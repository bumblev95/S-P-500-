from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

CONSTITUENTS_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
OUT_PATH = Path("prices/latest_prices.csv")


def to_yahoo_symbol(symbol: str) -> str:
    """Convert S&P symbols such as BRK.B to Yahoo style BRK-B."""
    return str(symbol).strip().upper().replace(".", "-")


def get_last_row_for_symbol(data: pd.DataFrame, ysym: str) -> pd.Series | None:
    if data is None or data.empty:
        return None

    # Multi-ticker download usually returns MultiIndex columns: (ticker, field)
    if isinstance(data.columns, pd.MultiIndex):
        if ysym not in data.columns.get_level_values(0):
            return None
        one = data[ysym].dropna(how="all")
    else:
        one = data.dropna(how="all")

    if one.empty:
        return None

    for _, row in one.iloc[::-1].iterrows():
        close = row.get("Close")
        adj = row.get("Adj Close", close)
        if pd.notna(close) or pd.notna(adj):
            return row
    return None


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("Reading S&P 500 constituents...")
    constituents = pd.read_csv(CONSTITUENTS_URL)
    if "Symbol" not in constituents.columns:
        raise RuntimeError("Could not find Symbol column in constituents CSV")

    symbols = [str(s).strip().upper() for s in constituents["Symbol"].dropna().unique()]
    yahoo_symbols = [to_yahoo_symbol(s) for s in symbols]
    symbol_map = dict(zip(yahoo_symbols, symbols))

    print(f"Downloading Yahoo EOD prices for {len(yahoo_symbols)} symbols...")
    data = yf.download(
        tickers=" ".join(yahoo_symbols),
        period="10d",
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
        row = get_last_row_for_symbol(data, ysym)
        if row is None:
            print(f"No usable price for {ysym}")
            continue
        close = row.get("Close")
        adj = row.get("Adj Close", close)
        volume = row.get("Volume")
        date = row.name.date().isoformat() if hasattr(row.name, "date") else str(row.name)[:10]
        original_symbol = symbol_map.get(ysym, ysym.replace("-", "."))
        rows.append({
            "symbol": original_symbol,
            "yahooSymbol": ysym,
            "date": date,
            "close": round(float(close), 6) if pd.notna(close) else "",
            "adjClose": round(float(adj), 6) if pd.notna(adj) else "",
            "volume": int(volume) if pd.notna(volume) else "",
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
