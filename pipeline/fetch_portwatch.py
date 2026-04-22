"""
Pulls daily Strait of Hormuz transit data from IMF PortWatch,
caches it in SQLite, and writes site/data/transits.json for the frontend.

Run:
    python fetch_portwatch.py

Output:
    pipeline/cache.db            (full chokepoint cache, all ports)
    site/data/transits.json      (Hormuz-only, with derived series)
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

PORTWATCH_CSV = (
    "https://hub.arcgis.com/api/v3/datasets/"
    "42132aa4e2fc4d41bdaf9a445f688931_0/downloads/data"
    "?format=csv&spatialRefId=4326"
)

HORMUZ_PORTID = "chokepoint6"

ROOT = Path(__file__).resolve().parent.parent
CACHE_DB = ROOT / "pipeline" / "cache.db"
OUTPUT_JSON = ROOT / "site" / "data" / "transits.json"

VESSEL_TYPES = ["container", "dry_bulk", "general_cargo", "roro", "tanker", "cargo"]


def download_csv() -> pd.DataFrame:
    print(f"Downloading {PORTWATCH_CSV}")
    r = requests.get(PORTWATCH_CSV, timeout=120)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content))
    df.columns = [c.lstrip("﻿") for c in df.columns]  # strip BOM
    print(f"  got {len(df):,} rows across all chokepoints")
    return df


def write_cache(df: pd.DataFrame) -> None:
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(CACHE_DB) as con:
        df.to_sql("chokepoints_raw", con, if_exists="replace", index=False)


def hormuz_only(df: pd.DataFrame) -> pd.DataFrame:
    h = df[df["portid"] == HORMUZ_PORTID].copy()
    h["date"] = pd.to_datetime(h["date"], utc=True).dt.date
    h = h.sort_values("date").reset_index(drop=True)
    print(f"  {len(h):,} Hormuz rows ({h['date'].min()} -> {h['date'].max()})")
    return h


def baseline(h: pd.DataFrame, start: str | None, end: str | None, label: str) -> dict:
    sub = h
    if start:
        sub = sub[sub["date"] >= datetime.strptime(start, "%Y-%m-%d").date()]
    if end:
        sub = sub[sub["date"] <= datetime.strptime(end, "%Y-%m-%d").date()]
    if sub.empty:
        return {"label": label, "avg_total": None, "start": start, "end": end, "n": 0}
    return {
        "label": label,
        "avg_total": round(float(sub["n_total"].mean()), 2),
        "avg_tanker": round(float(sub["n_tanker"].mean()), 2),
        "start": str(sub["date"].min()),
        "end": str(sub["date"].max()),
        "n": int(len(sub)),
    }


def build_payload(h: pd.DataFrame) -> dict:
    h["ma7"] = h["n_total"].rolling(7, min_periods=1).mean().round(2)
    h["ma30"] = h["n_total"].rolling(30, min_periods=1).mean().round(2)
    h["ma7_tanker"] = h["n_tanker"].rolling(7, min_periods=1).mean().round(2)

    last_date = h["date"].iloc[-1]
    last_row = h.iloc[-1]
    last_30d_avg = float(h["n_total"].tail(30).mean())

    baselines = {
        "all_time": baseline(h, None, None, "All-time average (2019–present)"),
        "pre_oct_2023": baseline(h, None, "2023-10-06", "Pre-Oct 2023 (before regional war)"),
        "pre_jun_2025": baseline(h, None, "2025-06-12", "Pre-Jun 2025 (before 12-day war)"),
        "pre_feb_2026": baseline(h, None, "2026-02-27", "Pre-Feb 2026 (before strait closure)"),
        "last_12_months": baseline(
            h,
            (last_date - pd.Timedelta(days=365)).isoformat(),
            None,
            "Last 12 months",
        ),
    }

    def pct_vs(b: dict) -> float | None:
        if not b["avg_total"]:
            return None
        return round((last_30d_avg - b["avg_total"]) / b["avg_total"] * 100, 1)

    series = [
        {
            "date": str(row["date"]),
            "total": int(row["n_total"]),
            "tanker": int(row["n_tanker"]),
            "container": int(row["n_container"]),
            "dry_bulk": int(row["n_dry_bulk"]),
            "cargo": int(row["n_cargo"]),
            "ma7": float(row["ma7"]) if pd.notna(row["ma7"]) else None,
            "ma30": float(row["ma30"]) if pd.notna(row["ma30"]) else None,
        }
        for _, row in h.iterrows()
    ]

    return {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_through": str(last_date),
        "row_count": len(h),
        "current": {
            "latest_date": str(last_date),
            "latest_total": int(last_row["n_total"]),
            "latest_tanker": int(last_row["n_tanker"]),
            "last_7d_avg": round(float(h["n_total"].tail(7).mean()), 2),
            "last_30d_avg": round(last_30d_avg, 2),
            "vs_pre_oct_2023_pct": pct_vs(baselines["pre_oct_2023"]),
            "vs_pre_jun_2025_pct": pct_vs(baselines["pre_jun_2025"]),
            "vs_pre_feb_2026_pct": pct_vs(baselines["pre_feb_2026"]),
            "vs_last_12_months_pct": pct_vs(baselines["last_12_months"]),
        },
        "baselines": baselines,
        "series": series,
    }


def write_payload(payload: dict) -> None:
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    size_kb = OUTPUT_JSON.stat().st_size / 1024
    print(f"  wrote {OUTPUT_JSON} ({size_kb:.1f} KB, {len(payload['series']):,} rows)")


def main() -> int:
    df = download_csv()
    write_cache(df)
    h = hormuz_only(df)
    payload = build_payload(h)
    write_payload(payload)
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
