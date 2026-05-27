from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import yfinance as yf

CONSTITUENTS_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
CUSTOM_PATH = Path("custom_tickers.csv")
CONFIG_PATH = Path("config/watchlist_config.json")
LEGACY_SHEET_URL_PATH = Path("watchlist_sheet_url.txt")
OUT_PATH = Path("prices/latest_prices.csv")


def to_yahoo_symbol(symbol: str) -> str:
    """Convert symbols such as BRK.B to Yahoo style BRK-B."""
    return str(symbol).strip().upper().replace(".", "-")


def to_display_symbol(yahoo_symbol: str) -> str:
    return str(yahoo_symbol).strip().upper().replace("-", ".")


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace("-", ".")


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
    print("Reading S&P 500 constituents...")
    constituents = pd.read_csv(CONSTITUENTS_URL)
    if "Symbol" not in constituents.columns:
        raise RuntimeError("Could not find Symbol column in constituents CSV")

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


def get_symbol_frame(data: pd.DataFrame, ysym: str) -> pd.DataFrame | None:
    if data is None or data.empty:
        return None
    if isinstance(data.columns, pd.MultiIndex):
        if ysym not in data.columns.get_level_values(0):
            return None
        one = data[ysym].dropna(how="all")
    else:
        one = data.dropna(how="all")
    if one.empty:
        return None
    return one


def calc_return(series: pd.Series, lookback: int) -> float | str:
    s = series.dropna()
    if len(s) <= lookback:
        return ""
    last = float(s.iloc[-1])
    prev = float(s.iloc[-1 - lookback])
    if prev <= 0:
        return ""
    return round(last / prev - 1.0, 6)


def calc_ma(series: pd.Series, window: int) -> float | str:
    s = series.dropna()
    if len(s) < window:
        return ""
    return round(float(s.tail(window).mean()), 6)


def calc_annualized_vol(series: pd.Series, lookback: int = 84) -> float | str:
    s = series.dropna().tail(lookback + 1)
    if len(s) < 25:
        return ""
    rets = s.pct_change().dropna()
    if rets.empty:
        return ""
    return round(float(rets.std() * (252 ** 0.5)), 6)


def calc_max_drawdown(series: pd.Series, lookback: int = 84) -> float | str:
    s = series.dropna().tail(lookback)
    if len(s) < 10:
        return ""
    running_max = s.cummax()
    dd = s / running_max - 1.0
    return round(float(dd.min()), 6)


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    symbols = read_symbols()
    yahoo_symbols = [to_yahoo_symbol(s) for s in symbols]
    symbol_map = dict(zip(yahoo_symbols, symbols))

    print(f"Downloading Yahoo EOD prices/history for {len(yahoo_symbols)} symbols...")
    data = yf.download(
        tickers=" ".join(yahoo_symbols),
        period="13mo",
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        actions=False,
        threads=True,
        progress=False,
    )

    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for ysym in yahoo_symbols:
        one = get_symbol_frame(data, ysym)
        if one is None or one.empty:
            print(f"No usable price for {ysym}")
            continue

        close_series = one.get("Close")
        adj_series = one.get("Adj Close") if "Adj Close" in one.columns else close_series
        if close_series is None:
            print(f"No Close column for {ysym}")
            continue
        valid = close_series.dropna()
        if valid.empty:
            print(f"No valid close for {ysym}")
            continue

        last_date = valid.index[-1]
        close = float(valid.iloc[-1])
        adj_close = ""
        try:
            adj_valid = adj_series.dropna()
            if not adj_valid.empty:
                adj_close = round(float(adj_valid.iloc[-1]), 6)
        except Exception:
            pass

        volume = ""
        try:
            vol_valid = one.get("Volume").dropna()
            if not vol_valid.empty:
                volume = int(vol_valid.iloc[-1])
        except Exception:
            pass

        high52 = ""
        low52 = ""
        range52 = ""
        distance52High = ""
        distance52Low = ""
        try:
            recent = valid.tail(252)
            if not recent.empty:
                high52_val = float(recent.max())
                low52_val = float(recent.min())
                high52 = round(high52_val, 6)
                low52 = round(low52_val, 6)
                if high52_val > low52_val:
                    range52 = round((close - low52_val) / (high52_val - low52_val), 6)
                if high52_val > 0:
                    distance52High = round(close / high52_val - 1.0, 6)
                if low52_val > 0:
                    distance52Low = round(close / low52_val - 1.0, 6)
        except Exception:
            pass

        avgVolume3m = ""
        try:
            vol_series = one.get("Volume").dropna().tail(63)
            if not vol_series.empty:
                avgVolume3m = int(vol_series.mean())
        except Exception:
            pass

        original_symbol = symbol_map.get(ysym, to_display_symbol(ysym))
        rows.append({
            "symbol": original_symbol,
            "yahooSymbol": ysym,
            "date": last_date.date().isoformat() if hasattr(last_date, "date") else str(last_date)[:10],
            "close": round(close, 6),
            "adjClose": adj_close,
            "volume": volume,
            "avgVolume3m": avgVolume3m,
            "ma20": calc_ma(valid, 20),
            "ma50": calc_ma(valid, 50),
            "ma200": calc_ma(valid, 200),
            "volatility4m": calc_annualized_vol(valid, 84),
            "maxDrawdown4m": calc_max_drawdown(valid, 84),
            "high52": high52,
            "low52": low52,
            "range52": range52,
            "distance52High": distance52High,
            "distance52Low": distance52Low,
            "return1m": calc_return(valid, 21),
            "return3m": calc_return(valid, 63),
            "return4m": calc_return(valid, 84),
            "return6m": calc_return(valid, 126),
            "source": "Yahoo EOD via GitHub Actions/yfinance",
            "updatedAt": updated_at,
        })

    if not rows:
        raise RuntimeError("No prices were downloaded. Yahoo/yfinance may be temporarily unavailable.")

    out = pd.DataFrame(rows).sort_values("symbol")
    out.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(out)} prices to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
