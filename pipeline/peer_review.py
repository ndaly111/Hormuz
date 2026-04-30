"""Peer-account engagement review.

Pulls recent posts from a curated list of Bluesky accounts in adjacent
niches (geopolitics, maritime, breaking-news data, OSINT), ranks by
engagement, and asks Claude to extract patterns. Output goes to Discord.

One-off research task. Run manually via the peer-review workflow when
you want to refresh "what's working in adjacent niches" — not on a cron.
The output should inform manual updates to compose_headline.py's prompt.

Env vars:
  BLUESKY_HANDLE         For atproto auth (reuses daily-refresh secret)
  BLUESKY_APP_PASSWORD   "
  ANTHROPIC_API_KEY      Optional. Without it, only raw top-posts are sent.
  DISCORD_WEBHOOK        Where the report lands. Falls back to stdout.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from atproto import Client

SEED_ACCOUNTS = [
    "unusualwhales.bsky.social",
    "warmapper.org",
    "flightradar24.com",
    "reuters.com",
    "osinttechnical.bsky.social",
    "noelreports.com",
    "navalnews.com",
]

POSTS_PER_ACCOUNT = 100
MIN_AGE_DAYS = 2          # let engagement mature
MAX_AGE_DAYS = 60         # but stay recent enough to be relevant
TOP_N = 30                # how many top-engagement posts to feed Claude

MODEL = os.environ.get("ANTHROPIC_HEADLINE_MODEL", "claude-haiku-4-5-20251001")


@dataclass
class Post:
    handle: str
    text: str
    likes: int
    reposts: int
    replies: int
    score: int
    posted_at: datetime
    uri: str


def fetch_feed(client: Client, handle: str) -> list[Post]:
    posts: list[Post] = []
    cursor: Optional[str] = None
    fetched = 0
    while fetched < POSTS_PER_ACCOUNT:
        resp = client.get_author_feed(
            actor=handle,
            limit=min(50, POSTS_PER_ACCOUNT - fetched),
            cursor=cursor,
        )
        for item in resp.feed:
            # Skip reposts so we only study original content
            if getattr(item, "reason", None) is not None:
                continue
            p = item.post
            text = (getattr(p.record, "text", "") or "").strip()
            if len(text) < 10:
                continue
            likes = p.like_count or 0
            reposts = p.repost_count or 0
            replies = p.reply_count or 0
            score = likes + 3 * reposts + 5 * replies
            created = getattr(p.record, "created_at", None)
            try:
                posted_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                continue
            posts.append(Post(
                handle=handle,
                text=text,
                likes=likes,
                reposts=reposts,
                replies=replies,
                score=score,
                posted_at=posted_at,
                uri=p.uri,
            ))
            fetched += 1
        cursor = getattr(resp, "cursor", None)
        if not cursor:
            break
    return posts


def filter_window(posts: list[Post], now: datetime) -> list[Post]:
    not_too_new = now - timedelta(days=MIN_AGE_DAYS)
    not_too_old = now - timedelta(days=MAX_AGE_DAYS)
    return [p for p in posts if not_too_old <= p.posted_at <= not_too_new]


def analyze(top_posts: list[Post]) -> Optional[str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        return None

    blocks = []
    for i, p in enumerate(top_posts, 1):
        blocks.append(
            f"#{i} | @{p.handle} | likes={p.likes} reposts={p.reposts} "
            f"replies={p.replies} score={p.score}\n{p.text}\n"
        )
    sample = "\n".join(blocks)

    system = """\
You are analyzing high-engagement posts from Bluesky accounts in the breaking-news,
geopolitics, OSINT, and maritime niches. The user runs @hormuz-traffic.bsky.social,
an account that publishes daily Strait of Hormuz vessel-traffic data with a chart
and (when news warrants) a sharp news lede.

Goal: extract concrete, actionable patterns from these high-performers that the
user can copy into their own posting style. Avoid generic social-media advice
("use hashtags", "engage with replies"). Focus on what is specific in this
niche: sentence structure, verb choice, length, hook patterns, what gets
reposted vs replied vs liked, time-of-day cues, framing of data versus
commentary.

Format your output as Markdown with these sections:
1. **Top patterns** (3-5 bullets, each specific and actionable)
2. **Verbs and openings** (concrete examples worth imitating)
3. **What to avoid** (anti-patterns visible in lower performers if any)
4. **Proposed additions to the headline prompt** (3-5 bullets in
   prompt-instruction form, ready to paste into a system prompt)

Be terse and direct. No filler. No em dashes.
"""
    user_msg = (
        f"Top {len(top_posts)} highest-engagement posts from peer accounts "
        f"(score = likes + 3*reposts + 5*replies):\n\n{sample}\n\n"
        "Extract patterns and propose prompt additions."
    )

    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            temperature=0.3,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        print(f"Claude API failed: {e}", file=sys.stderr)
        return None
    if not resp.content or resp.content[0].type != "text":
        return None
    return resp.content[0].text.strip()


def post_discord(content: str) -> None:
    webhook = os.environ.get("DISCORD_WEBHOOK")
    if not webhook:
        print("DISCORD_WEBHOOK not set, printing to stdout:\n")
        print(content)
        return
    # Discord limit is 2000 chars; split on newlines
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
    handle = os.environ.get("BLUESKY_HANDLE")
    pw = os.environ.get("BLUESKY_APP_PASSWORD")
    client = Client()
    if handle and pw:
        try:
            client.login(handle, pw)
        except Exception as e:
            print(f"Login failed, continuing anonymous: {e}", file=sys.stderr)

    all_posts: list[Post] = []
    for h in SEED_ACCOUNTS:
        try:
            posts = fetch_feed(client, h)
            print(f"[{h}] fetched {len(posts)} posts")
            all_posts.extend(posts)
        except Exception as e:
            print(f"[{h}] failed: {e}", file=sys.stderr)

    now = datetime.now(timezone.utc)
    in_window = filter_window(all_posts, now)
    in_window.sort(key=lambda p: p.score, reverse=True)
    top = in_window[:TOP_N]

    if not top:
        post_discord("**Peer review:** no posts in window. Check seed accounts.")
        return 0

    header = (
        f"**Peer review — {now:%Y-%m-%d}**  "
        f"({len(SEED_ACCOUNTS)} accounts, {len(in_window)} posts in window, "
        f"top {len(top)} analyzed)\n\n"
        f"**Top 5 by engagement:**\n"
    )
    top5_lines = []
    for p in top[:5]:
        snippet = p.text.replace("\n", " ")[:160]
        top5_lines.append(
            f"- `@{p.handle}` — score {p.score} (♥ {p.likes}, ↻ {p.reposts}, "
            f"💬 {p.replies})\n  > {snippet}"
        )
    summary = header + "\n".join(top5_lines)

    analysis = analyze(top) or "_(Claude analysis unavailable. Set ANTHROPIC_API_KEY.)_"
    full = summary + "\n\n**Pattern analysis:**\n\n" + analysis

    # Always echo to stdout so the workflow log captures the full report
    print("\n========== PEER REVIEW REPORT ==========\n")
    print(full)
    print("\n========== END REPORT ==========\n")

    post_discord(full)
    return 0


if __name__ == "__main__":
    sys.exit(main())
