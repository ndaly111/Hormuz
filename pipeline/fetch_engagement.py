"""Fill in engagement metrics for posts in engagement_log.json.

Reads pipeline/engagement_log.json, finds entries that are:
  - at least 24h old (engagement has time to mature), and
  - either missing engagement entirely OR last fetched >24h ago

Calls the public Bluesky API getPosts in batches of 25 to retrieve
likeCount / repostCount / replyCount / quoteCount, writes results back
to the ledger, commits.

Runs daily via .github/workflows/fetch-engagement.yml.

Public API requires no auth — we read public engagement counts from the
appview directly.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "pipeline" / "engagement_log.json"

# Bluesky public AppView API — no auth required for public engagement counts
APPVIEW_GET_POSTS = "https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts"
BATCH_SIZE = 25  # API limit
MIN_AGE_HOURS = 24
REFETCH_AFTER_HOURS = 24  # re-poll ledger entries at most once per day


def needs_refetch(entry: dict, now: datetime) -> bool:
    """Should we (re)fetch engagement for this ledger entry?"""
    try:
        ts = datetime.fromisoformat(entry["ts"])
    except (KeyError, ValueError):
        return False
    if now - ts < timedelta(hours=MIN_AGE_HOURS):
        return False  # too fresh to bother
    eng = entry.get("engagement")
    if not eng:
        return True
    try:
        last_fetched = datetime.fromisoformat(eng["fetched_at"])
    except (KeyError, ValueError):
        return True
    return now - last_fetched >= timedelta(hours=REFETCH_AFTER_HOURS)


def fetch_batch(uris: list[str]) -> dict[str, dict]:
    """Hit getPosts for up to 25 URIs. Returns {uri: post_view}."""
    params = [("uris", u) for u in uris]
    r = requests.get(APPVIEW_GET_POSTS, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    out: dict[str, dict] = {}
    for p in data.get("posts", []):
        out[p["uri"]] = p
    return out


def main() -> int:
    if not LEDGER.exists():
        print(f"No ledger at {LEDGER}; nothing to do.")
        return 0

    try:
        entries: list[dict] = json.loads(LEDGER.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Could not parse ledger: {e}", file=sys.stderr)
        return 1

    if not isinstance(entries, list):
        print("Ledger root is not a list; refusing to overwrite.", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    pending = [e for e in entries if needs_refetch(e, now)]
    if not pending:
        print(f"No entries to refresh ({len(entries)} total in ledger).")
        return 0

    print(f"Refreshing engagement for {len(pending)} of {len(entries)} entries")

    by_uri = {e["post_uri"]: e for e in pending if e.get("post_uri")}
    uris = list(by_uri.keys())

    fetched_total = 0
    for i in range(0, len(uris), BATCH_SIZE):
        batch = uris[i:i + BATCH_SIZE]
        try:
            views = fetch_batch(batch)
        except Exception as e:
            print(f"  batch {i // BATCH_SIZE + 1} failed: {e}", file=sys.stderr)
            continue
        for uri, view in views.items():
            entry = by_uri.get(uri)
            if not entry:
                continue
            entry["engagement"] = {
                "fetched_at": now.isoformat(timespec="seconds"),
                "likes": view.get("likeCount", 0) or 0,
                "reposts": view.get("repostCount", 0) or 0,
                "replies": view.get("replyCount", 0) or 0,
                "quotes": view.get("quoteCount", 0) or 0,
            }
            fetched_total += 1
        # Mark URIs that didn't come back as deleted/private so we stop polling
        missing = [u for u in batch if u not in views]
        for u in missing:
            entry = by_uri.get(u)
            if entry and not entry.get("engagement"):
                entry["engagement"] = {
                    "fetched_at": now.isoformat(timespec="seconds"),
                    "likes": 0, "reposts": 0, "replies": 0, "quotes": 0,
                    "missing": True,
                }

    LEDGER.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    print(f"Updated {fetched_total} entries; ledger saved ({len(entries)} total).")

    # Print a small summary of recent posts so the workflow log is useful
    print("\n---- Last 5 posts ----")
    for e in entries[-5:]:
        eng = e.get("engagement") or {}
        ts = e.get("ts", "?")[:16]
        had = "📰" if e.get("had_news_cluster") else "📊"
        likes = eng.get("likes", "?")
        reposts = eng.get("reposts", "?")
        replies = eng.get("replies", "?")
        quotes = eng.get("quotes", "?")
        lede = (e.get("lede") or e.get("story_headline") or "[data-only]")[:80]
        print(f"  [{ts}] {had} L:{likes} R:{reposts} Reply:{replies} Q:{quotes}  {lede}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
