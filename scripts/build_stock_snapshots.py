"""Build the stock detail page's small, independently cacheable read model."""
import argparse
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re

from build_forecasts import atomic_json


def explore_trend(entry):
    """Sample actual closes from a 21-session change window for the directory."""
    dates = {}
    for row in entry.get("history", ()):
        day, close = row.get("date"), row.get("close")
        if (isinstance(day, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)
                and day <= entry["asOf"] and isinstance(close, (int, float))
                and not isinstance(close, bool) and isfinite(close) and close > 0):
            dates[day] = close
    window = sorted(dates.items())[-22:]
    if len(window) < 22 or window[-1][0] != entry["asOf"]:
        return None
    closes = [value for _, value in window]
    low, high = min(closes), max(closes)
    sample = [closes[round(i * 21 / 8)] for i in range(9)]
    points = [round((value-low)/(high-low)*100) if high > low else 50 for value in sample]
    return {"from": window[0][0], "asOf": window[-1][0],
            "returnPct": round((closes[-1]/closes[0]-1)*100, 2), "points": points}


def publish(source, target):
    raw = source.read_bytes()
    revision = sha256(raw).hexdigest()
    data = json.loads(raw)
    entries = data["stocks"]
    symbols = sorted(entries)
    if data["schemaVersion"] != 1 or not symbols:
        raise ValueError("Missing validated forecast snapshot")
    catalog, risk, trends = [], {}, {}
    for symbol in symbols:
        entry = entries[symbol]
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,19}", symbol) or entry["symbol"] != symbol:
            raise ValueError(f"Invalid symbol: {symbol}")
        catalog.append({"symbol": symbol, "name": entry.get("name", "")})
        trend = explore_trend(entry)
        if trend:
            trends[symbol] = trend
        risk[symbol] = {"price": entry["price"], "asOf": entry["asOf"],
                        "inputs": {"ma200": entry.get("inputs", {}).get("ma200")}}
        if symbol == "SPY":
            risk[symbol]["history"] = entry.get("history", [])[-63:]
    target.mkdir(parents=True, exist_ok=True)
    for symbol in symbols:
        atomic_json(target / f"{symbol}.json", {"revision": revision, "stock": entries[symbol]})
    for existing in target.glob("*.json"):
        if existing.stem not in entries and existing.name not in {"index.json", "explore-trends.json"}:
            existing.unlink()
    atomic_json(target / "index.json", {"schemaVersion": 1, "revision": revision,
                                        "items": catalog, "risk": risk})
    atomic_json(target / "explore-trends.json", {"schemaVersion": 1, "revision": revision, "trends": trends})
    print(f"Stock detail files: {len(catalog)} · source {revision[:12]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root
    publish(root / "forecasts/latest.json", root / "forecasts/by-symbol")
