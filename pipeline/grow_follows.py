"""Weekly follow scout: follow a small number of accounts active in our niche.

Searches recent Bluesky posts for Hormuz/oil/shipping keywords, scores the
authors on relevance (bio keywords, how often they showed up across queries,
audience size), and follows the top few. Follow-backs are the main follower
source for small accounts; this keeps it slow and targeted.

Hard limits, in order of importance:
  - MAX_FOLLOWS_PER_RUN per run (weekly cron) — deliberately tiny
  - stops entirely once the account follows TOTAL_FOLLOW_CAP accounts
  - never unfollows (no follow-churn, ever)
  - skips anyone already followed, muted, blocked, or blocking us

Appends every follow to pipeline/follow_log.json (committed by the workflow)
so the graph growth is auditable next to the engagement ledger.

Run via .github/workflows/follow-scout.yml (Mondays 15:00 UTC).

Env:
  BLUESKY_HANDLE         default: hormuz-traffic.bsky.social
  BLUESKY_APP_PASSWORD   required
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLLOW_LOG = ROOT / "pipeline" / "follow_log.json"

HANDLE = os.environ.get("BLUESKY_HANDLE", "hormuz-traffic.bsky.social")
APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD")

MAX_FOLLOWS_PER_RUN = 10
TOTAL_FOLLOW_CAP = 400
MIN_FOLLOWERS = 25       # skip empty/abandoned accounts
MAX_FOLLOWERS = 50_000   # whales won't follow back; not worth a slot

SEARCH_QUERIES = [
    "Strait of Hormuz",
    "Hormuz shipping",
    "Iran oil exports",
    "tanker tracking",
    "#OOTT",
]

# Relevance signal: any of these in the author's bio.
BIO_KEYWORDS = [
    "oil", "tanker", "maritime", "shipping", "energy", "osint", "geopolit",
    "navy", "naval", "gulf", "iran", "commodit", "freight", "trade",
    "middle east", "defense", "defence", "sanctions",
]


def main() -> int:
    if not APP_PASSWORD:
        print("ERROR: BLUESKY_APP_PASSWORD env var not set", file=sys.stderr)
        return 2

    from atproto import Client

    client = Client()
    client.login(HANDLE, APP_PASSWORD)
    me = client.me.did

    my_profile = client.app.bsky.actor.get_profile({"actor": me})
    if (my_profile.follows_count or 0) >= TOTAL_FOLLOW_CAP:
        print(f"Follow cap reached ({my_profile.follows_count}/{TOTAL_FOLLOW_CAP}); doing nothing.")
        return 0

    # 1. Collect authors of recent on-topic posts.
    candidates: dict[str, dict] = {}
    for q in SEARCH_QUERIES:
        try:
            res = client.app.bsky.feed.search_posts({"q": q, "limit": 50, "sort": "latest"})
        except Exception as e:
            print(f"  search {q!r} failed: {e}", file=sys.stderr)
            continue
        for p in res.posts:
            a = p.author
            if a.did == me:
                continue
            if a.did in candidates:
                candidates[a.did]["hits"] += 1
            else:
                candidates[a.did] = {"handle": a.handle, "hits": 1}
    print(f"Collected {len(candidates)} unique authors from {len(SEARCH_QUERIES)} queries.")

    # 2. Hydrate profiles (25 per call) and filter/score.
    dids = list(candidates)
    profiles = []
    for i in range(0, len(dids), 25):
        try:
            profiles += client.app.bsky.actor.get_profiles({"actors": dids[i:i + 25]}).profiles
        except Exception as e:
            print(f"  get_profiles batch failed: {e}", file=sys.stderr)

    scored = []
    for p in profiles:
        v = p.viewer
        if v and (v.following or v.muted or v.blocked_by or v.blocking):
            continue
        followers = p.followers_count or 0
        if not (MIN_FOLLOWERS <= followers <= MAX_FOLLOWERS):
            continue
        bio = (p.description or "").lower()
        kw_hits = sum(1 for k in BIO_KEYWORDS if k in bio)
        hits = candidates[p.did]["hits"]
        # Require either a relevant bio or repeated topical posting.
        if kw_hits == 0 and hits < 2:
            continue
        score = kw_hits * 10 + hits * 5 + min(followers, 5000) / 1000
        scored.append((score, p, kw_hits, hits))
    scored.sort(key=lambda t: -t[0])
    print(f"{len(scored)} candidates passed filters.")

    # 3. Follow the top few and log.
    try:
        log = json.loads(FOLLOW_LOG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    followed = 0
    for score, p, kw_hits, hits in scored[:MAX_FOLLOWS_PER_RUN]:
        try:
            client.follow(p.did)
        except Exception as e:
            print(f"  follow {p.handle} failed: {e}", file=sys.stderr)
            continue
        followed += 1
        log.append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "did": p.did,
            "handle": p.handle,
            "followers_count": p.followers_count,
            "bio_keyword_hits": kw_hits,
            "query_hits": hits,
            "score": round(score, 1),
        })
        print(f"  followed @{p.handle} (followers={p.followers_count}, "
              f"bio_kw={kw_hits}, query_hits={hits})")

    FOLLOW_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"Done: followed {followed} accounts this run "
          f"({(my_profile.follows_count or 0) + followed}/{TOTAL_FOLLOW_CAP} total).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
