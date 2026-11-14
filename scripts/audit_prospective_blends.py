"""Audit five prospectively frozen blend cohorts after all targets mature."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from prospective_blends import (
    COHORT_COUNT, REGISTERED_PROTOCOL_SHA256, XNYS_EARLY_CLOSES,
    build_methods, component_return, joint_gate, metric, sessions_after,
)

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "research/joint-indicator/prospective-blend-v1"
PROTOCOL_PATH = "research/joint-indicator/prospective-blend-v1/PROTOCOL.json"
ISSUE_PREFIX = "research/joint-indicator/prospective-blend-v1/issued/"
TARGET_PATTERN = "ml/archive/{date}-pooled-hgb-pattern-v3-medium-long.json"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def git_bytes(commit: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)


def git_time(commit: str) -> datetime:
    value = git("show", "-s", "--format=%cI", commit)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Commit has no timezone: {commit}")
    return parsed.astimezone(timezone.utc)


def target_close_utc(target: str) -> datetime:
    local_close = time(13, 0) if target in XNYS_EARLY_CLOSES else time(16, 0)
    close = datetime.combine(date.fromisoformat(target), local_close, ZoneInfo("America/New_York"))
    return close.astimezone(timezone.utc)


def target_start_utc(target: str) -> datetime:
    start = datetime.combine(date.fromisoformat(target), time.min, ZoneInfo("America/New_York"))
    return start.astimezone(timezone.utc)


def list_files(commit: str) -> list[str]:
    paths = git("ls-tree", "-r", "--name-only", commit, "--", ISSUE_PREFIX).splitlines()
    return sorted(path for path in paths if path.startswith(ISSUE_PREFIX) and path.endswith(".json"))


def first_add_commit(commit: str, path: str) -> str:
    rows = git("log", "--diff-filter=A", "--format=%H", "--reverse", commit, "--", path).splitlines()
    if not rows:
        raise ValueError(f"Issue artifact has no verifiable first-add commit: {path}")
    return rows[0]


def verify_issue_artifact(source_commit: str, path: str, raw: bytes, snapshot: dict,
                          protocol_sha: str) -> str:
    if snapshot.get("protocolSha256") != protocol_sha:
        raise ValueError("Issue artifact references a different registered protocol")
    origin = snapshot["origin"]
    expected_sessions = sessions_after(origin)
    expected_target = expected_sessions[-1]
    if snapshot.get("targetSessions") != expected_sessions or snapshot.get("targetDate") != expected_target:
        raise ValueError(f"Frozen session/target mismatch for {origin}")
    if snapshot.get("horizonSessions") != 21 or snapshot.get("containsTargetData") is not False:
        raise ValueError(f"Issue artifact is not a pre-target 21-session record: {path}")
    if snapshot["cohort"].get("n") != len(snapshot["rows"]):
        raise ValueError(f"Frozen cohort count mismatch for {origin}")
    symbols = [row["symbol"] for row in snapshot["rows"]]
    if symbols != sorted(set(symbols)) or symbols != snapshot["cohort"].get("symbols"):
        raise ValueError(f"Frozen symbol list is not sorted and unique for {origin}")

    add_commit = first_add_commit(source_commit, path)
    add_time = git_time(add_commit)
    target_start = target_start_utc(expected_target)
    if add_time >= target_start:
        raise ValueError(f"Issue artifact was committed after target session began: {path}")
    if parse_timestamp(snapshot["capturedAt"]) > add_time:
        raise ValueError(f"Issue artifact capture time follows its archive commit: {path}")
    if parse_timestamp(snapshot["capturedAt"]) >= target_start:
        raise ValueError(f"Issue artifact capture was not before the target session: {path}")
    input_commit = snapshot["inputCommit"]
    if subprocess.run(["git", "merge-base", "--is-ancestor", input_commit, add_commit], cwd=ROOT,
                      check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        raise ValueError(f"Frozen input commit is not an ancestor of issue archive: {path}")
    input_commit_time = git_time(input_commit)
    if input_commit_time >= target_start:
        raise ValueError(f"Forecast input archive was committed after target session began: {path}")
    if parse_timestamp(snapshot["inputCommitAt"]) != input_commit_time:
        raise ValueError(f"Frozen input commit timestamp mismatch: {path}")
    if git_bytes(add_commit, path) != raw:
        raise ValueError(f"Issue artifact was rewritten after first publication: {path}")

    inputs = snapshot["inputs"]
    issued = git_bytes(input_commit, inputs["issued"]["path"])
    if digest(issued) != inputs["issued"]["sha256"]:
        raise ValueError(f"Issued archive hash does not match frozen provenance: {origin}")
    for source in inputs["simpleTrend"]:
        trend_raw = git_bytes(input_commit, source["path"])
        if digest(trend_raw) != source["sha256"]:
            raise ValueError(f"Trend archive hash does not match frozen provenance: {origin}")

    issue_doc = json.loads(issued)
    registered_at = parse_timestamp(json.loads(git_bytes(source_commit, PROTOCOL_PATH))["registeredAt"])
    trend_docs: dict[str, list[dict]] = {}
    for source in inputs["simpleTrend"]:
        import csv
        import io
        trend_docs[source["path"]] = list(csv.DictReader(io.StringIO(
            git_bytes(input_commit, source["path"]).decode("utf-8"))))
    v5_by_symbol = {}
    for row in issue_doc:
        if (row.get("model") == "environment-challenger-v5-horizon-specific"
                and row.get("asOf") == origin and str(row.get("horizon")) == "21"):
            if parse_timestamp(row["issuedAt"]) < registered_at:
                continue
            if row["symbol"] in v5_by_symbol:
                raise ValueError(f"Duplicate source v5 issue row {origin}/{row['symbol']}")
            v5_by_symbol[row["symbol"]] = row
    trend_by_symbol = {}
    for rows in trend_docs.values():
        for row in rows:
            if (row.get("model") == "trend-decay-v1" and row.get("asOf") == origin
                    and str(row.get("horizon")) == "21"):
                if parse_timestamp(row["issuedAt"]) < registered_at:
                    continue
                if row["symbol"] in trend_by_symbol:
                    raise ValueError(f"Duplicate source trend issue row {origin}/{row['symbol']}")
                trend_by_symbol[row["symbol"]] = row
    if set(v5_by_symbol) & set(trend_by_symbol) != set(symbols):
        raise ValueError(f"Frozen cohort is not the full v5/trend intersection for {origin}")

    for row in snapshot["rows"]:
        symbol = row["symbol"]
        v5_row, trend_row = v5_by_symbol[symbol], trend_by_symbol[symbol]
        if (parse_timestamp(v5_row["issuedAt"]) > parse_timestamp(snapshot["capturedAt"])
                or parse_timestamp(trend_row["issuedAt"]) > parse_timestamp(snapshot["capturedAt"])):
            raise ValueError(f"Candidate was captured before a component was issued: {origin}/{symbol}")
        if digest(canonical(v5_row)) != row["sourceRows"]["v5Sha256"]:
            raise ValueError(f"Frozen v5 row hash mismatch: {origin}/{symbol}")
        if digest(canonical(trend_row)) != row["sourceRows"]["simpleTrendSha256"]:
            raise ValueError(f"Frozen trend row hash mismatch: {origin}/{symbol}")
        if row["v5IssuedAt"] != v5_row["issuedAt"] or row["simpleTrendIssuedAt"] != trend_row["issuedAt"]:
            raise ValueError(f"Issue timestamps changed for {origin}/{symbol}")
        expected_methods = build_methods(
            component_return(float(v5_row["horizonModel"]), float(v5_row["anchor"])),
            component_return(float(trend_row["base"]), float(trend_row["anchor"])),
            float(v5_row["anchor"]),
        )
        if canonical(row["methods"]) != canonical(expected_methods):
            raise ValueError(f"Frozen candidate formula mismatch: {origin}/{symbol}")
    return add_commit


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def audit(source_commit: str, output: Path | None = None) -> dict:
    source_commit = git("rev-parse", source_commit)
    protocol_raw = git_bytes(source_commit, PROTOCOL_PATH)
    if digest(protocol_raw) != REGISTERED_PROTOCOL_SHA256:
        raise ValueError("Registered protocol bytes changed; start a new preregistered version")
    protocol = json.loads(protocol_raw)
    if subprocess.run(["git", "merge-base", "--is-ancestor", protocol["registrationMainCommit"], source_commit],
                      cwd=ROOT, check=False, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode != 0:
        raise ValueError("Outcome source is not descended from the registered main commit")
    protocol_sha = digest(protocol_raw)
    files = list_files(source_commit)
    if len(files) != COHORT_COUNT:
        return {"status": "pending", "reason": "five_pre_target_issue_cohorts_not_yet_frozen",
                "issueCohortsFrozen": len(files), "required": COHORT_COUNT,
                "scoresWritten": False}

    snapshots = []
    for path in files:
        raw = git_bytes(source_commit, path)
        snapshot = json.loads(raw)
        commit = verify_issue_artifact(source_commit, path, raw, snapshot, protocol_sha)
        snapshots.append((path, raw, snapshot, commit))
    snapshots.sort(key=lambda item: (item[2]["origin"], item[0]))
    for prior, current in zip(snapshots, snapshots[1:]):
        if current[2]["origin"] < prior[2]["targetDate"]:
            raise ValueError("Frozen prospective observation windows overlap")

    pending = []
    complete = []
    for path, raw, snapshot, issue_commit in snapshots:
        target_path = TARGET_PATTERN.format(date=snapshot["targetDate"])
        try:
            target_raw = git_bytes(source_commit, target_path)
        except subprocess.CalledProcessError:
            pending.append({"origin": snapshot["origin"], "targetDate": snapshot["targetDate"],
                            "reason": "target_archive_not_present"})
            continue
        target_doc = json.loads(target_raw)
        targets = {symbol: item for symbol, item in target_doc.get("stocks", {}).items()
                   if item.get("asOf") == snapshot["targetDate"]}
        target_add_commit = first_add_commit(source_commit, target_path)
        if git_time(target_add_commit) < target_close_utc(snapshot["targetDate"]):
            raise ValueError(f"Target price archive predates the target session close: {target_path}")
        if git_bytes(target_add_commit, target_path) != target_raw:
            raise ValueError(f"Target archive was rewritten after first publication: {target_path}")
        missing = sorted(set(snapshot["cohort"]["symbols"]) - set(targets))
        if missing:
            pending.append({"origin": snapshot["origin"], "targetDate": snapshot["targetDate"],
                            "reason": "incomplete_frozen_target_cohort", "missing": missing,
                            "targetCoverage": len(snapshot["cohort"]["symbols"]) - len(missing),
                            "targetRequired": len(snapshot["cohort"]["symbols"])})
            continue
        cohort_rows = []
        for issued_row in snapshot["rows"]:
            symbol = issued_row["symbol"]
            target_price = float(targets[symbol]["price"])
            if target_price <= 0:
                raise ValueError(f"Non-positive target price for {snapshot['origin']}/{symbol}")
            anchor = float(issued_row["anchor"])
            if anchor <= 0:
                raise ValueError(f"Non-positive common anchor for {snapshot['origin']}/{symbol}")
            cohort_rows.append({
                "symbol": symbol,
                "origin": snapshot["origin"],
                "targetDate": snapshot["targetDate"],
                "targetPrice": target_price,
                "actualReturn": target_price / anchor - 1.0,
                "methods": issued_row["methods"],
            })
        complete.append({
            "origin": snapshot["origin"], "targetDate": snapshot["targetDate"],
            "issueFile": path, "issueCommit": issue_commit,
            "issueFileSha256": digest(raw), "targetFile": target_path,
            "targetFileSha256": digest(target_raw), "rows": cohort_rows,
        })

    if pending or len(complete) != COHORT_COUNT:
        return {"status": "pending", "reason": "full_frozen_cohort_targets_not_yet_complete",
                "sourceCommit": source_commit, "completeOrigins": len(complete),
                "pendingOrigins": pending, "scoresWritten": False}

    methods = ("noChange", "v5", "simpleTrend", "fixed50", "downsideOverride")
    origin_metrics = {name: [] for name in methods}
    origins = []
    for cohort in complete:
        scores = {name: metric(cohort["rows"], name) for name in methods}
        for name in methods:
            origin_metrics[name].append(scores[name])
        origins.append({
            "origin": cohort["origin"], "targetDate": cohort["targetDate"],
            "n": len(cohort["rows"]), "issueFile": cohort["issueFile"],
            "issueCommit": cohort["issueCommit"], "issueFileSha256": cohort["issueFileSha256"],
            "targetFile": cohort["targetFile"], "targetFileSha256": cohort["targetFileSha256"],
            "metrics": scores,
        })
    macro = {name: {key: (sum(item[key] for item in values if item.get(key) is not None)
                                / sum(item.get(key) is not None for item in values)
                          if any(item.get(key) is not None for item in values) else None)
                     for key in ("mape", "returnMaePctPoints", "upRecall", "downRecall",
                                 "downWarningPrecision", "falseDownWarningRate")}
             for name, values in origin_metrics.items()}
    result = {
        "version": protocol["version"],
        "registeredAt": protocol["registeredAt"],
        "protocolSha256": protocol_sha,
        "sourceCommit": source_commit,
        "sourceCommitAt": git_time(source_commit).isoformat().replace("+00:00", "Z"),
        "cohortCount": len(origins),
        "summaryWeighting": "equal-origin mean; per-origin denominators and metrics retained",
        "metricsByMethod": macro,
        "jointGate": joint_gate(origin_metrics),
        "selection": None,
        "productionPromotion": False,
        "productionForecastChanged": False,
        "serviceRankingsChanged": False,
        "tradeClaims": False,
        "origins": origins,
        "rows": [row for cohort in complete for row in cohort["rows"]],
    }
    if output is not None:
        if output.exists():
            raise ValueError(f"Refusing to overwrite an existing prospective result: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(canonical(result))
    return {"status": "complete", "result": result, "scoresWritten": output is not None,
            "output": str(output) if output else None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", default="HEAD", help="Outcome archive commit to pin")
    parser.add_argument("--output", type=Path, default=STUDY / "results.json")
    args = parser.parse_args(argv)
    result = audit(args.source_commit)
    if result["status"] == "pending":
        print(json.dumps(result, sort_keys=True))
        return 2
    audit(args.source_commit, args.output)
    print(json.dumps({"status": "complete", "sourceCommit": args.source_commit,
                      "output": str(args.output), "selection": None}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
