from __future__ import annotations

import json

import pandas as pd
import pytest

import fetch_portwatch
from fetch_portwatch import build_payload, hormuz_only


def make_rows(start: str, end: str, total: int = 100) -> pd.DataFrame:
    rows = []
    for d in pd.date_range(start, end, freq="D"):
        rows.append(
            {
                "date": d.isoformat(),
                "portid": "chokepoint6",
                "n_container": 10,
                "n_dry_bulk": 20,
                "n_general_cargo": 10,
                "n_roro": 10,
                "n_tanker": total - 50,
                "n_cargo": 50,
                "n_total": total,
            }
        )
    return pd.DataFrame(rows)


def test_payload_uses_365_day_baseline_and_matching_7_day_headline() -> None:
    df = make_rows("2025-02-28", "2026-03-06")
    post_closure = df["date"] >= "2026-02-28"
    df.loc[post_closure, ["n_tanker", "n_total"]] = [0, 50]

    payload = build_payload(hormuz_only(df))

    baseline = payload["baselines"]["pre_feb_2026"]
    current = payload["current"]
    assert baseline["start"] == "2025-02-28"
    assert baseline["end"] == "2026-02-27"
    assert baseline["n"] == 365
    assert baseline["avg_total"] == 100.0
    assert current["last_7d_avg"] == 50.0
    assert current["last_7d_vs_pre_closure_pct"] == -50.0
    assert current["last_30d_vs_pre_closure_pct"] != -50.0
    assert payload["methodology"]["metric"] == "AIS-derived transit calls"


def test_validation_rejects_missing_date() -> None:
    df = make_rows("2026-01-01", "2026-01-03").drop(index=1)
    with pytest.raises(ValueError, match="missing dates"):
        hormuz_only(df)


def test_validation_rejects_non_reconciling_total() -> None:
    df = make_rows("2026-01-01", "2026-01-03")
    df.loc[1, "n_total"] = 999
    with pytest.raises(ValueError, match="do not reconcile"):
        hormuz_only(df)


def test_timestamp_only_change_does_not_republish(tmp_path, monkeypatch) -> None:
    output = tmp_path / "transits.json"
    monkeypatch.setattr(fetch_portwatch, "OUTPUT_JSON", output)
    first = {"updated": "2026-09-30T10:00:00+00:00", "series": [{"total": 1}]}
    second = {"updated": "2026-10-01T10:00:00+00:00", "series": [{"total": 1}]}

    assert fetch_portwatch.write_payload(first) is True
    assert fetch_portwatch.write_payload(second) is False
    assert json.loads(output.read_text(encoding="utf-8"))["updated"] == first["updated"]
