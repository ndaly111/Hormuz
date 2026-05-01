"""One-shot: backfill engagement_log.json from the author's existing feed.

Use this once to seed the ledger with historical posts that existed before
the live append-on-post hook landed. Idempotent — won't duplicate URIs.

Run: python pipeline/backfill_ledger.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "pipeline" / "engagement_log.json"
HANDLE = "hormuz-traffic.bsky.social"
GET_AUTHOR_FEED = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"


def fetch_feed(handle: str, limit: int = 100) -> list[dict]:
    out: list[dict] = []
    cursor: str | None = None
    while len(out) < limit:
        params = {"actor": handle, "limit": min(50, limit - len(out))}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(GET_AUTHOR_FEED, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("feed", []))
        cursor = data.get("cursor")
        if not cursor:
            break
    return out


def main() -> int:
    try:
        existing = json.loads(LEDGER.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []
    seen_uris = {e.get("post_uri") for e in existing}

    feed = fetch_feed(HANDLE, limit=200)
    print(f"Fetched {len(feed)} feed items for @{HANDLE}")

    now = datetime.now(timezone.utc)
    added = 0
    for item in feed:
        if item.get("reason"):  # skip reposts
            continue
        post = item.get("post") or {}
        uri = post.get("uri")
        if not uri or uri in seen_uris:
            continue
        rec = post.get("record") or {}
        text = (rec.get("text") or "").strip()
        if not text:
            continue
        created = rec.get("createdAt", "")
        # Heuristic: a post that has the lede separator (\n\n) and starts with
        # something other than "Day N of" had a Claude lede.
        first_line = text.split("\n", 1)[0]
        had_lede = not first_line.startswith("Day ") and "of Hormuz closure:" not in first_line
        lede = first_line if had_lede else None

        entry = {
            "ts": created,
            "post_uri": uri,
            "lede": lede,
            "had_news_cluster": had_lede,
            "story_headline": None,
            "outlets": [],
            "article_count": None,
            "engagement": {
                "fetched_at": now.isoformat(timespec="seconds"),
                "likes": post.get("likeCount", 0) or 0,
                "reposts": post.get("repostCount", 0) or 0,
                "replies": post.get("replyCount", 0) or 0,
                "quotes": post.get("quoteCount", 0) or 0,
                "backfilled": True,
            },
        }
        existing.append(entry)
        added += 1

    # Sort chronologically by ts
    existing.sort(key=lambda e: e.get("ts", ""))
    LEDGER.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print(f"Added {added} new entries; ledger now has {len(existing)} total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
