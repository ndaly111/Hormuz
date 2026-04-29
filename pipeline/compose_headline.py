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
from dataclasses import dataclass
from typing import Optional

# Conservative default — fast, cheap, good enough for one-line headlines.
# Bump to claude-sonnet-4-6 if quality is wanting. Cost is trivial either way.
MODEL = os.environ.get("ANTHROPIC_HEADLINE_MODEL", "claude-haiku-4-5-20251001")


SYSTEM_PROMPT = """\
You are writing the lede for a Bluesky post from @hormuz-traffic.bsky.social — \
an account that publishes daily Strait of Hormuz vessel-traffic data with a chart. \
Several major outlets are covering a related news story. Compose ONE sharp \
headline that pairs the news with the traffic data so readers stop scrolling and \
react. Replies, reposts, quote-posts are the win condition.

NARRATIVE ANGLES (pick whichever the data + news support):
- If the news shows stalemate, no progress, or escalation: accountability framing.
  ("Trump still has no plan to reopen Hormuz" / "Two months in, no movement"
  / "Talks stall as traffic stays flatlined")
- If traffic is improving even slightly: lean into the positive turn.
  ("First sign of life: Hormuz traffic up 12% as Trump deal takes shape"
  / "Ships return to Hormuz as US negotiations advance")
- If a new disruption hit: lean into the worsening trend.
  ("Iran threatens new lane as Hormuz traffic falls further below norm")
- If the news is just rhetoric and traffic is unchanged: highlight the gap.
  ("Trump warns Iran 'better get smart' — Hormuz still 91% below normal")

WRITING STYLE:
- One line, ≤100 characters.
- Active voice. Specific. A little edge. Some excitement.
- Don't paraphrase any single headline — synthesize across the cluster.
- Avoid wire-service hedging ("reportedly", "amid", "is said to").
- Pair the news beat with the data beat in the same sentence — that juxtaposition
  is the whole point.
- No hashtags. No emojis. No quotation marks around the headline. No outlet names.

OUTPUT: just the headline text, single line, no preamble or explanation.
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

    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=80,
            temperature=0.4,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        print(f"[compose_headline] API call failed: {e}")
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

    return (
        f"News cluster covered by: {outlets}\n\n"
        f"Headlines from the cluster:\n{headlines_block}\n\n"
        f"Today's traffic data (chart will follow the headline):\n"
        f"  Day {req.days_since_closure} of Hormuz closure\n"
        f"  7-day avg: {req.seven_day_avg:.1f} ships/day\n"
        f"  30-day avg: {req.thirty_day_avg:.1f} ships/day\n"
        f"  Pre-closure norm: {req.pre_closure_norm:.1f} ships/day\n"
        f"  vs pre-closure norm: {req.pct_vs_norm:+.1f}%\n"
        f"  Recent trend: {trend}\n\n"
        "Compose the sharpest one-line headline that drives engagement."
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
