"""Daily reply-target scout: surface high-engagement Hormuz posts and draft replies.

Searches Bluesky for posts about Strait of Hormuz / Iran / oil / shipping
in the last 24h. Filters to posts with >=10 likes (engagement signal that
the post is from an account with reach, not a zero-follower account).
For each candidate, asks Claude to draft 2-3 reply options that add a
specific data point from our chart or a buried fact from today's news
cluster.

Output goes to Discord for MANUAL review and copy-paste reply. No auto-
replies — that gets accounts banned and reads as spam.

Run via .github/workflows/reply-scout.yml (manual or daily cron at 14:00 UTC).

Env:
  ANTHROPIC_API_KEY   For draft replies. Required.
  DISCORD_WEBHOOK     Where candidates land. Falls back to stdout.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
TRANSITS_JSON = ROOT / "site" / "data" / "transits.json"

SEARCH_KEYWORDS = [
    "Strait of Hormuz",
    "Hormuz blockade",
    "Iran tanker",
    "Iranian oil",
    "Bab el-Mandeb",
    "OPEC oil",
]

OUR_HANDLE = "hormuz-traffic.bsky.social"
LOOKBACK = timedelta(hours=24)
MIN_LIKES = 10
MAX_CANDIDATES = 8  # cap candidates fed to Claude to bound cost

MODEL = os.environ.get("ANTHROPIC_HEADLINE_MODEL", "claude-haiku-4-5-20251001")


def _bsky_client():
    """Logged-in atproto client. searchPosts now requires auth on bsky.app."""
    handle = os.environ.get("BLUESKY_HANDLE")
    pw = os.environ.get("BLUESKY_APP_PASSWORD")
    from atproto import Client
    client = Client()
    if handle and pw:
        client.login(handle, pw)
    return client


@dataclass
class Candidate:
    uri: str
    author_handle: str
    author_display: str
    text: str
    likes: int
    reposts: int
    replies: int
    created_at: str
    web_url: str


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
            try:
                rkey = uri.split("/")[-1]
                web_url = f"https://bsky.app/profile/{handle}/post/{rkey}"
            except Exception:
                web_url = uri
            out.append(Candidate(
                uri=uri,
                author_handle=handle,
                author_display=getattr(author, "display_name", handle) or handle,
                text=text,
                likes=likes,
                reposts=getattr(p, "repost_count", 0) or 0,
                replies=getattr(p, "reply_count", 0) or 0,
                created_at=getattr(rec, "created_at", "") if rec else "",
                web_url=web_url,
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
You are drafting reply candidates for @hormuz-traffic.bsky.social, an
account that publishes daily Strait of Hormuz vessel-traffic data with a
chart and (when news warrants) a sharp news lede.

You will be given a post from another Bluesky account about
Iran / Hormuz / oil / shipping / maritime crisis. Your job: draft 2-3
DISTINCT reply options that the human can pick from and copy-paste.

EACH REPLY MUST:
- Add a specific data point from our chart, OR surface a buried fact from
  today's news cluster. Concrete numbers, vessel names, named officials,
  direct quotes are gold.
- Be 1-2 sentences, under 200 characters.
- Read like a person typing on Bluesky, not a model.
- Move the conversation forward (not just agree, not just compliment).

NEVER:
- Use em dashes (—).
- Use "amid", "ongoing", "remains", "mounting", "escalating", "navigate",
  "underscore", "robust", "reportedly", "allegedly", "potentially",
  "as tensions mount", "raises questions", "growing concerns", "in the wake of".
- Link our site or self-promote (reads as spam).
- Use emojis.
- Ask "thoughts?" or any filler question.
- Wrap the reply in quotes.

Output FORMAT (exactly this, no preamble):
1. [first reply]
2. [second reply]
3. [third reply, optional]

If only 2 quality replies are possible, give 2.
"""


def draft_replies(cand: Candidate, chart: dict, news: Optional[dict]) -> Optional[str]:
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
        "Draft 2-3 reply options."
    )

    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=400,
            temperature=0.5,
            system=REPLY_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        print(f"  draft failed for {cand.uri}: {e}", file=sys.stderr)
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
    now = datetime.now(timezone.utc)
    print(f"Reply scout — {now:%Y-%m-%d %H:%M UTC}")
    print("Searching Bluesky...")
    try:
        client = _bsky_client()
    except Exception as e:
        print(f"Bluesky login failed: {e}", file=sys.stderr)
        post_discord(
            f"**Reply scout — {now:%Y-%m-%d %H:%M UTC}**\n"
            f"_Could not log in to Bluesky: {e}_"
        )
        return 1
    candidates = collect_candidates(client, now)
    print(f"\n{len(candidates)} candidates after filtering")
    if not candidates:
        post_discord(
            f"**Reply scout — {now:%Y-%m-%d %H:%M UTC}**\n"
            "No qualifying posts in the last 24h "
            f"(min {MIN_LIKES} likes across {len(SEARCH_KEYWORDS)} keywords)."
        )
        return 0

    chart = load_chart_context()
    news = load_news_context()

    sections = []
    for i, c in enumerate(candidates, 1):
        drafts = draft_replies(c, chart, news) or "_(no drafts available)_"
        snippet = c.text.replace("\n", " ")
        if len(snippet) > 240:
            snippet = snippet[:240] + "…"
        sections.append(
            f"### {i}. @{c.author_handle} ({c.likes}♥ {c.reposts}↻ {c.replies}💬)\n"
            f"<{c.web_url}>\n"
            f"> {snippet}\n\n"
            f"**Drafts:**\n{drafts}\n"
        )

    header = (
        f"**Reply scout — {now:%Y-%m-%d %H:%M UTC}**\n"
        f"{len(candidates)} qualifying posts, drafts attached. "
        "Pick one, edit if needed, paste as a reply on Bluesky.\n\n"
    )
    full = header + "\n---\n".join(sections)

    print("\n========== REPLY SCOUT REPORT ==========\n")
    print(full)
    print("\n========== END REPORT ==========\n")

    post_discord(full)
    return 0


if __name__ == "__main__":
    sys.exit(main())
