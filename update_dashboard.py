#!/usr/bin/env python3
"""
update_dashboard.py
────────────────────────────────────────────────────────────────────
Runs on the 25th of every month via GitHub Actions.
Fetches live data from the FRED API, patches cycle-navigator.html
in place, and lets the workflow commit + push the result.

All FRED series IDs are mapped to the HTML's data-fred attributes,
so adding a new KPI means adding one line to SERIES_CONFIG below.
────────────────────────────────────────────────────────────────────
"""

import os
import re
import sys
import json
import time
import datetime
import requests
from pathlib import Path

# ── CONFIG ──────────────────────────────────────────────────────────
FRED_API_KEY = os.environ.get("FRED_API_KEY", "68cb1c667bbe364dc0f7e64c8e1283ae")
FRED_BASE    = "https://api.stlouisfed.org/fred/series/observations"
HTML_FILE    = Path(__file__).parent / "cycle-navigator.html"  # adjust if needed

# Fallback: check common filenames
for candidate in ["cycle-navigator.html", "economic-cycle-dashboard.html", "index.html"]:
    if (Path(__file__).parent / candidate).exists():
        HTML_FILE = Path(__file__).parent / candidate
        break

MONTHS_HISTORY = 36   # how many months of data to fetch for sparklines
RETRY_ATTEMPTS = 3
RETRY_DELAY    = 5    # seconds between retries

# ── SERIES CONFIG ────────────────────────────────────────────────────
# spark_id    : matches the SVG id / data-val attribute in the HTML
# series      : FRED series ID
# transform   : converts raw FRED float to display value
# format_val  : how to render the number as a string for the HTML label
# color_rules : list of (threshold_fn, css_var) to auto-update signal colour
#               first rule that matches wins; fallback is last entry

def pct(v):    return f"{v:+.2f}%"
def bps(v):    return f"{round(v)} bps"
def trn(v):    return f"${v/1000:.1f}T"
def idx(v):    return f"{v:.1f}"
def rate(v):   return f"{v:.2f}%"
def times(v):  return f"{v:.1f}×"
def thou(v):   return f"{v:.0f}k"
def plain(v):  return f"{v:.2f}"

GREEN  = "var(--green)"
ORANGE = "var(--orange)"
RED    = "var(--red)"
BLUE   = "var(--blue)"

SERIES_CONFIG = [
    {
        "spark_id": "spark-yc",
        "series":   "T10Y2Y",
        "transform": lambda v: v,
        "format":   pct,
        "color": lambda v: GREEN if v > 0.5 else (RED if v < -0.3 else ORANGE),
    },
    {
        "spark_id": "spark-hy",
        "series":   "BAMLH0A0HYM2",
        "transform": lambda v: v * 100,   # % → bps
        "format":   bps,
        "color": lambda v: RED if v > 500 else (ORANGE if v > 350 else GREEN),
    },
    {
        "spark_id": "spark-m2",
        "series":   "M2SL",
        "transform": lambda v: v,         # billions USD
        "format":   lambda v: f"${v/1000:.1f}T",
        "color": lambda v: GREEN,
    },
    {
        "spark_id": "spark-rfr",
        "series":   "FEDFUNDS",
        "transform": lambda v: v,
        "format":   rate,
        "color": lambda v: RED if v > 3.0 else (ORANGE if v > 1.5 else GREEN),
    },
    {
        "spark_id": "spark-5y5y",
        "series":   "T5YIFR",
        "transform": lambda v: v,
        "format":   rate,
        "color": lambda v: RED if v > 2.8 else (ORANGE if v > 2.2 else GREEN),
    },
    {
        "spark_id": "spark-cpi",
        "series":   "CPIAUCSL",
        "transform": lambda v: v,
        "format":   lambda v: f"{v:.1f}",
        # For CPI we show YoY % change; compute from series in patch_html
        "color": lambda v: GREEN,         # colour handled by YoY logic below
        "yoy": True,                      # flag: display as YoY % change
    },
    {
        "spark_id": "spark-cape",
        "series":   "CAPE",
        "transform": lambda v: v,
        "format":   times,
        "color": lambda v: RED if v > 30 else (ORANGE if v > 22 else GREEN),
    },
    {
        "spark_id": "spark-ppi",
        "series":   "PPIACO",
        "transform": lambda v: v,
        "format":   idx,
        "color": lambda v: GREEN,
        "yoy": True,
    },
    {
        "spark_id": "spark-claims",
        "series":   "ICSA",
        "transform": lambda v: v / 1000,  # raw → thousands
        "format":   thou,
        "color": lambda v: GREEN if v < 250 else (ORANGE if v < 350 else RED),
    },
    {
        "spark_id": "spark-sahm",
        "series":   "SAHMREALTIME",
        "transform": lambda v: v,
        "format":   plain,
        "color": lambda v: RED if v >= 0.5 else (ORANGE if v >= 0.3 else GREEN),
    },
    {
        "spark_id": "spark-jolts",
        "series":   "JTSQUR",
        "transform": lambda v: v,
        "format":   rate,
        "color": lambda v: GREEN if v > 2.5 else (ORANGE if v > 1.8 else RED),
    },
    {
        "spark_id": "spark-dxy",
        "series":   "DTWEXBGS",
        "transform": lambda v: v,
        "format":   idx,
        "color": lambda v: ORANGE if v > 105 else GREEN,
    },
    {
        "spark_id": "spark-erp",
        "series":   "DGS10",
        "transform": lambda v: v,
        "format":   rate,
        # ERP = 1/CAPE - DGS10 — we store DGS10 and compute ERP at patch time
        "color": lambda v: GREEN,
        "is_dgs10": True,
    },
]


# ── FRED FETCH ────────────────────────────────────────────────────────

def fetch_series(series_id: str, limit: int = MONTHS_HISTORY + 2) -> list[dict]:
    """Fetch observations from FRED, return list of {date, value} dicts."""
    params = {
        "series_id":  series_id,
        "api_key":    FRED_API_KEY,
        "file_type":  "json",
        "sort_order": "asc",
        "limit":      limit,
    }
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            r = requests.get(FRED_BASE, params=params, timeout=15)
            r.raise_for_status()
            obs = r.json()["observations"]
            return [o for o in obs if o["value"] != "."]
        except Exception as e:
            print(f"  ⚠ Attempt {attempt}/{RETRY_ATTEMPTS} failed for {series_id}: {e}")
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY)
    return []


def obs_to_floats(obs: list[dict]) -> list[float]:
    return [float(o["value"]) for o in obs]


def yoy_pct(values: list[float], freq_per_year: int = 12) -> list[float]:
    """Convert level series to YoY % change list (same length, NaN for first year)."""
    result = []
    for i, v in enumerate(values):
        if i < freq_per_year:
            result.append(float("nan"))
        else:
            prev = values[i - freq_per_year]
            result.append((v / prev - 1) * 100 if prev != 0 else float("nan"))
    return result


# ── HTML PATCHING ─────────────────────────────────────────────────────

def sparkline_js_array(values: list[float]) -> str:
    """Render a JS array literal from a list of floats, skipping NaN."""
    cleaned = [v for v in values if v == v]  # remove NaN
    rounded = [round(v, 4) for v in cleaned[-MONTHS_HISTORY:]]
    return "[" + ",".join(str(x) for x in rounded) + "]"


def patch_html(html: str, results: dict) -> str:
    """
    Patch the HTML string in place.

    results: dict  spark_id → {
        "values":  list[float],   # the series to use for sparkline
        "latest":  float,         # the single current value
        "display": str,           # formatted display string
        "color":   str,           # CSS color var string
    }
    """
    # 1. Update staticFallback JS object so the browser has fresh data too
    for spark_id, data in results.items():
        arr = sparkline_js_array(data["values"])
        # Replace the array inside staticFallback: 'spark-xx': [...old...]
        pattern = rf"('{re.escape(spark_id)}':\s*)\[[^\]]*\]"
        html = re.sub(pattern, rf"\g<1>{arr}", html)

    # 2. Update spark-current display label  <span ... data-val="spark-xx">VALUE</span>
    for spark_id, data in results.items():
        pattern = rf'(<span[^>]*data-val="{re.escape(spark_id)}"[^>]*>)[^<]*(</span>)'
        html = re.sub(pattern, rf'\g<1>{data["display"]}\g<2>', html)

    # 3. Update colour on spark-current span
    for spark_id, data in results.items():
        # style="color:var(--something)" on the span that has data-val
        pattern = rf'(<span[^>]*data-val="{re.escape(spark_id)}"[^>]*)style="color:[^"]*"'
        replacement = rf'\g<1>style="color:{data["color"]}"'
        html = re.sub(pattern, replacement, html)

    # 4. Stamp the last-updated date
    now = datetime.date.today()
    month_str = now.strftime("%b %Y")
    html = re.sub(
        r'(<span id="last-updated">)[^<]*(</span>)',
        rf'\g<1>{month_str}\g<2>',
        html
    )

    # 5. Update "next: DD Mon YYYY" in the live badge
    next_run = datetime.date(now.year if now.month < 12 else now.year + 1,
                             now.month % 12 + 1, 25)
    next_str = next_run.strftime("%-d %b %Y")
    html = re.sub(
        r'next: \d+ \w+ \d{4}',
        f'next: {next_str}',
        html
    )

    return html


# ── MAIN ──────────────────────────────────────────────────────────────

def main():
    print(f"\n{'═'*60}")
    print(f"  Economic Dashboard Updater — {datetime.date.today()}")
    print(f"{'═'*60}\n")

    if not HTML_FILE.exists():
        print(f"✗ HTML file not found: {HTML_FILE}")
        sys.exit(1)

    print(f"  File: {HTML_FILE}")
    html = HTML_FILE.read_text(encoding="utf-8")

    # Store raw CAPE values for ERP calculation
    cape_latest = None

    results = {}

    for cfg in SERIES_CONFIG:
        spark_id  = cfg["spark_id"]
        series_id = cfg["series"]
        print(f"  Fetching {series_id:<20s}", end="", flush=True)

        obs = fetch_series(series_id)
        if not obs:
            print("✗ FAILED — skipping")
            continue

        raw_vals   = obs_to_floats(obs)
        transforms = [cfg["transform"](v) for v in raw_vals]

        # YoY series (CPI, PPI)
        if cfg.get("yoy"):
            display_vals = yoy_pct(transforms)
            latest_display = next((v for v in reversed(display_vals) if v == v), None)
        else:
            display_vals = transforms
            latest_display = transforms[-1] if transforms else None

        if latest_display is None:
            print("✗ No valid data — skipping")
            continue

        # Store CAPE for ERP calc
        if series_id == "CAPE":
            cape_latest = transforms[-1]

        # ERP: store DGS10 raw but display as ERP = 1/CAPE - DGS10
        if cfg.get("is_dgs10") and cape_latest is not None:
            erp = round((1 / cape_latest) * 100 - latest_display, 2)
            display_str = f"{erp:+.2f}%"
            color = RED if erp < 0.5 else (ORANGE if erp < 1.5 else GREEN)
        else:
            erp = None
            display_str = cfg["format"](latest_display)
            color       = cfg["color"](latest_display)

        results[spark_id] = {
            "values":  display_vals,
            "latest":  latest_display,
            "display": display_str,
            "color":   color,
        }

        print(f"✓  latest={display_str}")

    print(f"\n  Patching HTML...")
    html = patch_html(html, results)
    HTML_FILE.write_text(html, encoding="utf-8")

    updated = len(results)
    skipped = len(SERIES_CONFIG) - updated
    print(f"  ✓ Updated {updated} series, {skipped} skipped")
    print(f"  ✓ Written → {HTML_FILE.name}")
    print(f"\n{'═'*60}\n")


if __name__ == "__main__":
    main()
