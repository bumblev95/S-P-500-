"""Publish a complete EOD snapshot, then hand its exact inputs to research.

This gate does not calculate forecasts or rankings. Git commits are the public
transaction boundary; incomplete downloads never advance the remote branch.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from build_forecasts import atomic_json

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PATHS = ("prices/latest_prices.csv", "forecasts/latest.json", "forecasts/archive")
SYMBOL = re.compile(r"[A-Z0-9^][A-Z0-9.^=-]{0,19}")


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("EOD timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def latest_closed_session(at):
    # Same 15-minute settlement buffer as the existing chart collector, including
    # XNYS holidays, early closes and the New York daylight-saving transition.
    import exchange_calendars as xcals

    now = timestamp(at)
    day = now.astimezone(ZoneInfo("America/New_York")).date()
    calendar = xcals.get_calendar("XNYS", start=day - timedelta(days=32), end=day + timedelta(days=7))
    session = calendar.date_to_session(day.isoformat(), direction="previous")
    if now < calendar.session_close(session).to_pydatetime() + timedelta(minutes=15):
        session = calendar.previous_session(session)
    return session.strftime("%Y-%m-%d")


def receipt_symbols(receipt):
    symbols = receipt.get("symbols", [])
    minimum = receipt.get("minimumSymbolCount")
    if (receipt.get("schemaVersion") != 1 or not symbols or "SPY" not in symbols
            or len(symbols) != len(set(symbols))
            or any(not isinstance(s, str) or not SYMBOL.fullmatch(s) for s in symbols)):
        raise ValueError("Invalid or duplicate requested EOD symbols")
    if type(minimum) is not int or minimum <= 0 or len(symbols) < minimum:
        raise ValueError("Requested EOD universe is smaller than the previous public snapshot")
    timestamp(receipt["updatedAt"])
    return set(symbols)


def positive(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError("Missing EOD close") from None
    if not math.isfinite(result) or result <= 0:
        raise ValueError("EOD close must be finite and positive")
    return result


def same_close(left, right):
    # The collector rounds CSV closes to six places and retains full precision
    # in history. No looser model/price tolerance is used for publication.
    return round(positive(left), 6) == round(positive(right), 6)


def public_hashes(root):
    paths = [root / p for p in PUBLIC_PATHS[:2]]
    paths.extend(sorted((root / "forecasts/archive").glob("*.csv")))
    return {p.relative_to(root).as_posix(): sha256(p.read_bytes()) for p in paths}


def validate(root, receipt):
    symbols = receipt_symbols(receipt)
    as_of = latest_closed_session(receipt["updatedAt"])
    with (root / PUBLIC_PATHS[0]).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    by_symbol = {r["symbol"]: r for r in rows}
    if len(by_symbol) != len(rows) or set(by_symbol) != symbols:
        raise ValueError("Price rows must match every requested symbol exactly, without duplicates")
    forecasts = json.loads((root / PUBLIC_PATHS[1]).read_text(encoding="utf-8"))
    stocks = forecasts["stocks"]
    if set(stocks) != symbols:
        raise ValueError("Forecasts must contain every requested price symbol exactly")
    if timestamp(forecasts["generatedAt"]) < timestamp(receipt["updatedAt"]):
        raise ValueError("Forecasts predate this EOD download")
    histories = {}
    for symbol in sorted(symbols):
        row, forecast = by_symbol[symbol], stocks[symbol]
        if row["date"] != as_of or row["updatedAt"] != receipt["updatedAt"]:
            raise ValueError(f"{symbol}: stale, unfinished or retained price row; expected {as_of}")
        positive(row["close"])
        if (forecast.get("symbol") != symbol or forecast.get("asOf") != as_of
                or forecast.get("sourceUpdatedAt") != row["updatedAt"]
                or not same_close(forecast.get("price"), row["close"])):
            raise ValueError(f"{symbol}: forecast and price snapshot disagree")
        path = root / "prices/history" / f"{symbol}.json"
        raw = path.read_bytes()
        record = json.loads(raw)
        history, chart = record.get("prices", []), forecast.get("history", [])
        if (record.get("symbol") != symbol or record.get("updatedAt") != row["updatedAt"]
                or not history or not chart):
            raise ValueError(f"{symbol}: missing or retained downloaded history/chart")
        for endpoint in (history[-1], chart[-1]):
            if endpoint.get("date") != as_of or not same_close(endpoint.get("close"), row["close"]):
                raise ValueError(f"{symbol}: history/chart does not end at the published close")
        histories[path.relative_to(root).as_posix()] = sha256(raw)
    return {"schemaVersion": 1, "asOf": as_of, "symbolCount": len(symbols),
            "receipt": receipt, "publicFiles": public_hashes(root), "historyFiles": histories}


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def staged_paths(root):
    return git(root, "diff", "--cached", "--name-only").splitlines()


def assert_public_unchanged(root, manifest):
    if public_hashes(root) != manifest["publicFiles"]:
        raise ValueError("Public inputs changed while rebasing; do not publish a mixed snapshot")


def publish_public(root, receipt, bundle):
    # Validate before touching the index or creating a commit.
    manifest = validate(root, receipt)
    if staged_paths(root):
        raise ValueError("Publication requires an empty Git index")
    git(root, "add", "--", *PUBLIC_PATHS)
    if staged_paths(root):
        git(root, "commit", "-m", "Update S&P 500 EOD prices and public forecasts")
    git(root, "fetch", "origin", "main")
    git(root, "rebase", "origin/main")
    assert_public_unchanged(root, manifest)
    # A non-fast-forward push fails safely; never force or expose separate files.
    git(root, "push", "origin", "HEAD:main")
    manifest["sourceCommit"] = git(root, "rev-parse", "HEAD")
    bundle.mkdir(parents=True, exist_ok=True)
    atomic_json(bundle / "publication.json", manifest)
    with tarfile.open(bundle / "histories.tar.gz", "w:gz") as archive:
        for path in manifest["historyFiles"]:
            archive.add(root / path, arcname=path)
    print(f"Published {manifest['symbolCount']} EOD closes for {manifest['asOf']}: {manifest['sourceCommit']}")
    return manifest


def read_manifest(bundle):
    manifest = json.loads((bundle / "publication.json").read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1 or not re.fullmatch(r"[0-9a-f]{40}", manifest.get("sourceCommit", "")):
        raise ValueError("Invalid EOD publication checkpoint")
    symbols = receipt_symbols(manifest["receipt"])
    expected = {f"prices/history/{s}.json" for s in symbols}
    if set(manifest["historyFiles"]) != expected:
        raise ValueError("Research checkpoint must contain exactly the requested histories")
    return manifest


def restore_research(root, bundle):
    manifest = read_manifest(bundle)
    git(root, "checkout", "--detach", manifest["sourceCommit"])
    assert_public_unchanged(root, manifest)
    # Verify the full transfer before writing any history. Never use fallback
    # caches or re-download a different price window for learned/adaptive work.
    with tarfile.open(bundle / "histories.tar.gz", "r:gz") as archive:
        members = archive.getmembers()
        if (len(members) != len(manifest["historyFiles"])
                or {m.name for m in members} != set(manifest["historyFiles"])
                or any(not m.isfile() for m in members)):
            raise ValueError("Incomplete or unsafe research history archive")
        for member in members:
            if sha256(archive.extractfile(member).read()) != manifest["historyFiles"][member.name]:
                raise ValueError(f"Research history hash mismatch: {member.name}")
        history_dir = root / "prices/history"
        history_dir.mkdir(parents=True, exist_ok=True)
        for path in history_dir.glob("*.json"):
            path.unlink()
        for member in members:
            (root / member.name).write_bytes(archive.extractfile(member).read())
    actual = validate(root, manifest["receipt"])
    if actual["historyFiles"] != manifest["historyFiles"]:
        raise ValueError("Restored histories do not match their publication checkpoint")
    print(f"Research restored from {manifest['sourceCommit']} ({manifest['asOf']})")
    return manifest


def remote_matches(root, manifest):
    for path, digest in manifest["publicFiles"].items():
        raw = subprocess.run(["git", "-C", str(root), "show", f"origin/main:{path}"],
                             capture_output=True, check=True).stdout
        if sha256(raw) != digest:
            return False
    return True


def publish_research(root, bundle):
    manifest = read_manifest(bundle)
    assert_public_unchanged(root, manifest)
    git(root, "fetch", "origin", "main")
    if not remote_matches(root, manifest):
        print("Public inputs have advanced; retain this run's research artifact without replacing current ml results.")
        return False
    if staged_paths(root):
        raise ValueError("Research publication requires an empty Git index")
    git(root, "add", "--", "ml")
    if not staged_paths(root):
        print("Research outputs unchanged; no commit needed.")
        return False
    git(root, "commit", "-m", f"Update EOD learned forecast research for {manifest['asOf']}")
    git(root, "rebase", "origin/main")
    assert_public_unchanged(root, manifest)
    git(root, "push", "origin", "HEAD:main")
    print(f"Published research for {manifest['asOf']}; public price/forecast files were not staged.")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "publish", "restore", "publish-research"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command in ("validate", "publish"):
        if not args.receipt:
            parser.error("--receipt is required")
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        if args.command == "validate":
            result = validate(root, receipt)
            print(f"Validated {result['symbolCount']} symbols, latest closed session {result['asOf']}")
            return
    if not args.bundle:
        parser.error("--bundle is required")
    if args.command == "publish":
        publish_public(root, receipt, args.bundle)
    elif args.command == "restore":
        restore_research(root, args.bundle)
    else:
        published = publish_research(root, args.bundle)
        import os
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                stream.write(f"published={'true' if published else 'false'}\n")


if __name__ == "__main__":
    main()
