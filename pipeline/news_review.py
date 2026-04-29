"""Daily Discord preview: would the bot post a news-augmented story today?

Runs find_top_story(), composes the would-be Bluesky caption, and sends
it to a Discord webhook for review. No live Bluesky posting.

Env vars:
  DISCORD_WEBHOOK_URL_HORMUZ  Discord webhook URL. If unset, prints to stdout.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from find_news import find_top_story

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL_HORMUZ")
ROOT = Path(__file__).resolve().parent.parent
TRANSITS_JSON = ROOT / "site" / "data" / "transits.json"
CLOSURE_DATE = datetime(2026, 3, 4, tzinfo=timezone.utc).date()
HASHTAGS = "#StraitOfHormuz #Shipping #Geopolitics #Maritime"
SITE_URL = "hormuz-traffic.com"


def load_data() -> dict:
    return json.loads(TRANSITS_JSON.read_text(encoding="utf-8"))


def build_caption(data: dict, story: dict | None) -> str:
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

    parts = [stat]
    if story:
        outlets = story["whitelisted_outlets"]
        listed = ", ".join(outlets[:4])
        if len(outlets) > 4:
            listed += f", +{len(outlets) - 4} more"
        parts.append(
            f"📰 {story['headline']}\n   Picked up by {listed}"
        )
    parts.append(HASHTAGS)
    parts.append(SITE_URL)
    return "\n\n".join(parts)


def discord_message(caption: str, story: dict | None) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if story:
        header = (
            f"**Hormuz news preview — {ts}**\n"
            f"Cluster matched: **{story['article_count']} articles**, "
            f"**{len(story['whitelisted_outlets'])} whitelisted outlets** "
            f"({len(story['all_outlets'])} total).\n"
            f"Lead: <{story['url']}>"
        )
    else:
        header = (
            f"**Hormuz news preview — {ts}**\n"
            "_No corroborated story today (no cluster with ≥3 whitelisted outlets in last 36h)._\n"
            "Post would be data-only."
        )
    return f"{header}\n```\n{caption}\n```"


def send_discord(content: str) -> None:
    if not WEBHOOK:
        print("DISCORD_WEBHOOK_URL_HORMUZ not set — printing to stdout instead:\n")
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
    caption = build_caption(data, story)
    msg = discord_message(caption, story)
    send_discord(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
