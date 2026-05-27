from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

CONSTITUENTS_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
CUSTOM_PATH = Path("custom_tickers.csv")
CONFIG_PATH = Path("config/watchlist_config.json")
LEGACY_SHEET_URL_PATH = Path("watchlist_sheet_url.txt")
OUT_PATH = Path("fundamentals/latest_fundamentals.csv")


def to_yahoo_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace(".", "-")


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace("-", ".")


def clean_value(value: Any) -> Any:
    if value is None:
        return ""
    try:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return ""
    except Exception:
        pass
    return value




def unix_to_date(value: Any) -> str:
    try:
        if value in (None, ""):
            return ""
        ts = float(value)
        if ts <= 0:
            return ""
        return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
    except Exception:
        return ""

def first_nonempty(*values: Any) -> Any:
    for v in values:
        if v not in (None, ""):
            return v
    return ""

def read_watchlist_sheet_url() -> str:
    env_url = os.getenv("WATCHLIST_CSV_URL", "").strip()
    if env_url:
        return env_url

    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            url = str(cfg.get("sheetCsvUrl") or "").strip()
            if url and not url.startswith("PASTE_"):
                return url
        except Exception as exc:
            print(f"Warning: could not read {CONFIG_PATH}: {exc}")

    if LEGACY_SHEET_URL_PATH.exists():
        url = LEGACY_SHEET_URL_PATH.read_text(encoding="utf-8").strip()
        if url and not url.startswith("PASTE_"):
            return url
    return ""


def symbol_col(df: pd.DataFrame) -> str | None:
    lower = {str(c).strip().lower(): c for c in df.columns}
    for key in ("symbol", "ticker", "티커"):
        if key in lower:
            return lower[key]
    return None


def read_symbol_frame(path_or_url: str | Path, label: str) -> list[str]:
    try:
        df = pd.read_csv(path_or_url)
        col = symbol_col(df)
        if not col:
            print(f"Warning: {label} has no symbol/ticker column")
            return []
        symbols = [normalize_symbol(s) for s in df[col].dropna().unique() if str(s).strip()]
        print(f"Reading {len(symbols)} custom tickers from {label}...")
        return symbols
    except Exception as exc:
        print(f"Warning: could not read {label}: {exc}")
        return []


def read_symbols() -> list[str]:
    constituents = pd.read_csv(CONSTITUENTS_URL)
    symbols = [normalize_symbol(s) for s in constituents["Symbol"].dropna().unique()]

    if CUSTOM_PATH.exists():
        symbols.extend(read_symbol_frame(CUSTOM_PATH, str(CUSTOM_PATH)))

    sheet_url = read_watchlist_sheet_url()
    if sheet_url:
        symbols.extend(read_symbol_frame(sheet_url, "Google Sheet watchlist CSV"))
    else:
        print("No Google Sheet watchlist CSV URL configured.")

    seen: set[str] = set()
    out: list[str] = []
    for s in symbols:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def get_info(symbol: str) -> dict[str, Any]:
    ysym = to_yahoo_symbol(symbol)
    ticker = yf.Ticker(ysym)
    try:
        info = ticker.get_info()
    except Exception:
        info = getattr(ticker, "info", {}) or {}
    if not isinstance(info, dict):
        return {}
    return info


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    symbols = read_symbols()

    rows: list[dict[str, Any]] = []
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for i, symbol in enumerate(symbols, start=1):
        ysym = to_yahoo_symbol(symbol)
        try:
            info = get_info(symbol)
            row = {
                "symbol": normalize_symbol(symbol),
                "yahooSymbol": ysym,
                "shortName": clean_value(info.get("shortName") or info.get("longName")),
                "sector": clean_value(info.get("sector")),
                "industry": clean_value(info.get("industry")),
                "forwardEps": clean_value(info.get("forwardEps")),
                "trailingEps": clean_value(info.get("trailingEps")),
                "forwardPE": clean_value(info.get("forwardPE")),
                "trailingPE": clean_value(info.get("trailingPE")),
                "pegRatio": clean_value(info.get("pegRatio")),
                "revenueGrowth": clean_value(info.get("revenueGrowth")),
                "earningsGrowth": clean_value(info.get("earningsGrowth")),
                "grossMargins": clean_value(info.get("grossMargins")),
                "operatingMargins": clean_value(info.get("operatingMargins")),
                "profitMargins": clean_value(info.get("profitMargins")),
                "debtToEquity": clean_value(info.get("debtToEquity")),
                "currentRatio": clean_value(info.get("currentRatio")),
                "quickRatio": clean_value(info.get("quickRatio")),
                "totalDebt": clean_value(info.get("totalDebt")),
                "totalCash": clean_value(info.get("totalCash")),
                "beta": clean_value(info.get("beta")),
                "marketCap": clean_value(info.get("marketCap")),
                "fiftyTwoWeekHigh": clean_value(info.get("fiftyTwoWeekHigh")),
                "fiftyTwoWeekLow": clean_value(info.get("fiftyTwoWeekLow")),
                "earningsTimestamp": clean_value(first_nonempty(info.get("earningsTimestamp"), info.get("earningsTimestampStart"), info.get("earningsTimestampEnd"))),
                "nextEarningsDate": unix_to_date(first_nonempty(info.get("earningsTimestamp"), info.get("earningsTimestampStart"), info.get("earningsTimestampEnd"))),
                "source": "Yahoo Finance fundamentals via yfinance/GitHub Actions",
                "updatedAt": updated_at,
            }
            rows.append(row)
            print(f"{i}/{len(symbols)} {symbol}: ok")
        except Exception as exc:
            rows.append({
                "symbol": normalize_symbol(symbol),
                "yahooSymbol": ysym,
                "source": "Yahoo Finance fundamentals via yfinance/GitHub Actions",
                "updatedAt": updated_at,
                "error": str(exc)[:220],
            })
            print(f"{i}/{len(symbols)} {symbol}: failed - {exc}")
        time.sleep(0.25)

    df = pd.DataFrame(rows)
    preferred_cols = [
        "symbol", "yahooSymbol", "shortName", "sector", "industry",
        "forwardEps", "trailingEps", "forwardPE", "trailingPE", "pegRatio",
        "revenueGrowth", "earningsGrowth", "grossMargins", "operatingMargins", "profitMargins",
        "debtToEquity", "currentRatio", "quickRatio", "totalDebt", "totalCash", "beta", "marketCap",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "earningsTimestamp", "nextEarningsDate",
        "source", "updatedAt", "error",
    ]
    for col in preferred_cols:
        if col not in df.columns:
            df[col] = ""
    df = df[preferred_cols]
    df.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH} with {len(df)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
