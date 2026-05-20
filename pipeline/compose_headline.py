"""Send a corroborated news cluster to Claude and get a sharp lede back.

The cluster's existing headlines are useful as raw material but they're often
written for SEO ("Trump reportedly not happy with Iran's latest Hormuz
proposal") rather than as a punchy social-post lede. Claude rewrites them
into a single sharp headline that connects to the traffic chart that follows.

Falls back to the cluster's representative headline if ANTHROPIC_API_KEY is
unset or the API call fails. Logged but never raised — the post should still
go out even if Claude is down.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

# Conservative default — fast, cheap, good enough for one-line headlines.
# Bump to claude-sonnet-4-6 if quality is wanting. Cost is trivial either way.
MODEL = os.environ.get("ANTHROPIC_HEADLINE_MODEL", "claude-haiku-4-5-20251001")


SYSTEM_PROMPT = """\
You are writing the lede for a Bluesky post from @hormuz-traffic.bsky.social, \
an account that publishes daily Strait of Hormuz vessel-traffic data with a chart. \
Several major outlets are covering a related news story. Compose ONE sharp \
headline that drives engagement (replies, reposts, quote-posts) and reads like \
a human typed it, not a model.

FIND THE BURIED FACT — most important rule:
You will receive both the cluster's headlines AND article bodies (when available).
Headlines are written for SEO and all sound the same. The article bodies are
where the news lives — specific dollar amounts, vessel names, named officials,
direct quotes, surprising sub-details. SCAN THE BODIES and lead with the most
striking buried fact that other accounts won't have. If one outlet got an
exclusive quote, lead with the quote. If one body has a specific number
(34% approval, 27 days dark, $800K bet), lead with the number. If one body
names a vessel or person other outlets don't, use that. Do not regurgitate
the headlines — the headlines are what every other account will post.

GOLD STANDARD (this is the target voice — drama verbs, two-fact tension,
direct quote as punchline when one is available, buried detail when it slaps):
  Trump approval bottoms at 34% as he tells aides the blockade is "more effective than bombing"
  UAE tanker slips past Iran's Hormuz closure after going dark for 27 days, spotted near India. Traffic still at 9% of norm
  Trump rejects Iran's offer to reopen Strait of Hormuz
  US boards Iran-bound tanker as Hormuz closure hits day 54
  Iran threatens new shipping lane after Trump rejects deal

PROVEN STRUCTURES (build the headline using one of these):
- Two-fact tension: "[Fact A] as [Fact B]" — places contrasting or simultaneous
  facts in implicit conflict. The strongest pattern. Use it when there are two
  things in the news that bite each other.
- Direct quote as punchline: lead with the actor and what they did, end with
  the most quotable line in straight double-quotes. Quote a real, specific phrase.
- Pure declaration: subject + action + object, no padding. Use when there's one
  dominant fact and no good contrast or quote.

DRAMA VERBS (lift the verb out of neutral):
  bottoms, collapses, plummets, doubles down, doubles back, vows, claims,
  warns, dares, signals, rejects, blocks, boards, clears, threatens, escalates,
  signs, returns, stalls.

WRITING STYLE:
- One line, 10-18 words. Under 130 characters.
- Specific subjects, specific objects, specific numbers when newsworthy
  (34%, day 60, 91% below norm).
- No emoji, hashtag, or outlet-name in the headline.
- Quotation marks only around an actual quote inside the headline.
  Never wrap the whole headline in quotes.
- No period at the end.
- Don't paraphrase any single source headline. Synthesize across the cluster.

AVOID AI TELLS (these get the post ignored or mocked):
- NO em dashes (—) or double hyphens. Use a comma, period, or rewrite.
- NO smart/curly quotes. Straight quotes only if you need them.
- NO period at the end of the headline.
- NO Title Case On Every Word. Sentence case, with proper nouns capitalized.
- NO parenthetical asides or colons setting up an explanation.
- BANNED words: amid, ongoing, remains, mounting, escalating, navigate,
  underscore, robust, landscape, spotlight, pivotal, unprecedented, stark,
  signal (as a verb), reportedly, allegedly, potentially, seemingly,
  increasingly, notably, crucially.
- BANNED phrases: "raises questions", "sparks debate", "growing concerns",
  "amid tensions", "as tensions mount", "it remains to be seen",
  "in a move that", "marks a turning point", "high-stakes", "deepens crisis",
  "shows no signs of", "comes as", "in the wake of".
- NO hedging openers: "Reports indicate", "Sources say", "According to",
  "Officials suggest", "It appears that".
- Voice should read like a person typing on Bluesky, not a wire-service blurb
  or an op-ed lede.

WHEN TO ADD THE DATA HOOK:
- Default: just the news, like the gold-standard examples above.
- If the traffic data tells its own story that pairs with the news, fold it in:
  - Traffic improving while talks advance: "Hormuz traffic up 12% as Trump
    deal takes shape"
  - Rhetoric while traffic stays dead: "Trump warns Iran as Hormuz traffic
    stays at 9% of normal"
  - New disruption plus worsening data: "Iran threatens new lane as Hormuz
    falls further below norm"
- The chart appears right below the headline. Don't point at it unless the
  juxtaposition adds something.

NARRATIVE ANGLES (let the data and news guide which fits):
- Stalemate or escalation: accountability framing (no plan, two months in,
  talks stall).
- Improving traffic: vindication framing (first sign of life, ships return).
- Worsening or new disruption: escalation framing.
- Pure rhetoric while traffic is stuck: highlight the gap.

OUTPUT: just the headline text, single line, no preamble, no explanation,
no quotes around it.
"""


@dataclass
class HeadlineRequest:
    cluster_headlines: list[str]
    outlets: list[str]
    days_since_closure: int
    seven_day_avg: float
    thirty_day_avg: float
    pct_vs_norm: float
    pre_closure_norm: float
    # List of {"outlet": str, "title": str, "body": str} dicts. Optional —
    # falls back to headlines-only if the extractor didn't get any bodies.
    article_bodies: list[dict] | None = None


def _is_retryable_error(exc: Exception) -> bool:
    """True for transient API failures worth retrying.

    529 (Overloaded) is what we saw on 2026-05-19 — peak-hour capacity
    pressure that clears within seconds. 5xx, 429, and connection
    errors all benefit from a brief wait.
    """
    status = getattr(exc, "status_code", None)
    if status is not None and (status == 429 or status >= 500):
        return True
    cls_name = type(exc).__name__
    return cls_name in {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
    }


def compose(req: HeadlineRequest) -> Optional[str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        # Lazy import so the rest of the pipeline runs without anthropic installed
        from anthropic import Anthropic
    except ImportError:
        print("[compose_headline] anthropic SDK not installed; skipping")
        return None

    user_msg = _build_user_message(req)

    # The SDK does its own short-burst retry (~1.5s total by default), which
    # is too quick for a real 529 overload event. Disable the SDK's retries
    # and run our own loop with longer backoff so we actually outlast the
    # capacity blip.
    client = Anthropic(api_key=api_key, max_retries=0)
    backoffs = [2, 5, 15, 30]  # 4 attempts, ~52s total worst case

    resp = None
    last_err: Exception | None = None
    for attempt, delay in enumerate(backoffs, start=1):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=80,
                temperature=0.4,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            break
        except Exception as e:
            last_err = e
            if not _is_retryable_error(e) or attempt == len(backoffs):
                print(f"[compose_headline] API call failed (attempt {attempt}/{len(backoffs)}): {e}")
                return None
            print(f"[compose_headline] transient API error (attempt {attempt}/{len(backoffs)}): {e}; retrying in {delay}s")
            time.sleep(delay)

    if resp is None:
        # Shouldn't reach here, but guard the type checker.
        if last_err is not None:
            print(f"[compose_headline] exhausted retries: {last_err}")
        return None

    if not resp.content or resp.content[0].type != "text":
        print("[compose_headline] empty / non-text response")
        return None

    headline = resp.content[0].text.strip()
    # Strip surrounding quotes if Claude added them despite instructions
    headline = headline.strip('"').strip("'").strip("“").strip("”").strip()
    # Single line only
    headline = headline.split("\n")[0].strip()
    if not headline:
        return None
    return headline


def _build_user_message(req: HeadlineRequest) -> str:
    headlines_block = "\n".join(f"- {h}" for h in req.cluster_headlines)
    outlets = ", ".join(req.outlets[:8])
    if len(req.outlets) > 8:
        outlets += f", +{len(req.outlets) - 8} more"

    # Compute trend direction so the model can name it
    delta = req.seven_day_avg - req.thirty_day_avg
    if req.thirty_day_avg > 0:
        trend_pct = delta / req.thirty_day_avg * 100
    else:
        trend_pct = 0.0
    if trend_pct > 5:
        trend = f"improving (7-day avg up {trend_pct:+.1f}% vs 30-day avg)"
    elif trend_pct < -5:
        trend = f"worsening (7-day avg down {trend_pct:+.1f}% vs 30-day avg)"
    else:
        trend = f"flat (7-day avg within {trend_pct:+.1f}% of 30-day avg)"

    # Pre-compute "% of norm" so the model never has to do arithmetic.
    # Phrasings to use verbatim if a data hook is needed.
    if req.pre_closure_norm > 0:
        pct_of_norm = req.seven_day_avg / req.pre_closure_norm * 100
    else:
        pct_of_norm = 0.0

    bodies_block = ""
    if req.article_bodies:
        chunks = []
        for i, art in enumerate(req.article_bodies, 1):
            outlet = art.get("outlet", "?")
            title = art.get("title", "")
            body = art.get("body", "")
            chunks.append(f"--- Article {i}: {outlet} ---\n{title}\n\n{body}\n")
        bodies_block = (
            "Article bodies (scan these for buried facts; do not summarize, "
            "find one striking detail to lead with):\n\n" + "\n".join(chunks) + "\n"
        )

    return (
        f"News cluster covered by: {outlets}\n\n"
        f"Headlines from the cluster:\n{headlines_block}\n\n"
        f"{bodies_block}"
        f"Today's traffic data (chart will follow the headline):\n"
        f"  Day {req.days_since_closure} of Hormuz closure\n"
        f"  7-day avg: {req.seven_day_avg:.1f} ships/day\n"
        f"  Pre-closure norm: {req.pre_closure_norm:.1f} ships/day\n"
        f"  Currently at {pct_of_norm:.0f}% of normal "
        f"({-req.pct_vs_norm:.0f}% below norm)\n"
        f"  Recent trend: {trend}\n\n"
        f"USE THESE EXACT PHRASINGS (do not recompute, do not round differently):\n"
        f"  - \"{pct_of_norm:.0f}% of normal\"\n"
        f"  - \"{-req.pct_vs_norm:.0f}% below norm\"\n"
        f"  - \"day {req.days_since_closure}\"\n\n"
        "Compose the sharpest one-line headline that drives engagement. "
        "Lead with a buried fact from the article bodies if one is available."
    )


if __name__ == "__main__":
    # Manual smoke test
    req = HeadlineRequest(
        cluster_headlines=[
            "Trump reportedly not happy with Iran's latest Hormuz proposal",
            "Trump claims Iran told U.S. it wants Strait of Hormuz open ASAP",
            "Trump Is Dissatisfied With Iran's Plan to Reopen Strait of Hormuz",
        ],
        outlets=["Reuters", "BBC", "NYT", "CNBC", "Axios"],
        days_since_closure=54,
        seven_day_avg=5.3,
        thirty_day_avg=5.8,
        pct_vs_norm=-91.2,
        pre_closure_norm=60.0,
    )
    result = compose(req)
    print(f"Composed: {result!r}" if result else "No headline (API key missing or API failed)")
