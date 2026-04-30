"""Find Hormuz news clusters via Google News RSS.

Pulls articles for several queries, clusters by title-token similarity,
and returns the top cluster IF it has ≥3 distinct outlets from a
reputable-source whitelist. The whitelist filter is what stops Iran
state media echoing each other from registering as a "big story."

Pure stdlib + requests. No API keys. No model downloads.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import requests

# Queries against Google News RSS. Each fetches up to ~100 results,
# we dedupe by URL across all queries.
QUERIES = [
    '"Strait of Hormuz"',
    "Hormuz tanker",
    "Hormuz Iran",
    "Iran shipping",
    "Hormuz blockade OR closure",
]

# Outlets that count toward the cluster threshold. Goal: real wire services
# and reputable maritime/business publications. Excludes Iranian state media,
# tabloids, and aggregators that just rehash other outlets.
OUTLET_WHITELIST = {
    "Reuters", "AP", "Associated Press", "AFP",
    "BBC", "BBC News", "Al Jazeera", "Al Jazeera English",
    "Bloomberg", "Financial Times", "FT.com", "Wall Street Journal", "WSJ",
    "The New York Times", "NYT", "The Washington Post", "Washington Post",
    "The Guardian", "CNN", "CNBC", "Politico", "Axios",
    "ABC News", "CBS News", "NBC News", "USA Today", "NPR",
    "Voice of America", "VOA News",
    "Lloyd's List", "gCaptain", "Splash247", "Splash 247", "TradeWinds",
    "Maritime Executive", "The Maritime Executive", "Marine Link",
    "FreightWaves", "Hellenic Shipping News",
    "S&P Global", "S&P Global Commodity Insights",
    "DefenseNews", "Defense News", "Stars and Stripes",
}

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "of", "in", "on", "at",
    "to", "for", "with", "without", "from", "by", "is", "are", "was", "were",
    "be", "been", "as", "that", "this", "these", "those", "it", "its", "over",
    "under", "into", "out", "up", "down", "about", "after", "before", "again",
    "once", "than", "more", "less", "very", "via", "amid", "while", "during",
    "says", "said", "say", "new", "news",
}

LOOKBACK = timedelta(hours=36)
SIMILARITY_THRESHOLD = 0.35
MIN_DISTINCT_WHITELISTED_OUTLETS = 3
USER_AGENT = "Mozilla/5.0 (compatible; HormuzTrackerBot/1.0; +https://hormuz-traffic.com)"


@dataclass
class Article:
    title: str
    url: str
    outlet: str
    published: datetime


def fetch_rss(query: str) -> list[Article]:
    url = (
        f"https://news.google.com/rss/search?q={quote(query)}"
        "&ceid=US:en&hl=en-US&gl=US"
    )
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return []
    channel = root.find("channel")
    if channel is None:
        return []

    out: list[Article] = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_text = item.findtext("pubDate") or ""
        source_el = item.find("source")
        outlet = (source_el.text or "").strip() if source_el is not None else ""
        if not title or not link or not outlet:
            continue
        try:
            published = datetime.strptime(pub_text, "%a, %d %b %Y %H:%M:%S %Z")
            published = published.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        # Google News RSS often appends " - Outlet" to titles. Strip it.
        title = re.sub(rf"\s*-\s*{re.escape(outlet)}\s*$", "", title)
        out.append(Article(title=title, url=link, outlet=outlet, published=published))
    return out


def tokenize(text: str) -> set[str]:
    text = text.lower()
    tokens = re.findall(r"[a-z]{3,}", text)
    return {t for t in tokens if t not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster(articles: list[Article]) -> list[list[Article]]:
    """Union-find clustering over articles whose token-set Jaccard ≥ threshold."""
    n = len(articles)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    tokens = [tokenize(a.title) for a in articles]
    for i in range(n):
        for j in range(i + 1, n):
            if jaccard(tokens[i], tokens[j]) >= SIMILARITY_THRESHOLD:
                union(i, j)

    grouped: dict[int, list[Article]] = defaultdict(list)
    for i, a in enumerate(articles):
        grouped[find(i)].append(a)
    return list(grouped.values())


def find_top_story(now: Optional[datetime] = None) -> Optional[dict]:
    """Return cluster summary for the top corroborated story, or None.

    Returns a dict like:
      {
        "headline": str,             # representative title
        "outlet": str,               # representative outlet
        "url": str,                  # representative URL
        "whitelisted_outlets": [str],
        "all_outlets": [str],
        "article_count": int,
      }
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - LOOKBACK

    seen_urls: set[str] = set()
    fresh: list[Article] = []
    for q in QUERIES:
        try:
            articles = fetch_rss(q)
        except Exception as e:
            print(f"  rss fetch failed for {q!r}: {e}")
            continue
        for a in articles:
            if a.published < cutoff:
                continue
            if a.url in seen_urls:
                continue
            seen_urls.add(a.url)
            fresh.append(a)

    if not fresh:
        return None

    clusters = cluster(fresh)
    candidates: list[tuple[list[Article], set[str]]] = []
    for arts in clusters:
        whitelisted = {a.outlet for a in arts if a.outlet in OUTLET_WHITELIST}
        if len(whitelisted) >= MIN_DISTINCT_WHITELISTED_OUTLETS:
            candidates.append((arts, whitelisted))

    if not candidates:
        return None

    # Best cluster: most whitelisted outlets, tiebreak by most recent article
    candidates.sort(
        key=lambda c: (
            -len(c[1]),
            -max(a.published for a in c[0]).timestamp(),
        )
    )
    arts, whitelisted = candidates[0]

    rep = min(
        (a for a in arts if a.outlet in OUTLET_WHITELIST),
        key=lambda a: len(a.title),
    )

    # Sample up to 8 distinct headlines (whitelisted first, then others) for Claude
    seen_titles: set[str] = set()
    sampled: list[str] = []
    for a in sorted(arts, key=lambda a: a.outlet not in OUTLET_WHITELIST):
        # crude dedupe — collapse near-identical titles by lowercased prefix
        key = a.title.lower()[:60]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        sampled.append(a.title)
        if len(sampled) >= 8:
            break

    # Pull article bodies from up to 5 articles, prioritized by outlet quality.
    # Wire services and majors first — they have the most fact-density.
    bodies = _extract_article_bodies(arts, n=5)

    return {
        "headline": rep.title,
        "outlet": rep.outlet,
        "url": rep.url,
        "whitelisted_outlets": sorted(whitelisted),
        "all_outlets": sorted({a.outlet for a in arts}),
        "article_count": len(arts),
        "cluster_headlines": sampled,
        "article_bodies": bodies,
    }


# Outlet ranking for body extraction: wire services first, then majors,
# then broadcast / digital natives. The order is the priority queue.
EXTRACTION_PRIORITY = [
    "Reuters", "Associated Press", "AP", "AFP",
    "Bloomberg", "Financial Times", "FT.com",
    "The New York Times", "NYT",
    "The Wall Street Journal", "WSJ",
    "The Washington Post", "Washington Post",
    "BBC", "BBC News", "The Guardian",
    "Al Jazeera", "Al Jazeera English",
    "Axios", "Politico", "CNN", "CNBC",
    "NBC News", "CBS News", "ABC News", "NPR",
    "Lloyd's List", "gCaptain", "TradeWinds", "Splash247", "Splash 247",
    "Maritime Executive", "The Maritime Executive",
    "S&P Global", "S&P Global Commodity Insights",
]


def _looks_like_nav_chrome(body: str) -> bool:
    """Detect when trafilatura grabbed page navigation instead of the article.

    Symptoms: very short avg line length (lots of one-word menu items),
    high proportion of single-word lines, or a body dominated by city/show
    names.
    """
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if len(lines) < 5:
        return False  # too short to judge; let it through
    short_lines = sum(1 for ln in lines if len(ln.split()) <= 2)
    avg_words = sum(len(ln.split()) for ln in lines) / len(lines)
    # If most lines are 1-2 words and average is under 4, it's a menu
    return (short_lines / len(lines) > 0.6) and avg_words < 4


def _extract_article_bodies(arts: list[Article], n: int = 5) -> list[dict]:
    """Fetch and clean article text for top-priority articles, one per outlet.

    Returns a list of {outlet, title, body} dicts. Empty list on total failure.
    Each body is truncated to ~1500 chars to keep the prompt budget sane.
    """
    by_outlet: dict[str, Article] = {}
    for a in arts:
        if a.outlet not in by_outlet:
            by_outlet[a.outlet] = a

    ordered: list[Article] = []
    for outlet in EXTRACTION_PRIORITY:
        if outlet in by_outlet:
            ordered.append(by_outlet[outlet])
        if len(ordered) >= n:
            break

    # Lazy imports — keep find_news importable even if libs missing
    try:
        import trafilatura
    except ImportError:
        print("  trafilatura not installed; skipping body extraction")
        return []
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        print("  googlenewsdecoder not installed; skipping body extraction")
        return []

    out: list[dict] = []
    for a in ordered:
        try:
            # Resolve Google News redirect to the actual outlet URL
            decoded = gnewsdecoder(a.url, interval=1)
            if not decoded.get("status"):
                print(f"  decode failed for {a.outlet}: {decoded.get('message')}")
                continue
            real_url = decoded.get("decoded_url")
            if not real_url:
                continue
            html = trafilatura.fetch_url(real_url, no_ssl=True)
            if not html:
                print(f"  fetch failed for {a.outlet}: {real_url}")
                continue
            text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
            if not text:
                print(f"  extract failed for {a.outlet}: no readable content")
                continue
            body = text.strip()[:1500]
            if _looks_like_nav_chrome(body):
                print(f"  rejected {a.outlet}: extracted body is nav chrome")
                continue
            out.append({"outlet": a.outlet, "title": a.title, "body": body})
            print(f"  extracted {len(body)} chars from {a.outlet}")
        except Exception as e:
            print(f"  extraction failed for {a.outlet}: {e}")
            continue
    return out


if __name__ == "__main__":
    import json
    result = find_top_story()
    if result:
        print(json.dumps(result, indent=2))
    else:
        print("No qualifying cluster (need ≥3 whitelisted outlets in last 36h).")
