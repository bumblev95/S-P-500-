"""Build the stock detail page's small, independently cacheable read model."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

from build_forecasts import atomic_json


def publish(source, target):
    raw = source.read_bytes()
    revision = sha256(raw).hexdigest()
    data = json.loads(raw)
    entries = data["stocks"]
    symbols = sorted(entries)
    if data["schemaVersion"] != 1 or not symbols:
        raise ValueError("Missing validated forecast snapshot")
    catalog, risk = [], {}
    for symbol in symbols:
        entry = entries[symbol]
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,19}", symbol) or entry["symbol"] != symbol:
            raise ValueError(f"Invalid symbol: {symbol}")
        catalog.append({"symbol": symbol, "name": entry.get("name", "")})
        risk[symbol] = {"price": entry["price"], "asOf": entry["asOf"],
                        "inputs": {"ma200": entry.get("inputs", {}).get("ma200")}}
        if symbol == "SPY":
            risk[symbol]["history"] = entry.get("history", [])[-63:]
    target.mkdir(parents=True, exist_ok=True)
    for symbol in symbols:
        atomic_json(target / f"{symbol}.json", {"revision": revision, "stock": entries[symbol]})
    for existing in target.glob("*.json"):
        if existing.stem not in entries and existing.name != "index.json":
            existing.unlink()
    atomic_json(target / "index.json", {"schemaVersion": 1, "revision": revision,
                                        "items": catalog, "risk": risk})
    print(f"Stock detail files: {len(catalog)} · source {revision[:12]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root
    publish(root / "forecasts/latest.json", root / "forecasts/by-symbol")
