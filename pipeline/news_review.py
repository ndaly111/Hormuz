"""Daily Discord preview: would the bot post a news-augmented story today?

Runs find_top_story(), composes the would-be Bluesky caption, and sends
it to a Discord webhook for review. No live Bluesky posting.

Env vars:
  DISCORD_WEBHOOK  Discord webhook URL. If unset, prints to stdout.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from find_news import find_top_story
from compose_headline import HeadlineRequest, compose as compose_headline

WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
ROOT = Path(__file__).resolve().parent.parent
TRANSITS_JSON = ROOT / "site" / "data" / "transits.json"
CLOSURE_DATE = datetime(2026, 3, 4, tzinfo=timezone.utc).date()
HASHTAGS = "#StraitOfHormuz #Shipping #Geopolitics #Maritime"
SITE_URL = "hormuz-traffic.com"


def load_data() -> dict:
    return json.loads(TRANSITS_JSON.read_text(encoding="utf-8"))


def build_caption(data: dict, story: dict | None, lede: str | None) -> str:
    """Compose the would-be Bluesky caption.

    With a story + Claude-composed lede:
        <lede>
        Day N of closure: 7-day avg X ships/day (Y% vs norm)
        Reported by Reuters, BBC, NYT, +5 more
        #hashtags
        url

    Without a story:
        Day N of closure: 7-day avg X ships/day (Y% vs norm)
        #hashtags
        url
    """
    cur = data["current"]
    latest = datetime.fromisoformat(cur["latest_date"]).date()
    days_since = (latest - CLOSURE_DATE).days + 1
    pct = cur.get("vs_pre_feb_2026_pct")
    pct_s = f"{pct:+.1f}%" if pct is not None else "n/a"
    avg = cur.get("last_7d_avg")
    avg_s = f"{avg:,.1f}" if avg is not None else "n/a"

    stat = (
        f"Day {days_since} of Hormuz closure: "
        f"7-day avg {avg_s} ships/day ({pct_s} vs pre-closure norm)"
    )

    parts: list[str] = []
    if lede:
        parts.append(lede)
    parts.append(stat)
    if story:
        outlets = story["whitelisted_outlets"]
        listed = ", ".join(outlets[:4])
        if len(outlets) > 4:
            listed += f", +{len(outlets) - 4} more"
        parts.append(f"📰 Reported by {listed}")
    parts.append(HASHTAGS)
    parts.append(SITE_URL)
    return "\n\n".join(parts)


def get_lede(data: dict, story: dict) -> str | None:
    """Ask Claude to compose a sharp lede across the cluster's headlines."""
    cur = data["current"]
    pre_norm = (
        data.get("baselines", {})
            .get("pre_feb_2026", {})
            .get("avg_total")
        or 0.0
    )
    latest = datetime.fromisoformat(cur["latest_date"]).date()
    days_since = (latest - CLOSURE_DATE).days + 1
    req = HeadlineRequest(
        cluster_headlines=story.get("cluster_headlines", [story["headline"]]),
        outlets=story["whitelisted_outlets"],
        days_since_closure=days_since,
        seven_day_avg=float(cur.get("last_7d_avg") or 0.0),
        thirty_day_avg=float(cur.get("last_30d_avg") or 0.0),
        pct_vs_norm=float(cur.get("vs_pre_feb_2026_pct") or 0.0),
        pre_closure_norm=float(pre_norm),
        article_bodies=story.get("article_bodies") or None,
    )
    return compose_headline(req)


def discord_message(caption: str, story: dict | None, lede: str | None) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if story:
        cluster_block = "\n".join(f"  • {h}" for h in story.get("cluster_headlines", [])[:5])
        lede_status = (
            f"_Composed by Claude:_ {lede}" if lede
            else "_(Claude lede unavailable — fell back to cluster repr.)_"
        )
        header = (
            f"**Hormuz news preview — {ts}**\n"
            f"Cluster matched: **{story['article_count']} articles**, "
            f"**{len(story['whitelisted_outlets'])} whitelisted outlets** "
            f"({len(story['all_outlets'])} total).\n"
            f"Lead URL: <{story['url']}>\n\n"
            f"**Source headlines:**\n{cluster_block}\n\n"
            f"{lede_status}"
        )
    else:
        header = (
            f"**Hormuz news preview — {ts}**\n"
            "_No corroborated story today (no cluster with ≥3 whitelisted outlets in last 36h)._\n"
            "Post would be data-only."
        )
    return f"{header}\n\n**Proposed Bluesky post:**\n```\n{caption}\n```"


def send_discord(content: str) -> None:
    if not WEBHOOK:
        print("DISCORD_WEBHOOK not set — printing to stdout instead:\n")
        print(content)
        return
    # Discord webhook content is limited to 2000 chars; truncate if needed
    if len(content) > 1900:
        content = content[:1900] + "…"
    r = requests.post(WEBHOOK, json={"content": content}, timeout=30)
    if not r.ok:
        print(f"Discord post failed: {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    data = load_data()
    story = find_top_story()
    lede = get_lede(data, story) if story else None
    caption = build_caption(data, story, lede)
    msg = discord_message(caption, story, lede)
    bodies = (story or {}).get("article_bodies") or []
    print("\n========== NEWS PREVIEW ==========\n")
    print(f"Article bodies extracted: {len(bodies)}")
    if bodies:
        for b in bodies:
            print(f"  - {b.get('outlet')}: {len(b.get('body', ''))} chars")
    print(f"\nComposed lede: {lede!r}\n")
    print("---- Discord message ----")
    print(msg)
    print("\n========== END PREVIEW ==========\n")
    send_discord(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
