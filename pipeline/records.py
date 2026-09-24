"""Record / milestone hooks for the daily Bluesky post.

On days with no news lede the data-only caption is all that goes out, and
when PortWatch hasn't advanced it repeats verbatim (Sept 16, 17 and 20 2026
were byte-identical). This module turns the *data itself* into the story
when it has one: the latest day being the quietest or busiest in a while,
the 7-day average at a multi-week extreme, or a round-number day of the
closure. Records and milestones get reposted; "day 193, 5.3 ships/day" does
not.

Templated, not LLM-written: deterministic, free, no refusal failure mode.
Evaluated for the latest data date only, so each hook fires once, on the
refresh that first shows it. A multi-day PortWatch jump can skip a record
day; accepted.

    python pipeline/records.py      # prints today's hook, if any
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
TRANSITS_JSON = ROOT / "site" / "data" / "transits.json"

# Keep in sync with CLOSURE_DATE in site/today.js
CLOSURE_DATE = "2026-03-04"

# "Lowest in N days" needs N to be worth saying.
MIN_SPAN_DAYS = 30
# No records in the first weeks of the closure, when everything is one.
MIN_HISTORY_DAYS = 30
MILESTONES = (100, 150, 200, 250, 300, 365, 400, 500, 730, 1000)


@dataclass(frozen=True)
class Hook:
    key: str    # stable id for the ledger: low_day / high_day / low_ma7 / high_ma7 / milestone_N
    text: str   # one line, <= 120 chars; goes in the lede slot above the stat line


def _ships(n: int) -> str:
    if n == 0:
        return "No ships"
    return "1 ship" if n == 1 else f"{n:,} ships"


def _fmt(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _days_since_match(rows: list[dict], field: str,
                      matches: Callable[[float, float], bool]) -> int | None:
    """Days back to the most recent earlier row whose `field` `matches`
    today's value (was at least as extreme). None = never during the closure."""
    cur = rows[-1][field]
    today = date.fromisoformat(rows[-1]["date"])
    for row in reversed(rows[:-1]):
        prev = row.get(field)
        if prev is not None and matches(prev, cur):
            return (today - date.fromisoformat(row["date"])).days
    return None


def find_hook(data: dict) -> Hook | None:
    """Return the single strongest hook for the latest data point, or None.

    Precedence: single-day low, single-day high, 7-day-average low, 7-day-
    average high, closure milestone. Single-day extremes are the most
    concrete ("1 ship transited") so they win.
    """
    rows = [r for r in data["series"] if r["date"] >= CLOSURE_DATE]
    if len(rows) <= MIN_HISTORY_DAYS:
        return None
    latest = rows[-1]
    today = date.fromisoformat(latest["date"])
    day_n = (today - date.fromisoformat(CLOSURE_DATE)).days   # == today.js daysBetween
    total = latest["total"]
    when = _fmt(today)

    span = _days_since_match(rows, "total", lambda prev, cur: prev <= cur)
    if span is None:
        return Hook("low_day", f"Quietest day since the closure began: {_ships(total)} "
                               f"transited Hormuz on {when}, the lowest in {day_n} days.")
    if span >= MIN_SPAN_DAYS:
        return Hook("low_day", f"Quietest day in {span} days: {_ships(total)} transited Hormuz on {when}.")

    span = _days_since_match(rows, "total", lambda prev, cur: prev >= cur)
    if span is None:
        return Hook("high_day", f"Busiest day since the closure began: {_ships(total)} "
                                f"transited Hormuz on {when}, the most in {day_n} days.")
    if span >= MIN_SPAN_DAYS:
        return Hook("high_day", f"Busiest day in {span} days: {_ships(total)} transited Hormuz on {when}.")

    ma7 = latest.get("ma7")
    if ma7 is not None:
        span = _days_since_match(rows, "ma7", lambda prev, cur: prev <= cur)
        if span is None:
            return Hook("low_ma7", f"7-day average down to {ma7:.1f} ships/day, "
                                   f"the lowest of the {day_n}-day closure.")
        if span >= MIN_SPAN_DAYS:
            return Hook("low_ma7", f"7-day average down to {ma7:.1f} ships/day — lowest in {span} days.")

        span = _days_since_match(rows, "ma7", lambda prev, cur: prev >= cur)
        if span is None:
            return Hook("high_ma7", f"7-day average up to {ma7:.1f} ships/day, the highest "
                                    f"since the closure began {day_n} days ago.")
        if span >= MIN_SPAN_DAYS:
            return Hook("high_ma7", f"7-day average up to {ma7:.1f} ships/day — highest in {span} days.")

    if day_n in MILESTONES:
        closure_avg = sum(r["total"] for r in rows) / len(rows)
        norm = (data.get("baselines", {}).get("pre_feb_2026", {}).get("avg_total")) or 0.0
        return Hook(f"milestone_{day_n}",
                    f"{day_n} days. Hormuz traffic has averaged {closure_avg:.1f} ships/day over "
                    f"the whole closure, against a pre-closure norm of {norm:.0f}.")
    return None


if __name__ == "__main__":
    hook = find_hook(json.loads(TRANSITS_JSON.read_text(encoding="utf-8")))
    print(f"[{hook.key}] {hook.text}" if hook else "No hook for the latest data point.")
