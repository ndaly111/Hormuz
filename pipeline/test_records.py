"""Tests for records.find_hook and post_bluesky's duplicate-post guard.

Run:  python -m pytest pipeline/test_records.py -q
  or: python pipeline/test_records.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from records import CLOSURE_DATE, MIN_SPAN_DAYS, find_hook  # noqa: E402
from post_bluesky import _texts_from_feed  # noqa: E402


def _series(totals: list[int], start: str = CLOSURE_DATE) -> list[dict]:
    d0 = date.fromisoformat(start)
    rows = []
    for i, t in enumerate(totals):
        window = totals[max(0, i - 6): i + 1]
        rows.append({"date": (d0 + timedelta(days=i)).isoformat(), "total": t,
                     "ma7": sum(window) / len(window)})
    return rows


def _data(totals: list[int], norm: float = 60.0) -> dict:
    s = _series(totals)
    return {"current": {"latest_date": s[-1]["date"], "last_7d_avg": s[-1]["ma7"]},
            "baselines": {"pre_feb_2026": {"avg_total": norm}},
            "series": s}


def test_flat_history_has_no_hook():
    assert find_hook(_data([5] * 60)) is None


def test_quietest_day_in_n_days():
    totals = [5] * 60
    totals[10] = 1          # last time we were this low
    totals.append(1)        # today ties it -> 50 days since
    hook = find_hook(_data(totals))
    assert hook is not None and hook.key == "low_day"
    assert "Quietest day in 50 days" in hook.text and "1 ship transited" in hook.text


def test_low_day_needs_min_span():
    totals = [5] * 60
    totals[-8] = 1
    totals.append(1)        # only 8 days since the last 1-ship day
    assert find_hook(_data(totals)) is None
    assert MIN_SPAN_DAYS > 8


def test_lowest_since_closure_began():
    totals = [5] * 60 + [0]
    hook = find_hook(_data(totals))
    assert hook is not None and hook.key == "low_day"
    assert "since the closure began" in hook.text and "No ships" in hook.text


def test_busiest_day_outranks_7d_average():
    totals = [5] * 60 + [40]
    hook = find_hook(_data(totals))
    assert hook is not None and hook.key == "high_day"
    assert "Busiest day" in hook.text and "40 ships" in hook.text


def test_7d_average_high_fires_without_single_day_record():
    totals = [5] * 60 + [9, 9, 9, 9, 9, 9, 9]   # every day 9: no single-day record after the first
    hook = find_hook(_data(totals))
    assert hook is not None and hook.key == "high_ma7"
    assert "7-day average up to 9.0" in hook.text


def test_milestone_day():
    totals = [5] * 201          # index 200 == day 200
    hook = find_hook(_data(totals))
    assert hook is not None and hook.key == "milestone_200"
    assert hook.text.startswith("200 days.")


def test_pre_closure_rows_are_ignored():
    # A 0-ship day before the closure must not suppress a "since the closure began" low.
    pre = _series([0] * 30, start="2026-01-01")
    d = _data([5] * 60 + [0])
    d["series"] = pre + d["series"]
    hook = find_hook(d)
    assert hook is not None and "since the closure began" in hook.text


def test_too_little_history_is_silent():
    assert find_hook(_data([5] * 10 + [0])) is None


def test_every_hook_fits_the_post_budget():
    cases = [[5] * 60 + [0], [5] * 60 + [40], [5] * 60 + [9] * 7, [5] * 201]
    for totals in cases:
        hook = find_hook(_data(totals))
        assert hook is not None and len(hook.text) <= 120, hook


def test_texts_from_feed_skips_reposts_and_other_authors():
    feed = {"feed": [
        {"post": {"author": {"handle": "hormuz-traffic.bsky.social"}, "record": {"text": "ours"}}},
        {"post": {"author": {"handle": "hormuz-traffic.bsky.social"}, "record": {"text": "theirs, reposted"}},
         "reason": {"$type": "app.bsky.feed.defs#reasonRepost"}},
        {"post": {"author": {"handle": "someone.else"}, "record": {"text": "not ours"}}},
    ]}
    assert _texts_from_feed(feed, "hormuz-traffic.bsky.social") == ["ours"]


if __name__ == "__main__":
    import inspect
    tests = [f for n, f in sorted(globals().items()) if n.startswith("test_") and inspect.isfunction(f)]
    for t in tests:
        t()
        print("ok ", t.__name__)
    print(f"{len(tests)} passed")
