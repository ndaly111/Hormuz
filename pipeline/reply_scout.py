"""Daily reply bot: find high-engagement Hormuz posts and reply with a data point.

Searches Bluesky for posts about Strait of Hormuz / Iran / oil / shipping in
the last 24h from accounts with reach (>= MIN_LIKES), asks Claude for ONE
reply that adds a specific number from our chart or a buried fact from
today's news cluster, validates it mechanically, and posts it under the
target with today's chart image attached.

Autoposting was switched on 2026-09-24. From May to September the drafts
went to Discord for manual copy-paste and not one was ever posted; for a
76-follower account a reply under a 500-like post is the only reach there
is. Guardrails, in order:

  - hard cap MAX_REPLIES_PER_DAY, counted from reply_log.json, so a second
    run the same day can't double it
  - one reply per author per AUTHOR_COOLDOWN_DAYS; never the same post twice
  - only top-level posts with >= MIN_LIKES from the last LOOKBACK
  - every reply must pass validate_reply(): a concrete number, at most
    MAX_REPLY_CHARS, no link, no @-mention, no hashtag, no em dash, no
    emoji, none of the banned filler
  - Claude may answer SKIP for posts that are hostile, sarcastic, or not
    actually about Hormuz shipping
  - kill switch: REPLY_AUTOPOST != "true" -> report-only (drafts to Discord,
    nothing posted). Set the repo variable REPLY_AUTOPOST=false to stop.

Every posted reply is appended to pipeline/reply_log.json (committed by
the workflow) with the target and our follower count at the time, so the
trial can be judged on follower delta and reply engagement.

Run via .github/workflows/reply-scout.yml (daily 14:00 UTC).

Env:
  BLUESKY_HANDLE, BLUESKY_APP_PASSWORD   required
  ANTHROPIC_API_KEY                      required for drafting
  DISCORD_WEBHOOK                        run summary; falls back to stdout
  REPLY_AUTOPOST                         "true" to post; anything else = report only

CLI:
  --dry-run   search + draft + validate, print everything, post and write nothing
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
TRANSITS_JSON = ROOT / "site" / "data" / "transits.json"
REPLY_LOG = ROOT / "pipeline" / "reply_log.json"

SEARCH_KEYWORDS = [
    "Strait of Hormuz",
    "Hormuz blockade",
    "Iran tanker",
    "Iranian oil",
    "Bab el-Mandeb",
    "OPEC oil",
]

OUR_HANDLE = os.environ.get("BLUESKY_HANDLE", "hormuz-traffic.bsky.social")
LOOKBACK = timedelta(hours=24)
MIN_LIKES = 25
MAX_CANDIDATES = 8            # bound on Claude calls per run
MAX_REPLIES_PER_DAY = 2
AUTHOR_COOLDOWN_DAYS = 7
MAX_REPLY_CHARS = 200
AUTOPOST = os.environ.get("REPLY_AUTOPOST", "").strip().lower() == "true"

MODEL = os.environ.get("ANTHROPIC_HEADLINE_MODEL", "claude-haiku-4-5-20251001")

# Style rules from the old draft prompt, now enforced in code as well.
# Single words match on word boundaries ("navigate" is banned, "navigation"
# is not); phrases match as substrings.
BANNED_PHRASES = (
    "amid", "ongoing", "remains", "mounting", "escalating", "navigate",
    "underscore", "robust", "reportedly", "allegedly", "potentially",
    "as tensions mount", "raises questions", "growing concerns",
    "in the wake of", "thoughts?",
)
_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF☀-➿⭐⭕]")


def _bsky_client():
    """Logged-in atproto client. searchPosts requires auth on bsky.app."""
    pw = os.environ.get("BLUESKY_APP_PASSWORD")
    from atproto import Client
    client = Client()
    if OUR_HANDLE and pw:
        client.login(OUR_HANDLE, pw)
    return client


@dataclass
class Candidate:
    uri: str
    cid: str
    author_handle: str
    author_display: str
    text: str
    likes: int
    reposts: int
    replies: int
    created_at: str
    web_url: str


def web_url_for(handle: str, uri: str) -> str:
    try:
        return f"https://bsky.app/profile/{handle}/post/{uri.split('/')[-1]}"
    except Exception:
        return uri


def search_keyword(client, keyword: str, since_iso: str) -> list:
    """Returns a list of post views from the atproto SDK."""
    try:
        resp = client.app.bsky.feed.search_posts({
            "q": keyword,
            "limit": 50,
            "sort": "top",
            "since": since_iso,
            "lang": "en",
        })
        return list(resp.posts or [])
    except Exception as e:
        print(f"  search failed for {keyword!r}: {e}", file=sys.stderr)
        return []


def collect_candidates(client, now: datetime) -> list[Candidate]:
    since_iso = (now - LOOKBACK).isoformat(timespec="seconds")
    seen_uris: set[str] = set()
    out: list[Candidate] = []
    for kw in SEARCH_KEYWORDS:
        posts = search_keyword(client, kw, since_iso)
        print(f"  '{kw}': {len(posts)} results")
        for p in posts:
            uri = getattr(p, "uri", None)
            if not uri or uri in seen_uris:
                continue
            seen_uris.add(uri)
            author = getattr(p, "author", None)
            handle = getattr(author, "handle", "") if author else ""
            if handle == OUR_HANDLE:
                continue
            rec = getattr(p, "record", None)
            text = (getattr(rec, "text", "") or "").strip() if rec else ""
            if len(text) < 20:
                continue
            # Skip replies; top-level posts give our reply better visibility
            if rec and getattr(rec, "reply", None):
                continue
            likes = getattr(p, "like_count", 0) or 0
            if likes < MIN_LIKES:
                continue
            out.append(Candidate(
                uri=uri,
                cid=getattr(p, "cid", "") or "",
                author_handle=handle,
                author_display=getattr(author, "display_name", handle) or handle,
                text=text,
                likes=likes,
                reposts=getattr(p, "repost_count", 0) or 0,
                replies=getattr(p, "reply_count", 0) or 0,
                created_at=getattr(rec, "created_at", "") if rec else "",
                web_url=web_url_for(handle, uri),
            ))
    out.sort(key=lambda c: c.likes + 3 * c.reposts + 5 * c.replies, reverse=True)
    return out[:MAX_CANDIDATES]


def load_chart_context() -> dict:
    """Pull today's traffic data so Claude can quote it in replies."""
    try:
        data = json.loads(TRANSITS_JSON.read_text(encoding="utf-8"))
        cur = data.get("current", {})
        pre_norm = (
            data.get("baselines", {}).get("pre_feb_2026", {}).get("avg_total")
            or 0.0
        )
        sd = float(cur.get("last_7d_avg") or 0.0)
        pct_of_norm = (sd / pre_norm * 100) if pre_norm > 0 else 0.0
        from datetime import date
        latest = datetime.fromisoformat(cur["latest_date"]).date()
        days_since = (latest - date(2026, 3, 4)).days + 1
        return {
            "seven_day_avg": sd,
            "pre_norm": pre_norm,
            "pct_of_norm": pct_of_norm,
            "pct_below_norm": -float(cur.get("vs_pre_feb_2026_pct") or 0.0),
            "days_since": days_since,
        }
    except Exception as e:
        print(f"  chart context load failed: {e}", file=sys.stderr)
        return {}


def load_news_context() -> Optional[dict]:
    """Try to pull today's news cluster so Claude can pull buried facts.
    Optional — if it fails, replies still work with chart data alone."""
    try:
        from find_news import find_top_story
    except ImportError:
        return None
    try:
        story = find_top_story()
        if not story:
            return None
        return {
            "headline": story.get("headline"),
            "outlets": story.get("whitelisted_outlets") or [],
            "cluster_headlines": story.get("cluster_headlines") or [],
            "article_bodies": story.get("article_bodies") or [],
        }
    except Exception as e:
        print(f"  news context load failed: {e}", file=sys.stderr)
        return None


REPLY_SYSTEM = """\
You are replying as @hormuz-traffic.bsky.social, an account that publishes
daily Strait of Hormuz vessel-traffic data with a chart. You will be given
a post from another Bluesky account about Iran / Hormuz / oil / shipping.

Write ONE reply, or the single word SKIP.

Answer SKIP when the post is hostile, sarcastic, a joke, a flame war, not
actually about shipping through Hormuz, or when you have nothing concrete
to add. Skipping is always acceptable; a weak reply is not.

THE REPLY MUST:
- Add one specific data point from our chart, OR one buried fact from
  today's news cluster. A concrete number is mandatory.
- Be 1-2 sentences, under 200 characters.
- Read like a person typing on Bluesky, not a model.
- Move the conversation forward (not just agree, not just compliment).
- Stand on its own: it is posted publicly under their post, with our
  chart image attached.

NEVER:
- Use em dashes.
- Use "amid", "ongoing", "remains", "mounting", "escalating", "navigate",
  "underscore", "robust", "reportedly", "allegedly", "potentially",
  "as tensions mount", "raises questions", "growing concerns", "in the wake of".
- Link, @-mention, use hashtags, or self-promote (reads as spam).
- Use emojis.
- Ask "thoughts?" or any filler question.
- Wrap the reply in quotes, number it, add a preamble, or explain yourself.

Output: the reply text alone, or SKIP.
"""


def draft_reply(cand: Candidate, chart: dict, news: Optional[dict]) -> Optional[str]:
    """Raw model output for one candidate, or None if drafting is unavailable."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        return None

    chart_block = (
        f"Our chart data (for citing):\n"
        f"  - Day {chart.get('days_since', '?')} of Hormuz closure\n"
        f"  - 7-day avg: {chart.get('seven_day_avg', 0):.1f} ships/day\n"
        f"  - Currently {chart.get('pct_of_norm', 0):.0f}% of pre-war norm "
        f"({chart.get('pct_below_norm', 0):.0f}% below norm)\n"
    )

    news_block = ""
    if news:
        outlets = ", ".join(news.get("outlets", [])[:5])
        cluster_block = "\n".join(f"  - {h}" for h in news.get("cluster_headlines", [])[:5])
        news_block = (
            f"\nToday's news cluster (covered by {outlets}):\n{cluster_block}\n"
        )
        bodies = news.get("article_bodies") or []
        if bodies:
            news_block += "\nArticle bodies (scan for buried facts):\n"
            for art in bodies[:2]:  # cap to 2 to keep prompt size sane
                outlet = art.get("outlet", "?")
                body = (art.get("body") or "")[:1000]
                news_block += f"\n--- {outlet} ---\n{body}\n"

    user_msg = (
        f"Post we're replying to (@{cand.author_handle}, {cand.likes} likes):\n"
        f"  {cand.text}\n\n"
        f"{chart_block}{news_block}\n"
        "Write the reply, or SKIP."
    )

    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=200,
            # anthropic 1.x dropped temperature from the messages.create()
            # signature (TypeError); the API still honours it via extra_body.
            # Same fix as compose_headline.
            extra_body={"temperature": 0.5},
            system=REPLY_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        print(f"  draft failed for {cand.uri}: {e}", file=sys.stderr)
        return None
    if not resp.content or resp.content[0].type != "text":
        return None
    return resp.content[0].text.strip()


def parse_draft(raw: str) -> str:
    """Normalize model output to one line. Strips a leading '1.' / bullet
    that the old multi-option prompt trained the model to produce."""
    t = raw.strip()
    t = re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", t)
    return " ".join(t.split())


def validate_reply(text: str) -> Optional[str]:
    """Return why `text` must not be posted, or None if it passes."""
    t = text.strip()
    if not t or t.upper() == "SKIP":
        return "skip"
    if len(t) > MAX_REPLY_CHARS:
        return f"too long ({len(t)} > {MAX_REPLY_CHARS})"
    if not re.search(r"\d", t):
        return "no concrete number"
    if re.search(r"https?://|\bwww\.|\.(com|org|net|io)\b", t, re.I):
        return "contains a link"
    if "@" in t:
        return "contains an @-mention"
    if "#" in t:
        return "contains a hashtag"
    if "—" in t:
        return "em dash"
    if _EMOJI_RE.search(t):
        return "emoji"
    if t[0] in "\"'“‘" and t[-1] in "\"'”’":
        return "wrapped in quotes"
    low = t.lower()
    for phrase in BANNED_PHRASES:
        if " " in phrase or not phrase.isalpha():
            hit = phrase in low
        else:
            hit = re.search(rf"\b{re.escape(phrase)}\b", low) is not None
        if hit:
            return f"banned phrase {phrase!r}"
    return None


def load_reply_log() -> list[dict]:
    try:
        return json.loads(REPLY_LOG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_reply_log(log: list[dict]) -> None:
    REPLY_LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


def replies_today(log: list[dict], now: datetime) -> int:
    day = now.date().isoformat()
    return sum(1 for e in log if e.get("ts", "")[:10] == day and e.get("reply_uri"))


def ineligible_reason(cand: Candidate, log: list[dict], now: datetime) -> Optional[str]:
    """Why we must not reply to this candidate, or None."""
    cutoff = now - timedelta(days=AUTHOR_COOLDOWN_DAYS)
    for e in log:
        if e.get("target_uri") == cand.uri:
            return "already replied to this post"
    for e in log:
        if e.get("target_author") != cand.author_handle or not e.get("reply_uri"):
            continue
        try:
            ts = datetime.fromisoformat(e["ts"])
        except (KeyError, ValueError):
            continue
        if ts >= cutoff:
            return f"replied to @{cand.author_handle} within {AUTHOR_COOLDOWN_DAYS} days"
    return None


def todays_chart_image(client):
    """Reuse the image blob from our most recent chart post so every reply
    carries the current chart without re-rendering it (blobs are per-repo
    and any number of our records may reference one). None if not found."""
    from atproto import models
    try:
        feed = client.get_author_feed(actor=OUR_HANDLE, limit=10, filter="posts_no_replies").feed
    except Exception as e:
        print(f"  could not fetch our feed for the chart image: {e}", file=sys.stderr)
        return None
    for item in feed:
        if getattr(item, "reason", None):
            continue
        embed = getattr(item.post.record, "embed", None)
        images = getattr(embed, "images", None)
        if images:
            img = images[0]
            alt = img.alt or "Hormuz Strait daily vessel transit chart. Source: IMF PortWatch."
            return models.AppBskyEmbedImages.Main(
                images=[models.AppBskyEmbedImages.Image(alt=alt, image=img.image)]
            )
    return None


def post_reply(client, cand: Candidate, text: str, image) -> str:
    """Post `text` as a reply to `cand` (root == parent: we only reply to
    top-level posts). Returns the reply URI."""
    from atproto import models
    ref = models.ComAtprotoRepoStrongRef.Main(uri=cand.uri, cid=cand.cid)
    resp = client.send_post(
        text=text,
        reply_to=models.AppBskyFeedPost.ReplyRef(parent=ref, root=ref),
        embed=image,
    )
    return resp.uri


def post_discord(content: str) -> None:
    webhook = os.environ.get("DISCORD_WEBHOOK")
    if not webhook:
        print("DISCORD_WEBHOOK not set, printing to stdout:\n")
        print(content)
        return
    remaining = content
    while remaining:
        if len(remaining) <= 1900:
            chunk, remaining = remaining, ""
        else:
            cut = remaining.rfind("\n", 0, 1900)
            if cut < 1500:
                cut = 1900
            chunk = remaining[:cut]
            remaining = remaining[cut:].lstrip()
        r = requests.post(webhook, json={"content": chunk}, timeout=30)
        if not r.ok:
            print(f"Discord post failed: {r.status_code} {r.text}", file=sys.stderr)
            return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Search, draft and validate; post and write nothing.")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    live = AUTOPOST and not args.dry_run
    mode = "LIVE" if live else ("dry-run" if args.dry_run else "report-only (REPLY_AUTOPOST off)")
    print(f"Reply bot — {now:%Y-%m-%d %H:%M UTC} — {mode}")
    header = f"**Reply bot — {now:%Y-%m-%d %H:%M UTC} — {mode}**\n"

    try:
        client = _bsky_client()
    except Exception as e:
        print(f"Bluesky login failed: {e}", file=sys.stderr)
        post_discord(header + f"_Could not log in to Bluesky: {e}_")
        return 1

    followers = None
    try:
        followers = client.get_profile(OUR_HANDLE).followers_count
    except Exception as e:
        print(f"  follower count unavailable: {e}", file=sys.stderr)

    log = load_reply_log()
    budget = MAX_REPLIES_PER_DAY - replies_today(log, now)
    if budget <= 0:
        print("Daily reply cap already reached; nothing to do.")
        post_discord(header + "_Daily reply cap already reached._")
        return 0

    print("Searching Bluesky...")
    candidates = collect_candidates(client, now)
    print(f"\n{len(candidates)} candidates after filtering")
    if not candidates:
        post_discord(header + f"No qualifying posts in the last 24h "
                              f"(min {MIN_LIKES} likes across {len(SEARCH_KEYWORDS)} keywords).")
        return 0

    chart = load_chart_context()
    news = load_news_context()
    image = todays_chart_image(client) if live else None
    if live and image is None:
        print("  no chart image found on our recent posts; replies go out text-only")

    posted: list[tuple[Candidate, str, Optional[str]]] = []
    skipped: list[tuple[Candidate, str]] = []
    for c in candidates:
        if len(posted) >= budget:
            break
        why = ineligible_reason(c, log, now)
        if why:
            skipped.append((c, why))
            continue
        raw = draft_reply(c, chart, news)
        if raw is None:
            skipped.append((c, "no draft (API key missing or call failed)"))
            continue
        text = parse_draft(raw)
        why = validate_reply(text)
        if why:
            skipped.append((c, "model said SKIP" if why == "skip" else f"{why}: {text!r}"))
            continue

        reply_uri = None
        if live:
            try:
                reply_uri = post_reply(client, c, text, image)
            except Exception as e:
                skipped.append((c, f"post failed: {e}"))
                continue
            log.append({
                "ts": now.isoformat(timespec="seconds"),
                "target_uri": c.uri,
                "target_url": c.web_url,
                "target_author": c.author_handle,
                "target_likes": c.likes,
                "reply_uri": reply_uri,
                "text": text,
                "image": image is not None,
                "followers": followers,
            })
            save_reply_log(log)
        posted.append((c, text, reply_uri))

    lines = [header]
    verb = "Posted" if live else "Would post"
    lines.append(f"{verb} {len(posted)} of {budget} allowed today. Followers: {followers}.")
    for c, text, uri in posted:
        link = f" → <{web_url_for(OUR_HANDLE, uri)}>" if uri else ""
        lines.append(f"• @{c.author_handle} ({c.likes}♥) <{c.web_url}>{link}\n  > {text}")
    if skipped:
        lines.append(f"\nSkipped {len(skipped)}:")
        for c, why in skipped:
            lines.append(f"• @{c.author_handle} ({c.likes}♥): {why}")
    summary = "\n".join(lines)

    print("\n========== REPLY BOT SUMMARY ==========\n")
    print(summary)
    print("\n========== END ==========\n")
    post_discord(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
