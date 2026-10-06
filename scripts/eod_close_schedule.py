"""Start at the exchange close and collect the first complete settled snapshot."""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from eod_publication import ROOT, latest_closed_session, same_close, validate


def already_published(root, as_of):
    """Skip scheduled backups only when all existing public rows agree."""
    try:
        with (root / "prices/latest_prices.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        stocks = json.loads((root / "forecasts/latest.json").read_text())["stocks"]
        symbols = {row["symbol"] for row in rows}
        return (bool(rows) and "SPY" in symbols and len(symbols) == len(rows)
                and symbols == set(stocks) and all(
                    row["date"] == as_of and stocks[row["symbol"]]["asOf"] == as_of
                    and row["updatedAt"] == stocks[row["symbol"]]["sourceUpdatedAt"]
                    and same_close(row["close"], stocks[row["symbol"]]["price"])
                    for row in rows))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def collection_plan(root, event, now):
    import exchange_calendars as xcals

    day = now.astimezone(ZoneInfo("America/New_York")).date()
    calendar = xcals.get_calendar("XNYS", start=day - timedelta(days=32), end=day + timedelta(days=7))
    close = calendar.session_close(day.isoformat()).to_pydatetime() if calendar.is_session(day.isoformat()) else None
    if event == "schedule" and (close is None or now < close):
        print("No exchange close to collect at this scheduled time.", flush=True)
        return None
    # Keep the same 15-minute completion buffer as collector and publication.
    # Starting the job at the close lets setup finish while the provider settles.
    ready = close + timedelta(minutes=15) if close is not None and now >= close else now
    as_of = day.isoformat() if close is not None and now >= close else latest_closed_session(now.isoformat())
    if event == "schedule" and already_published(root, as_of):
        print(f"Complete {as_of} snapshot already published; skip the backup run.", flush=True)
        return None
    return as_of, max(now, ready)


def public_snapshot(root):
    paths = [root / "prices/latest_prices.csv", root / "forecasts/latest.json"]
    paths.extend((root / "forecasts/archive").glob("*.csv"))
    return {path: path.read_bytes() for path in paths if path.exists()}


def restore_public(root, original):
    # A failed attempt must not become an immutable first-issued archive record.
    generated = [root / "prices/latest_prices.csv", root / "forecasts/latest.json"]
    generated.extend((root / "forecasts/archive").glob("*.csv"))
    for path in generated:
        if path not in original:
            path.unlink(missing_ok=True)
    for path, raw in original.items():
        path.write_bytes(raw)


def run_command(command, root):
    stopped = False
    with subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True) as process:
        for line in process.stdout:
            print(line, end="", flush=True)
            stopped |= "Provider requested a stop;" in line
        return process.wait(), stopped


def output(name, value):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write(f"{name}={value}\n")


def collect(root, receipt, public_only, event, *, attempts=4, interval=300,
            clock=lambda: datetime.now(timezone.utc), sleeper=time.sleep):
    output("ready", "false")
    plan = collection_plan(root, event, clock())
    if plan is None:
        return 0
    as_of, ready = plan
    print(f"Exchange session {as_of}; earliest settled collection {ready.isoformat()}", flush=True)
    while (remaining := (ready - clock()).total_seconds()) > 0:
        sleeper(min(30, remaining))
    original = public_snapshot(root)
    command = [sys.executable, "scripts/update_eod_prices.py", "--receipt", str(receipt)]
    if public_only:
        command.append("--public-prices-only")
    for attempt in range(1, attempts + 1):
        print(f"Complete EOD collection attempt {attempt}/{attempts}", flush=True)
        stopped = False
        try:
            code, stopped = run_command(command, root)
            if code != 0 or stopped:
                raise ValueError("Price provider did not complete this download")
            code, _ = run_command([sys.executable, "scripts/build_forecasts.py"], root)
            if code != 0:
                raise ValueError("Public forecast build failed")
            manifest = validate(root, json.loads(receipt.read_text()))
            if manifest["asOf"] != as_of:
                raise ValueError(f"Expected closing session {as_of}, got {manifest['asOf']}")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            restore_public(root, original)
            print(f"EOD not ready: {exc}", flush=True)
            if stopped:
                print("Provider requested a stop; do not retry or change hosts.", flush=True)
                return 1
            if attempt == attempts:
                return 1
            sleeper(interval)
        else:
            output("ready", "true")
            print(f"All {manifest['symbolCount']} closes for {as_of} are ready for atomic publication.", flush=True)
            return 0
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--public-prices-only", action="store_true")
    args = parser.parse_args(argv)
    return collect(ROOT, args.receipt, args.public_prices_only,
                   os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch"))


if __name__ == "__main__":
    sys.exit(main())
