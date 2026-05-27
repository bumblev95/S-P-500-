from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

CONSTITUENTS_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
OUT_PATH = Path("fundamentals/latest_fundamentals.csv")


def to_yahoo_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace(".", "-")


def clean_value(value: Any) -> Any:
    if value is None:
        return ""
    try:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return ""
    except Exception:
        pass
    return value


def get_info(symbol: str) -> dict[str, Any]:
    ysym = to_yahoo_symbol(symbol)
    ticker = yf.Ticker(ysym)
    # get_info is preferred over .info because newer yfinance versions route through get_info.
    try:
        info = ticker.get_info()
    except Exception:
        info = getattr(ticker, "info", {}) or {}
    if not isinstance(info, dict):
        return {}
    return info


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    constituents = pd.read_csv(CONSTITUENTS_URL)
    symbols = constituents["Symbol"].astype(str).str.strip().tolist()

    rows: list[dict[str, Any]] = []
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for i, symbol in enumerate(symbols, start=1):
        ysym = to_yahoo_symbol(symbol)
        try:
            info = get_info(symbol)
            row = {
                "symbol": symbol.upper().replace("-", "."),
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
                "source": "Yahoo Finance fundamentals via yfinance/GitHub Actions",
                "updatedAt": updated_at,
            }
            rows.append(row)
            print(f"{i}/{len(symbols)} {symbol}: ok")
        except Exception as exc:
            rows.append({
                "symbol": symbol.upper().replace("-", "."),
                "yahooSymbol": ysym,
                "source": "Yahoo Finance fundamentals via yfinance/GitHub Actions",
                "updatedAt": updated_at,
                "error": str(exc)[:220],
            })
            print(f"{i}/{len(symbols)} {symbol}: failed - {exc}")
        # Be gentle with Yahoo. Fundamentals do not need to be refreshed fast.
        time.sleep(0.25)

    df = pd.DataFrame(rows)
    preferred_cols = [
        "symbol", "yahooSymbol", "shortName", "sector", "industry",
        "forwardEps", "trailingEps", "forwardPE", "trailingPE", "pegRatio",
        "revenueGrowth", "earningsGrowth", "grossMargins", "operatingMargins", "profitMargins",
        "debtToEquity", "currentRatio", "quickRatio", "totalDebt", "totalCash", "beta", "marketCap",
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
