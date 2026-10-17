"""Freeze past-only HTP/PTH features for momentum-decomposition research."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import time
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "research/joint-indicator/momentum-decomposition-v1"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(symbol: str) -> tuple[list[tuple[str, float]], dict]:
    ticker = symbol.replace(".", "-")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=20y&interval=1d"
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as response:
                raw = response.read()
            payload = json.loads(raw)["chart"]["result"][0]
            if payload["meta"]["symbol"].upper() != ticker.upper():
                raise ValueError("Asset identity mismatch")
            prices = payload["indicators"].get("adjclose", [{}])[0].get(
                "adjclose", payload["indicators"]["quote"][0]["close"]
            )
            today = datetime.now(timezone.utc).date().isoformat()
            series = [
                (datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat(), float(price))
                for timestamp, price in zip(payload["timestamp"], prices)
                if price is not None and math.isfinite(price) and price > 0
                and datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat() < today
            ]
            if not series or len({day for day, _ in series}) != len(series):
                raise ValueError("Empty or duplicate daily price history")
            return series, {
                "symbol": symbol,
                "url": url,
                "retrievedAt": datetime.now(timezone.utc).isoformat(),
                "payloadHash": digest(raw),
                "rows": len(series),
                "firstDate": series[0][0],
                "lastDate": series[-1][0],
                "status": "ok",
            }
        except Exception as exc:
            if attempt == 2:
                return [], {"symbol": symbol, "url": url, "status": "error", "error": str(exc)}
            time.sleep(0.75 * (attempt + 1))


def past(series: list[tuple[str, float]], origin: str) -> list[tuple[str, float]]:
    return series[:bisect_left([day for day, _ in series], origin)]


def decompose(series: list[tuple[str, float]], origin: str) -> dict | None:
    data = past(series, origin)
    if len(data) < 253:
        return None
    # t-252 through t-21 inclusive when the last available close is t-1.
    formation = data[-252:-20]
    if len(formation) != 232:
        return None
    values = np.asarray([price for _, price in formation], dtype=float)
    start = float(values[0])
    end = float(values[-1])
    high = float(values.max())
    last = float(data[-1][1])
    trailing_126 = float(np.log(last / data[-127][1]))
    return {
        "origin": origin,
        "through": data[-1][0],
        "formationStart": formation[0][0],
        "formationEnd": formation[-1][0],
        "htp": float(np.log(high / start)),
        "pth": float(np.log(end / high)),
        "totalMomentum": float(np.log(end / start)),
        "trailing126": trailing_126,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=FOLDER)
    args = parser.parse_args()
    folder = args.folder
    protocol_raw = (folder / "PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_raw)
    environment_raw = gzip.decompress((folder / protocol["source"]["environment"]).read_bytes())
    universe_raw = (folder / protocol["source"]["universe"]).read_bytes()
    if digest(environment_raw) != protocol["source"]["environmentSha256"]:
        raise ValueError("Environment source changed after registration")
    if digest(universe_raw) != protocol["source"]["universeSha256"]:
        raise ValueError("Universe source changed after registration")
    source = json.loads(environment_raw)
    symbols = sorted({
        row["symbol"]
        for horizon in protocol["horizons"]
        for row in source["stocks"][str(horizon)]["outcomes"]
    })
    histories: dict[str, list[tuple[str, float]]] = {}
    metadata = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(fetch, symbol): symbol for symbol in symbols}
        for count, future in enumerate(as_completed(pending), 1):
            symbol = pending[future]
            histories[symbol], metadata[symbol] = future.result()
            if count % 25 == 0 or not histories[symbol]:
                print(count, len(symbols), symbol, metadata[symbol]["status"], flush=True)
    features = {}
    for horizon in protocol["horizons"]:
        for row in source["stocks"][str(horizon)]["outcomes"]:
            key = f"{row['symbol']}|{row['origin']}"
            if key not in features:
                value = decompose(histories.get(row["symbol"], []), row["origin"])
                features[key] = {
                    "symbol": row["symbol"],
                    "origin": row["origin"],
                    "usable": value is not None,
                    **(value or {}),
                }
    snapshot = {
        "version": protocol["version"],
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "sourceMainCommit": protocol["sourceMainCommit"],
        "sourceHash": digest(environment_raw),
        "universeHash": digest(universe_raw),
        "protocolHash": digest(protocol_raw),
        "collectorHash": digest(Path(__file__).read_bytes()),
        "rawDataVintage": "Yahoo revised adjusted daily closes retrieved after registration; not point-in-time data",
        "metadata": {symbol: metadata[symbol] for symbol in sorted(metadata)},
        "features": features,
        "coverage": {
            "symbols": len(symbols),
            "successfulSymbols": sum(bool(histories[symbol]) for symbol in symbols),
            "featureRows": len(features),
            "usableRows": sum(feature["usable"] for feature in features.values()),
        },
    }
    raw = json.dumps(
        snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()
    output = folder / "sources/features.json.gz"
    output.write_bytes(gzip.compress(raw, mtime=0))
    print("Frozen features", snapshot["coverage"], digest(raw), flush=True)


if __name__ == "__main__":
    main()
