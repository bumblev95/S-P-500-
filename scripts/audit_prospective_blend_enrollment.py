"""Audit whether the preregistered prospective blend can enroll a cohort.

This reads only issued forecast archives.  It deliberately does not open target
price archives or compute performance metrics.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from prospective_blends import REGISTERED_PROTOCOL_SHA256


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "research/joint-indicator/prospective-blend-v1/PROTOCOL.json"
ISSUED_PATH = "research/issued.json"
ARCHIVE_PREFIX = "forecasts/archive/"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def git_bytes(commit: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp has no UTC offset: {value}")
    return parsed.astimezone(timezone.utc)


def eligible(row: dict, registered_at: datetime, minimum_origin: str) -> bool:
    return (str(row.get("asOf", "")) >= minimum_origin
            and bool(row.get("issuedAt"))
            and parse_timestamp(str(row["issuedAt"])) >= registered_at)


def required_summary(rows: list[dict], *, model: str, horizon: int,
                     registered_at: datetime, minimum_origin: str) -> dict:
    matching = [row for row in rows
                if row.get("model") == model and str(row.get("horizon")) == str(horizon)]
    post = [row for row in matching if eligible(row, registered_at, minimum_origin)]
    latest = max(matching, key=lambda row: (str(row.get("asOf", "")),
                                             str(row.get("issuedAt", ""))), default=None)
    return {
        "model": model,
        "horizon": horizon,
        "totalRows": len(matching),
        "latestOrigin": latest.get("asOf") if latest else None,
        "latestIssuedAt": latest.get("issuedAt") if latest else None,
        "postRegistrationRows": len(post),
        "postRegistrationOrigins": sorted({str(row["asOf"]) for row in post}),
        "postRegistrationSymbols": len({str(row["symbol"]) for row in post}),
    }


def available_groups(rows: list[dict], *, registered_at: datetime,
                     minimum_origin: str) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        if eligible(row, registered_at, minimum_origin):
            groups[(str(row.get("model")), str(row.get("horizon")))].append(row)
    result = []
    for (model, horizon), group in sorted(groups.items()):
        result.append({
            "model": model,
            "horizon": horizon,
            "rows": len(group),
            "origins": sorted({str(row["asOf"]) for row in group}),
            "latestOrigin": max(str(row["asOf"]) for row in group),
            "latestIssuedAt": max(str(row["issuedAt"]) for row in group),
        })
    return result


def audit(source_commit: str, observed_at: str) -> dict:
    source_commit = git("rev-parse", source_commit)
    protocol_raw = PROTOCOL_PATH.read_bytes()
    if digest(protocol_raw) != REGISTERED_PROTOCOL_SHA256:
        raise ValueError("Registered protocol bytes changed; start a new version")
    protocol = json.loads(protocol_raw)
    registered_at = parse_timestamp(protocol["registeredAt"])
    observation_time = parse_timestamp(observed_at)
    if observation_time < registered_at:
        raise ValueError("Observation time predates registration")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", protocol["registrationMainCommit"], source_commit],
        cwd=ROOT, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode != 0:
        raise ValueError("Source commit is not descended from registrationMainCommit")

    issued_raw = git_bytes(source_commit, ISSUED_PATH)
    issued_rows = json.loads(issued_raw)
    archive_paths = [
        path for path in git("ls-tree", "-r", "--name-only", source_commit, "--", ARCHIVE_PREFIX).splitlines()
        if path.startswith(ARCHIVE_PREFIX) and path.endswith(".csv")
    ]
    trend_rows: list[dict] = []
    archive_hashes = []
    for path in sorted(archive_paths):
        raw = git_bytes(source_commit, path)
        archive_hashes.append({"path": path, "sha256": digest(raw)})
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            row["sourcePath"] = path
            trend_rows.append(row)

    minimum_origin = protocol["scope"]["minimumOriginDate"]
    v5_spec = protocol["inputs"]["v5"]
    trend_spec = protocol["inputs"]["simpleTrend"]
    horizon = int(protocol["scope"]["horizonSessions"])
    v5 = required_summary(
        issued_rows, model=v5_spec["model"], horizon=horizon,
        registered_at=registered_at, minimum_origin=minimum_origin,
    )
    trend = required_summary(
        trend_rows, model=trend_spec["model"], horizon=horizon,
        registered_at=registered_at, minimum_origin=minimum_origin,
    )

    v5_keys = {
        (str(row["asOf"]), str(row["symbol"])) for row in issued_rows
        if row.get("model") == v5_spec["model"]
        and str(row.get("horizon")) == str(horizon)
        and eligible(row, registered_at, minimum_origin)
    }
    trend_keys = {
        (str(row["asOf"]), str(row["symbol"])) for row in trend_rows
        if row.get("model") == trend_spec["model"]
        and str(row.get("horizon")) == str(horizon)
        and eligible(row, registered_at, minimum_origin)
    }
    common: dict[str, int] = defaultdict(int)
    for origin, _symbol in v5_keys & trend_keys:
        common[origin] += 1

    commit_at = git("show", "-s", "--format=%cI", source_commit)
    code_raw = Path(__file__).read_bytes()
    return {
        "version": "prospective-blend-v1-enrollment-audit",
        "observedAt": observation_time.isoformat().replace("+00:00", "Z"),
        "inputCommit": source_commit,
        "inputCommitAt": parse_timestamp(commit_at).isoformat().replace("+00:00", "Z"),
        "protocolSha256": digest(protocol_raw),
        "auditCodeSha256": digest(code_raw),
        "sourceHashes": {
            "issued": {"path": ISSUED_PATH, "sha256": digest(issued_raw)},
            "searchedTrendArchives": archive_hashes,
        },
        "requirements": {
            "registeredAt": protocol["registeredAt"],
            "minimumOriginDate": minimum_origin,
            "horizonSessions": horizon,
            "v5": v5,
            "simpleTrend": trend,
        },
        "eligibleCommonIssues": [
            {"origin": origin, "symbols": count} for origin, count in sorted(common.items())
        ],
        "availableAfterRegistration": {
            "issuedJson": available_groups(
                issued_rows, registered_at=registered_at, minimum_origin=minimum_origin),
            "forecastArchives": available_groups(
                trend_rows, registered_at=registered_at, minimum_origin=minimum_origin),
        },
        "enrollment": {
            "status": "blocked" if not common else "eligible",
            "reason": ("no_post_registration_common_v5_21_and_trend_v1_21_issue"
                       if not common else "common_issue_available"),
            "cohortsFrozen": 0,
            "scoresWritten": False,
        },
        "guards": {
            "targetArchivesRead": False,
            "retrospectiveSubstitutionAllowed": False,
            "protocolChanged": False,
            "productionForecastChanged": False,
            "serviceRankingsChanged": False,
        },
        "nextAction": (
            "Keep v1 pending. Do not relabel v7 126/252-session issues or trend-decay-v2 "
            "126/252-session archives as the registered 21-session components. Either resume "
            "genuine post-registration 21-session issues or preregister a separate long-horizon "
            "study before collecting its first eligible issue."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = audit(args.source_commit, args.observed_at)
    raw = canonical(result)
    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(raw)
    print(raw.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
