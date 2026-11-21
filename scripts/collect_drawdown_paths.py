"""Freeze only the realized daily paths needed by the registered drawdown study."""
import argparse
import gzip
import hashlib
import json
import math
import time
from bisect import bisect_left, bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "research/joint-indicator/drawdown-separation-v1"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fetch(symbol):
    query_symbol = symbol.replace(".", "-")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{query_symbol}?range=20y&interval=1d"
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as response:
                raw = response.read()
            chart = json.loads(raw)["chart"]["result"][0]
            if chart["meta"]["symbol"].upper() != query_symbol.upper():
                raise ValueError("Asset identity mismatch")
            prices = chart["indicators"].get("adjclose", [{}])[0].get(
                "adjclose", chart["indicators"]["quote"][0]["close"]
            )
            data = [
                (datetime.fromtimestamp(ts, timezone.utc).date().isoformat(), float(price))
                for ts, price in zip(chart["timestamp"], prices)
                if price is not None and math.isfinite(price) and price > 0
            ]
            if len(data) != len({day for day, _ in data}):
                raise ValueError("Duplicate daily price date")
            return data, {
                "symbol": symbol,
                "url": url,
                "retrievedAt": datetime.now(timezone.utc).isoformat(),
                "payloadHash": digest(raw),
                "rows": len(data),
                "firstDate": data[0][0],
                "lastDate": data[-1][0],
                "status": "ok",
            }
        except Exception as exc:
            if attempt == 2:
                return [], {"symbol": symbol, "url": url, "status": "error", "error": str(exc)}
            time.sleep(1 + attempt)


def slice_path(series, origin, target):
    days = [day for day, _ in series]
    anchor_index = bisect_left(days, origin) - 1
    end_index = bisect_right(days, target)
    if anchor_index < 0 or end_index <= anchor_index + 1:
        return {"status": "missing", "reason": "no_anchor_or_future_observation"}
    selected = series[anchor_index:end_index]
    anchor = selected[0][1]
    return {
        "status": "ok",
        "anchorDate": selected[0][0],
        "through": selected[-1][0],
        "dates": [day for day, _ in selected],
        "ratios": [round(price / anchor, 10) for _, price in selected],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=FOLDER)
    args = parser.parse_args()
    folder = args.folder
    protocol_bytes = (folder / "PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    source_path = (folder / protocol["source"]).resolve()
    source_raw = gzip.decompress(source_path.read_bytes())
    if digest(source_raw) != protocol["sourceHashes"]["environmentRawSha256"]:
        raise ValueError("Environment source hash mismatch")
    source = json.loads(source_raw)
    rows = []
    for horizon in protocol["horizons"]:
        all_rows = source["stocks"][str(horizon)]["outcomes"]
        dates = sorted({row["origin"] for row in all_rows})
        start = dates[len(dates) // 2]
        rows.extend((horizon, row) for row in all_rows if row["origin"] >= start)
    symbols = sorted({row["symbol"] for _, row in rows})
    histories, metadata = {}, {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(fetch, symbol): symbol for symbol in symbols}
        for index, future in enumerate(as_completed(pending), 1):
            symbol = pending[future]
            histories[symbol], metadata[symbol] = future.result()
            if index % 25 == 0 or not histories[symbol]:
                print(index, len(symbols), symbol, metadata[symbol]["status"], flush=True)
    paths = {}
    for horizon, row in rows:
        key = f"{horizon}|{row['symbol']}|{row['origin']}"
        path = slice_path(histories.get(row["symbol"], []), row["origin"], row["targetDate"])
        path.update(symbol=row["symbol"], origin=row["origin"], targetDate=row["targetDate"], horizon=horizon)
        paths[key] = path
    output = {
        "version": protocol["version"],
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "protocolHash": digest(protocol_bytes),
        "environmentRawHash": digest(source_raw),
        "rawDataVintage": "Revised adjusted daily history, not certified point-in-time data",
        "metadata": {symbol: metadata[symbol] for symbol in sorted(metadata)},
        "paths": {key: paths[key] for key in sorted(paths)},
        "coverage": {
            "totalRows": len(paths),
            "coveredRows": sum(path["status"] == "ok" for path in paths.values()),
            "symbols": len(symbols),
            "successfulSymbols": sum(bool(histories[symbol]) for symbol in symbols),
        },
    }
    raw = json.dumps(output, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    destination = folder / "sources/path-snapshot.json.gz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    compressed = gzip.compress(raw, mtime=0)
    # Keep Git/API blobs small while preserving one byte-identical gzip stream.
    chunk_size = 700_000
    for old in destination.parent.glob("path-snapshot.part-*.gzpart"):
        old.unlink()
    parts = []
    for index, offset in enumerate(range(0, len(compressed), chunk_size)):
        chunk = compressed[offset:offset + chunk_size]
        name = f"path-snapshot.part-{index:03d}.gzpart"
        (destination.parent / name).write_bytes(chunk)
        parts.append({"name": name, "size": len(chunk), "sha256": digest(chunk)})
    manifest = {
        "format": "concatenated byte chunks of one deterministic gzip stream",
        "gzipSize": len(compressed), "gzipSha256": digest(compressed),
        "rawSize": len(raw), "rawSha256": digest(raw), "parts": parts,
    }
    (destination.parent / "path-snapshot.manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    if destination.exists():
        destination.unlink()
    print("Frozen path snapshot", output["coverage"], digest(raw), flush=True)


if __name__ == "__main__":
    main()
