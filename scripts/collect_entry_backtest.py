"""Collect one dated Yahoo quote-basis OHLC snapshot for entry-rule research.

No production files, forecasts, or forward-study observations are written.
401/403/429 stop new provider requests; there is no access workaround/retry.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def normalize(payload, symbol, cutoff):
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise ValueError(str(chart["error"]))
    result = chart["result"][0]
    if result["meta"]["symbol"].upper() != symbol.upper():
        raise ValueError("Provider symbol mismatch")
    if result["meta"].get("currency") != "USD":
        raise ValueError("USD prices required")
    tz = ZoneInfo(result["meta"]["exchangeTimezoneName"])
    quotes = result["indicators"]["quote"][0]
    rows, rejected = [], []
    for i, stamp in enumerate(result.get("timestamp", [])):
        local = datetime.fromtimestamp(stamp, tz)
        date = local.date().isoformat()
        if date > cutoff:
            continue
        values = {k: quotes.get(k, [None] * (i + 1))[i]
                  for k in ("open", "high", "low", "close", "volume")}
        valid = all(isinstance(values[k], (int, float)) and math.isfinite(values[k])
                    for k in ("open", "high", "low", "close"))
        if not valid or not (0 < values["low"] <= min(values["open"], values["close"])
                             <= max(values["open"], values["close"]) <= values["high"]):
            rejected.append(date)
            continue
        if not isinstance(values["volume"], (int, float)) or values["volume"] < 0:
            values["volume"] = None
        # 16:00 local is a conservative observation clock on early-close days.
        end = datetime.combine(local.date(), time(16), tzinfo=tz)
        rows.append({"date": date, "t": stamp * 1000, "end": int(end.timestamp() * 1000),
                     "signalPrice": round(values["close"], 6), **values})
    if len({r["date"] for r in rows}) != len(rows):
        raise ValueError("Duplicate trading dates")
    if rows != sorted(rows, key=lambda r: r["date"]):
        raise ValueError("Unordered trading dates")
    if not rows or rows[-1]["date"] != cutoff:
        raise ValueError("Latest requested completed session missing")
    return rows, rejected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", default="2026-10-02")
    parser.add_argument("--output", type=Path, default=ROOT / "research/history/entry-backtest-2026-10-04")
    parser.add_argument("--symbols", help="Optional comma-separated research subset, plus SPY")
    args = parser.parse_args()
    if args.cutoff >= datetime.now(timezone.utc).date().isoformat():
        raise ValueError("Cutoff must be a past completed session")
    args.output.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output / "raw"
    raw_dir.mkdir(exist_ok=True)
    universe_bytes = (ROOT / "research/universe.json").read_bytes()
    universe = json.loads(universe_bytes)
    members = {v.get("yahooSymbol", k.replace(".", "-")): {"symbol": k.replace(".", "-"), **v}
               for k, v in universe["members"].items()}
    # The actual home universe also contains SPY and SOXX; test the same slots.
    forecast_bytes = (ROOT / "forecasts/latest.json").read_bytes()
    forecast = json.loads(forecast_bytes)
    for symbol in forecast["stocks"]:
        normalized = symbol.replace(".", "-")
        members.setdefault(normalized, {"symbol": normalized, "sector": "ETF / index"})
    if args.symbols:
        chosen = set(args.symbols.split(","))
        members = {k: v for k, v in members.items() if k in chosen}
    members.setdefault("SPY", {"symbol": "SPY", "sector": "ETF / index"})
    blocked, stocks, sources = threading.Event(), {}, {}

    def fetch(symbol):
        cache = raw_dir / (symbol + ".json.gz")
        url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol) + "?range=10y&interval=1d"
        try:
            if cache.exists():
                data = gzip.decompress(cache.read_bytes())
                retrieved = datetime.fromtimestamp(cache.stat().st_mtime, timezone.utc).isoformat()
            else:
                if blocked.is_set():
                    return symbol, None, {"error": "provider access/rate stop"}
                req = Request(url, headers={"User-Agent": "PublicStockDashboard/1.0"})
                with urlopen(req, timeout=30) as response:
                    data = response.read()
                retrieved = datetime.now(timezone.utc).isoformat()
                cache.write_bytes(gzip.compress(data, mtime=0))
            rows, rejected = normalize(json.loads(data), symbol, args.cutoff)
            source = {"url": url, "retrievedAt": retrieved, "sha256": hashlib.sha256(data).hexdigest(),
                      "rows": len(rows), "first": rows[0]["date"], "last": rows[-1]["date"],
                      "rejectedDates": rejected}
            return symbol, {"sector": members[symbol]["sector"], "rows": rows}, source
        except HTTPError as exc:
            if exc.code in (401, 403, 429):
                blocked.set()
            return symbol, None, {"url": url, "error": "HTTP " + str(exc.code)}
        except Exception as exc:
            return symbol, None, {"url": url, "error": type(exc).__name__ + ": " + str(exc)}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(fetch, symbol) for symbol in sorted(members)]
        for done, future in enumerate(as_completed(futures), 1):
            symbol, data, source = future.result()
            sources[symbol] = source
            if data:
                stocks[symbol] = data
            if done % 25 == 0 or done == len(futures) or not data:
                print(json.dumps({"completed": done, "total": len(futures), "symbol": symbol,
                                  "success": len(stocks), "error": source.get("error")}), flush=True)
    dataset = {"schemaVersion": 2, "cutoff": args.cutoff, "basis": "Yahoo quote OHLC; no AdjClose mixing",
               "signalPricePrecision": "Python round(close, 6), matching production CSV; history stays full precision",
               "universeRetrievedAt": universe["retrievedAt"],
               "universeSHA256": hashlib.sha256(universe_bytes).hexdigest(),
               "homeUniverseSHA256": hashlib.sha256(forecast_bytes).hexdigest(),
               "symbols": sorted(members),
               "stocks": {k: stocks[k] for k in sorted(stocks)}}
    encoded = json.dumps(dataset, separators=(",", ":"), allow_nan=False).encode()
    compressed = gzip.compress(encoded, mtime=0)
    (args.output / "prices.json.gz").write_bytes(compressed)
    manifest = {"generatedAt": datetime.now(timezone.utc).isoformat(), "cutoff": args.cutoff,
                "expectedStocks": len(members), "collectedStocks": len(stocks),
                "providerStopped": blocked.is_set(), "datasetSHA256": hashlib.sha256(encoded).hexdigest(),
                "compressedSHA256": hashlib.sha256(compressed).hexdigest(), "compressedBytes": len(compressed),
                "sources": {k: sources[k] for k in sorted(sources)}}
    (args.output / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: v for k, v in manifest.items() if k != "sources"}), flush=True)
    if "SPY" not in stocks:
        raise SystemExit("SPY unavailable; backtest cannot run")


if __name__ == "__main__":
    main()
