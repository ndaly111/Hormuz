"""
Posts the daily Hormuz transit chart + caption to Bluesky.

Reuses the existing /today page's share-image generator (today.js
`generateShareImage()`) and caption builder (`buildTweetText()`) so the
post matches the on-site share kit byte-for-byte — no duplicate design
logic to drift.

Flow:
  1. Start a local HTTP server over the site/ directory
  2. Launch headless chromium, load today.html, wait for init
  3. Extract the generated PNG (data URL) and caption text
  4. Post to Bluesky via atproto with image embed + clickable URL

Env:
  BLUESKY_HANDLE         default: hormuz-traffic.bsky.social
  BLUESKY_APP_PASSWORD   required unless --dry-run (from GitHub secret)
  SHARE_RANGE_KEY        default: d30   (one of d7/d30/closure/war/all)

CLI flags:
  --dry-run    render image + log caption, skip the actual Bluesky post.
               Writes PNG to pipeline/_latest_share.png for local preview.
"""
from __future__ import annotations

import argparse
import base64
import os
import socket
import sys
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"

# Keep in sync with CLOSURE_DATE in site/today.js
CLOSURE_DATE = "2026-03-04"

# Bluesky counts graphemes with a 300 cap. The link label is part of the text.
POST_CHAR_LIMIT = 300

HANDLE = os.environ.get("BLUESKY_HANDLE", "hormuz-traffic.bsky.social")
APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD")
RANGE_KEY = os.environ.get("SHARE_RANGE_KEY", "war")
SITE_URL = "https://hormuz-traffic.com"
SITE_LABEL = "hormuz-traffic.com"


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE_DIR), **kwargs)

    def log_message(self, *_args, **_kwargs):
        pass


def _start_server() -> tuple[HTTPServer, int]:
    port = _pick_free_port()
    srv = HTTPServer(("127.0.0.1", port), _QuietHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def capture_share_assets(port: int) -> tuple[bytes, str]:
    """Return (png_bytes, caption) from a live render of today.html."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1400, "height": 1000})
        page = context.new_page()
        page.goto(f"http://127.0.0.1:{port}/today.html", wait_until="networkidle")

        # Select requested range before image generation. today.js init()
        # defaults to d30, so we always click the requested range button
        # unless it happens to equal d30.
        if RANGE_KEY != "d30":
            page.evaluate(f"""(async () => {{
              document.querySelectorAll('.share-range-buttons .range-btn')
                .forEach(b => b.classList.remove('active'));
              const btn = document.querySelector(
                `.share-range-buttons .range-btn[data-range='{RANGE_KEY}']`);
              if (btn) {{ btn.classList.add('active'); btn.click(); }}
            }})()""")

        # Wait for share image to be ready
        page.wait_for_function(
            "document.getElementById('shareImage') && "
            "document.getElementById('shareImage').src && "
            "document.getElementById('shareImage').src.startsWith('data:image/png')",
            timeout=30000,
        )

        data_url = page.evaluate("() => document.getElementById('shareImage').src")
        caption = page.evaluate("() => document.getElementById('tweetText').value")
        browser.close()

    png_bytes = base64.b64decode(data_url.split(",", 1)[1])
    return png_bytes, caption.strip()


def _retry_connect(fn, what: str, attempts: int = 3, delay: int = 30):
    """Retry a network call, but ONLY on connection-establishment failures
    (ConnectError/ConnectTimeout fire before the request is sent, so a retry
    can never double-post). Any error after the connection is up — including
    read timeouts on send_post — raises immediately for the same reason.
    Seen in the wild 2026-07-17: a single TLS-handshake timeout to bsky.social
    killed the whole daily run."""
    import time

    import httpx

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            if attempt == attempts:
                raise
            print(f"  {what}: connection failed ({e!r}); "
                  f"retrying in {delay}s ({attempt}/{attempts - 1} retries used)")
            time.sleep(delay)


def post(png_bytes: bytes, caption: str) -> str:
    if not APP_PASSWORD:
        raise RuntimeError("BLUESKY_APP_PASSWORD not set")

    # Lazy import so --dry-run works without atproto installed
    from atproto import Client, client_utils, models

    client = Client()
    _retry_connect(lambda: client.login(HANDLE, APP_PASSWORD), "login")

    blob = _retry_connect(lambda: client.upload_blob(png_bytes), "upload_blob")

    # Build the rich-text post. Hashtags must be added via tb.tag() so they
    # become real Bluesky facets — without that they render as plain text and
    # don't surface in tag search or feed-curator pipelines. The caption from
    # today.js already includes them as plain "#Word" tokens; we split them
    # out here and tag-facet each one.
    import re
    HASHTAG_RE = re.compile(r"(#\w+)")

    tb = client_utils.TextBuilder()
    for part in HASHTAG_RE.split(caption):
        if not part:
            continue
        if HASHTAG_RE.match(part):
            tb.tag(part, part[1:])  # tb.tag(displayed_text, tag_value)
        else:
            tb.text(part)
    tb.text("\n\n")
    tb.link(SITE_LABEL, SITE_URL)

    alt = "Hormuz Strait daily vessel transit chart. Source: IMF PortWatch."
    response = _retry_connect(
        lambda: client.send_post(
            text=tb,
            embed=models.AppBskyEmbedImages.Main(
                images=[models.AppBskyEmbedImages.Image(alt=alt, image=blob.blob)]
            ),
        ),
        "send_post",
    )
    return response.uri


def build_recap_caption() -> str:
    """Weekly recap caption computed straight from transits.json — no news
    pipeline. Posted Sundays with the d30 chart for visual contrast."""
    import json
    from datetime import date

    data = json.loads((SITE_DIR / "data" / "transits.json").read_text(encoding="utf-8"))
    cur = data["current"]
    week = data["series"][-7:]
    best = max(week, key=lambda r: r["total"])
    worst = min(week, key=lambda r: r["total"])
    day_n = (date.fromisoformat(cur["latest_date"]) - date.fromisoformat(CLOSURE_DATE)).days

    def fmt_d(iso: str) -> str:
        d = date.fromisoformat(iso)
        return f"{d.strftime('%b')} {d.day}"

    return (
        f"Hormuz week in review — day {day_n} of the closure\n"
        f"7-day avg: {cur['last_7d_avg']:.1f} ships/day "
        f"({cur['vs_pre_feb_2026_pct']:+.0f}% vs pre-closure norm)\n"
        f"Busiest day: {fmt_d(best['date'])} ({best['total']} ships) · "
        f"Quietest: {fmt_d(worst['date'])} ({worst['total']})\n\n"
        f"#StraitOfHormuz #OOTT #Shipping #Maritime"
    )


def get_news_lede(rank: int = 0) -> tuple[str | None, dict | None]:
    """Try to compose a Claude news lede for today. Returns (lede, story).
    rank=0 = top cluster; rank=1 = second cluster (for the afternoon post).
    Either or both may be None if no qualifying story at that rank, no API
    key, or error. Never raises — the post must still go out as data-only
    on any failure."""
    try:
        from find_news import find_top_story
        from news_review import get_lede, load_data
    except ImportError as e:
        print(f"  news pipeline import failed: {e}")
        return None, None
    try:
        story = find_top_story(rank=rank)
        if not story:
            print(f"  no qualifying news cluster at rank {rank}")
            return None, None
        data = load_data()
        lede = get_lede(data, story)
        if not lede:
            # We had a real corroborated story and still posted data-only.
            # That is the silent-rot failure mode: an anthropic 1.x signature
            # change ate every lede from 2026-08-21 to 08-29 and nothing
            # surfaced it. Annotate the run so it shows up in Actions.
            _annotate_missing_lede(story)
        return lede, story
    except Exception as e:
        print(f"  lede composition failed: {e}", file=sys.stderr)
        return None, None


def _annotate_missing_lede(story: dict) -> None:
    """Emit a GitHub Actions error annotation for a story that got no lede.

    Deliberately does NOT fail the step — the data-only post is still worth
    sending. The workflow's final guard step turns this into a red run so a
    failure notification actually goes out.
    """
    msg = (
        f"News cluster found ({story.get('article_count')} articles, "
        f"{len(story.get('whitelisted_outlets') or [])} whitelisted outlets) "
        f"but Claude returned no lede — posting data-only. "
        f"Top headline: {story.get('headline')!r}"
    )
    print(f"  {msg}", file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::error title=Lede composition failed::{msg}")


def append_to_ledger(post_uri: str, lede: str | None, story: dict | None,
                     kind: str | None = None) -> None:
    """Append a post entry to engagement_log.json. Called once per successful
    Bluesky post. Engagement metrics are filled in later by fetch_engagement.py
    once the post is at least 24h old."""
    import json
    from datetime import datetime, timezone

    ledger_path = ROOT / "pipeline" / "engagement_log.json"
    try:
        existing = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "post_uri": post_uri,
        "lede": lede,
        "had_news_cluster": story is not None,
        "story_headline": (story or {}).get("headline"),
        "outlets": (story or {}).get("whitelisted_outlets") or [],
        "article_count": (story or {}).get("article_count"),
        "engagement": None,  # filled in by fetch_engagement.py
    }
    if kind:
        entry["kind"] = kind
    existing.append(entry)
    ledger_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print(f"  appended to engagement ledger ({len(existing)} entries)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Render + log caption, skip Bluesky post")
    parser.add_argument("--cluster-rank", type=int, default=0,
                        help="News cluster rank to use as the lede source. "
                             "0=top cluster (morning), 1=second cluster (afternoon).")
    parser.add_argument("--require-cluster", action="store_true",
                        help="Skip the post (exit 0) when no qualifying news "
                             "cluster exists at the requested rank. Used by the "
                             "afternoon workflow so quiet news days don't force "
                             "a redundant data-only second post.")
    parser.add_argument("--weekly-recap", action="store_true",
                        help="Post the Sunday week-in-review caption computed "
                             "from transits.json instead of the daily caption. "
                             "Skips the news-lede pipeline entirely.")
    args = parser.parse_args()

    if not args.dry_run and not APP_PASSWORD:
        print("ERROR: BLUESKY_APP_PASSWORD env var not set", file=sys.stderr)
        return 2

    if args.weekly_recap:
        lede, story = None, None
    else:
        lede, story = get_news_lede(rank=args.cluster_rank)
        if args.require_cluster and story is None:
            print(f"Skipping post — no qualifying cluster at rank {args.cluster_rank}.")
            return 0

    srv, port = _start_server()
    try:
        print(f"Local server on :{port}, rendering today.html (range={RANGE_KEY})")
        png, caption = capture_share_assets(port)
        print(f"  PNG: {len(png):,} bytes   Base caption: {caption!r}")

        if args.weekly_recap:
            caption = build_recap_caption()
            print(f"  Weekly recap caption: {caption!r}")
        elif lede:
            caption = f"{lede}\n\n{caption}"
            # News-day discovery tag; skip when it would push past the 300 cap
            # (the final post text also carries "\n\n" + the site-link label).
            budget = POST_CHAR_LIMIT - (len(caption) + 2 + len(SITE_LABEL))
            if budget >= len(" #Iran"):
                caption += " #Iran"
            print(f"  With Claude lede prepended: {caption!r}")
        else:
            print("  no lede; posting data-only caption")

        if args.dry_run:
            out = ROOT / "pipeline" / "_latest_share.png"
            out.write_bytes(png)
            print(f"DRY RUN — PNG saved to {out}, not posting.")
            print(f"DRY RUN — final caption:\n{caption}")
            return 0

        uri = post(png, caption)
        print(f"Posted to Bluesky: {uri}")
        try:
            append_to_ledger(uri, lede, story,
                             kind="weekly_recap" if args.weekly_recap else None)
        except Exception as e:
            print(f"  ledger append failed (non-fatal): {e}", file=sys.stderr)
        return 0
    finally:
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
