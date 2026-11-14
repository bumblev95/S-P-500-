"""Freeze research-only v5/trend blend predictions before future targets mature."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from prospective_blends import (
    COHORT_COUNT, HORIZON, REGISTERED_PROTOCOL_SHA256, build_methods,
    component_return, target_date,
)

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "research/joint-indicator/prospective-blend-v1"
PROTOCOL_PATH = "research/joint-indicator/prospective-blend-v1/PROTOCOL.json"
ISSUED_PATH = "research/issued.json"
TREND_PREFIX = "forecasts/archive/"
OUTPUT_PREFIX = "research/joint-indicator/prospective-blend-v1/issued"
V5_MODEL = "environment-challenger-v5-horizon-specific"
TREND_MODEL = "trend-decay-v1"


def canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def git_bytes(commit: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def target_start_utc(target: str) -> datetime:
    start = datetime.combine(date.fromisoformat(target), time.min, ZoneInfo("America/New_York"))
    return start.astimezone(timezone.utc)


def trend_archives(commit: str, issued: list[dict], registered_at: datetime,
                   minimum_origin: str) -> dict[str, bytes]:
    month_paths = {
        f"{TREND_PREFIX}{row['asOf'][:7]}.csv"
        for row in issued
        if row.get("model") == V5_MODEL and str(row.get("horizon")) == str(HORIZON)
        and row.get("asOf", "") >= minimum_origin
        and parse_time(row["issuedAt"]) >= registered_at
    }
    tracked = set(git("ls-tree", "-r", "--name-only", commit, "--", "forecasts/archive").splitlines())
    return {path: git_bytes(commit, path) for path in sorted(month_paths & tracked)}


def issue_rows(issued: list[dict], trend_files: dict[str, bytes], registered_at: datetime):
    trends: dict[tuple[str, str], list[dict]] = {}
    trend_sources: dict[tuple[str, str], str] = {}
    for path, raw in trend_files.items():
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            if row.get("model") != TREND_MODEL or str(row.get("horizon")) != str(HORIZON):
                continue
            key = (str(row.get("asOf")), str(row.get("symbol")))
            trends.setdefault(key, []).append(row)
            trend_sources[key] = path

    v5: dict[tuple[str, str], list[dict]] = {}
    for row in issued:
        if row.get("model") != V5_MODEL or str(row.get("horizon")) != str(HORIZON):
            continue
        key = (str(row.get("asOf")), str(row.get("symbol")))
        v5.setdefault(key, []).append(row)

    origins = sorted({key[0] for key in set(v5) & set(trends)})
    by_origin = {}
    for origin in origins:
        symbols = sorted(symbol for as_of, symbol in (set(v5) & set(trends)) if as_of == origin)
        # Duplicate rows are an integrity error, not a tie-break opportunity.
        if any(len(v5[(origin, symbol)]) != 1 or len(trends[(origin, symbol)]) != 1
               for symbol in symbols):
            raise ValueError(f"Duplicate v5 or simple-trend issue row on {origin}")
        eligible = []
        for symbol in symbols:
            vr = v5[(origin, symbol)][0]
            tr = trends[(origin, symbol)][0]
            if parse_time(vr["issuedAt"]) < registered_at or parse_time(tr["issuedAt"]) < registered_at:
                continue
            eligible.append((symbol, vr, tr))
        if eligible:
            by_origin[origin] = [(symbol, vr, tr, trend_sources[(origin, symbol)])
                                 for symbol, vr, tr in eligible]
    return by_origin


def freeze_one(*, now: datetime | None = None, output_root: Path = STUDY) -> dict | None:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    protocol_raw = (ROOT / PROTOCOL_PATH).read_bytes()
    if sha256(protocol_raw) != REGISTERED_PROTOCOL_SHA256:
        raise ValueError("Registered protocol bytes changed; start a new preregistered version")
    protocol = json.loads(protocol_raw)
    registered_at = parse_time(protocol["registeredAt"])
    commit = git("rev-parse", "HEAD")
    commit_time = parse_time(git("show", "-s", "--format=%cI", commit))
    if subprocess.run(["git", "merge-base", "--is-ancestor", protocol["registrationMainCommit"], commit],
                      cwd=ROOT, check=False, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode != 0:
        raise ValueError("Current issue source is not descended from the registered main commit")
    issued_raw = git_bytes(commit, ISSUED_PATH)
    issued = json.loads(issued_raw)
    minimum_origin = protocol["scope"]["minimumOriginDate"]
    trend_files = trend_archives(commit, issued, registered_at, minimum_origin)
    input_rows = issue_rows(issued, trend_files, registered_at)

    output_dir = output_root / "issued"
    existing = sorted(output_dir.glob("*.json")) if output_dir.exists() else []
    if len(existing) >= COHORT_COUNT:
        return None
    previous_target = None
    if existing:
        previous = json.loads(existing[-1].read_text())
        previous_target = previous["targetDate"]

    minimum_origin = max(previous_target or protocol["scope"]["minimumOriginDate"],
                        protocol["scope"]["minimumOriginDate"])
    for origin in sorted(input_rows):
        if origin < minimum_origin:
            continue
        target = target_date(origin)
        # Never reconstruct an issue after its target session has started. The
        # clock check reads no target price or outcome data, so late activation
        # cannot select on score.
        target_start = target_start_utc(target)
        if target_start <= now or target_start <= registered_at:
            continue
        if commit_time >= target_start:
            continue
        symbols = [item[0] for item in input_rows[origin]]
        if not symbols:
            continue
        trend_paths = sorted({item[3] for item in input_rows[origin]})
        rows = []
        for symbol, v5, trend, trend_path in input_rows[origin]:
            common_anchor = float(v5["anchor"])
            v5_return = component_return(float(v5["horizonModel"]), float(v5["anchor"]))
            trend_return = component_return(float(trend["base"]), float(trend["anchor"]))
            methods = build_methods(v5_return, trend_return, common_anchor)
            rows.append({
                "symbol": symbol,
                "anchor": common_anchor,
                "v5IssuedAt": v5["issuedAt"],
                "simpleTrendIssuedAt": trend["issuedAt"],
                "sourceRows": {
                    "v5Sha256": sha256(canonical(v5)),
                    "simpleTrendSha256": sha256(canonical(trend)),
                    "simpleTrendPath": trend_path,
                },
                "componentReturns": {"v5": v5_return, "simpleTrend": trend_return},
                "methods": methods,
            })
        target_sessions = []
        # Include the deterministic session list so the origin/target mapping
        # can be independently replayed without any price or outcome data.
        from prospective_blends import sessions_after
        target_sessions = sessions_after(origin)
        document = {
            "version": protocol["version"],
            "protocolSha256": sha256(protocol_raw),
            "origin": origin,
            "targetDate": target,
            "horizonSessions": HORIZON,
            "targetSessions": target_sessions,
            "capturedAt": now.isoformat().replace("+00:00", "Z"),
            "inputCommit": commit,
            "inputCommitAt": commit_time.isoformat().replace("+00:00", "Z"),
            "inputs": {
                "issued": {"path": ISSUED_PATH, "sha256": sha256(issued_raw)},
                "simpleTrend": [{"path": path, "sha256": sha256(trend_files[path])}
                                for path in trend_paths],
            },
            "cohort": {
                "selection": "Outcome-independent intersection of v5 horizonModel and trend-decay-v1 21-session issue rows, with both component issuedAt timestamps at or after preregistration.",
                "n": len(rows),
                "symbols": symbols,
            },
            "rows": rows,
            "containsTargetData": False,
            "productionForecastChanged": False,
            "serviceRankingsChanged": False,
        }
        output_path = output_dir / f"{origin}.json"
        if output_path.exists():
            raise ValueError(f"Refusing to rewrite an existing frozen issue file: {output_path.name}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(canonical(document))
        return {"path": str(output_path.relative_to(ROOT)), "origin": origin,
                "targetDate": target, "n": len(rows), "inputCommit": commit}
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", help="UTC timestamp for deterministic replay/tests")
    args = parser.parse_args(argv)
    now = parse_time(args.now) if args.now else None
    result = freeze_one(now=now)
    print(json.dumps(result or {"frozen": False, "reason": "no_new_future_common_issue"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
