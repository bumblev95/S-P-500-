"""Freeze and audit fja05680/sp500 as ticker-only, retrospective quarantine.

No network, upstream notebook execution, PIT input writes, cohort export,
security-ID inference, model import, price download or performance calculation.
CSV dates describe candidate effective days, NEVER original publication clocks.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import io
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

from build_pit_sp500_inputs import audit_bundle
from pit_sp500_inputs import InputError, NY, canonical, session_open, sha256, timestamp

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path("research/joint-indicator/pit-inputs-v1")
FOLDER = ROOT / "research/joint-indicator/pit-quarantine-fja-v1"
VERSION = "sp500-fja-quarantine-v1"
BASE_HEAD = "dd84d24dc44eaf6dee6afaad7b3828ac737e2086"
SOURCE_COMMIT = "a2430f2af0c79ddf0748e91de11bdeb1616ab5a7"
REPOSITORY = "https://github.com/fja05680/sp500"
FILES = {
    "history": "S&P 500 Historical Components & Changes (Updated).csv",
    "original": "S&P 500 Historical Components & Changes.csv",
    "changes": "sp500_changes_since_2019.csv",
    "intervals": "sp500_ticker_start_end.csv",
    "current": "sp500.csv",
    "readme": "README.md",
    "license": "LICENSE",
    "history_code": "sp500_historical.ipynb",
    "interval_code": "PIT to Ticker Delta.ipynb",
    "snapshot_code": "sp500_by_date.ipynb",
    "current_code": "sp500.ipynb",
}
BLOCKERS = [
    "uncertified_membership_baseline_and_change_completeness",
    "missing_historical_publication_and_revision_vintages",
    "missing_historical_sector_coverage",
    "missing_permanent_security_identity_and_dated_alias_coverage",
    "missing_delisted_price_vintages",
    "missing_full_lifecycle_delisting_outcomes",
]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE)


def git_hash(kind, raw):
    return hashlib.sha1(kind.encode() + b" " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def safe_path(folder, relative):
    folder = Path(folder).resolve()
    path = (folder / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(folder):
        raise InputError("Path leaves frozen bundle: " + relative)
    return path


def freeze_files(folder, files):
    """Check the entire write set before writing; never replace different bytes."""
    paths = [(safe_path(folder, name), raw) for name, raw in files.items()]
    for path, raw in paths:
        if path.exists() and path.read_bytes() != raw:
            raise InputError("Frozen file differs; use a new version: " + str(path))
    for path, raw in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("xb") as handle:
                handle.write(raw)


def root_tree(raw):
    entries, offset = {}, 0
    while offset < len(raw):
        end = raw.index(b"\0", offset)
        mode, name = raw[offset:end].split(b" ", 1)
        oid = raw[end + 1:end + 21]
        if len(oid) != 20 or name.decode() in entries:
            raise InputError("Invalid/duplicate Git tree entry")
        entries[name.decode()] = (mode.decode(), oid.hex())
        offset = end + 21
    return entries


def import_source(repo, commit, folder=FOLDER):
    """Acquire exact Git objects once. A new upstream commit needs a new version."""
    folder = Path(folder)
    if commit != SOURCE_COMMIT:
        raise InputError("This version requires the pinned source commit")
    if (folder / "source-lock.json").exists():
        load_sources(folder)
        return
    remote = git(repo, "remote", "get-url", "origin").decode().strip().removesuffix(".git")
    if remote != REPOSITORY:
        raise InputError("Unexpected source repository")
    commit_raw = git(repo, "cat-file", "commit", commit)
    if git_hash("commit", commit_raw) != commit:
        raise InputError("Source commit object mismatch")
    tree_sha = commit_raw.splitlines()[0].decode().removeprefix("tree ")
    tree_raw = git(repo, "cat-file", "tree", tree_sha)
    entries = root_tree(tree_raw)
    acquired = datetime.now(timezone.utc).isoformat()
    lock = dict(schemaVersion=1, version=VERSION, researchOnly=True,
                allowedUse="quarantine_audit_only", trustedForPIT=False,
                modelTrainingAllowed=False, productionChangesAllowed=False,
                repository=REPOSITORY, commit=commit, tree=tree_sha,
                sourceResearchHead=BASE_HEAD, retrievedAt=acquired,
                acquisition="git cat-file from a clone of the named repository; timestamp is local payload acquisition",
                historicalKnownAt=None, temporalQuality="retrospective_uncertified",
                clockPolicy="Neither CSV dates nor Git commit time establish original publication/revision availability",
                sources={}, referenceFiles={})
    files = {"sources/commit.git-object": commit_raw, "sources/tree.git-object": tree_raw}
    for role, name in FILES.items():
        mode, blob = entries[name]
        if mode != "100644":
            raise InputError("Expected regular source blob")
        raw = git(repo, "cat-file", "blob", blob)
        path = "sources/" + role + ".gz"
        packed = gzip.compress(raw, mtime=0)
        files[path] = packed
        lock["sources"][role] = dict(sourceId="fja-" + role, upstreamPath=name,
            gitBlobSha=blob, rawSha256=sha256(raw), storedSha256=sha256(packed),
            byteCount=len(raw), path=path, compression="gzip",
            uri=REPOSITORY + "/blob/" + commit + "/" + quote(name, safe="/"))
    previous = json.loads((ROOT / REFERENCE / "manifest.json").read_text())
    paths = set(previous["preservedFiles"])
    paths.update(str(p.relative_to(ROOT)) for p in (ROOT / REFERENCE).rglob("*") if p.is_file())
    paths.update(["scripts/pit_sp500_inputs.py", "scripts/build_pit_sp500_inputs.py",
                  "scripts/test_pit_sp500_inputs.py", ".github/workflows/validate-pit-inputs.yml"])
    for path in sorted(paths):
        raw = safe_path(ROOT, path).read_bytes()
        if raw != git(ROOT, "show", BASE_HEAD + ":" + path):
            raise InputError("Reference differs from base head: " + path)
        lock["referenceFiles"][path] = sha256(raw)
    files["source-lock.json"] = canonical(lock)
    freeze_files(folder, files)
    load_sources(folder)


def load_sources(folder=FOLDER):
    folder = Path(folder)
    lock = json.loads((folder / "source-lock.json").read_text())
    required = dict(schemaVersion=1, version=VERSION, repository=REPOSITORY,
        commit=SOURCE_COMMIT, sourceResearchHead=BASE_HEAD, researchOnly=True,
        allowedUse="quarantine_audit_only", trustedForPIT=False, historicalKnownAt=None,
        temporalQuality="retrospective_uncertified", modelTrainingAllowed=False,
        productionChangesAllowed=False)
    if any(lock.get(k) != v for k, v in required.items()) or set(lock["sources"]) != set(FILES):
        raise InputError("Pinned quarantine-only source contract required")
    timestamp(lock["retrievedAt"])
    commit_raw = (folder / "sources/commit.git-object").read_bytes()
    tree_raw = (folder / "sources/tree.git-object").read_bytes()
    if (git_hash("commit", commit_raw) != SOURCE_COMMIT
            or commit_raw.splitlines()[0] != ("tree " + lock["tree"]).encode()
            or git_hash("tree", tree_raw) != lock["tree"]):
        raise InputError("Pinned Git commit/tree proof mismatch")
    entries, payloads = root_tree(tree_raw), {}
    for role, name in FILES.items():
        source = lock["sources"][role]
        expected_uri = REPOSITORY + "/blob/" + SOURCE_COMMIT + "/" + quote(name, safe="/")
        if (source["upstreamPath"] != name or source["uri"] != expected_uri
                or source["sourceId"] != "fja-" + role
                or source.get("compression") != "gzip"
                or entries[name] != ("100644", source["gitBlobSha"])):
            raise InputError("Source blob not bound to pinned tree/locator")
        packed = safe_path(folder, source["path"]).read_bytes()
        if sha256(packed) != source["storedSha256"]:
            raise InputError("Stored source checksum mismatch: " + role)
        raw = gzip.decompress(packed)
        if (sha256(raw) != source["rawSha256"] or len(raw) != source["byteCount"]
                or git_hash("blob", raw) != source["gitBlobSha"]):
            raise InputError("Original source bytes/blob mismatch: " + role)
        payloads[role] = raw
    return lock, payloads


def read_csv(raw, fields, role):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
    if reader.fieldnames != fields:
        raise InputError("Unexpected CSV header: " + role)
    result = []
    for number, row in enumerate(reader, 2):
        if None in row or any(v is None for v in row.values()):
            raise InputError("Malformed CSV row: " + role)
        result.append(dict(row, locator=dict(sourceId="fja-" + role, csvRecord=number)))
    if not result:
        raise InputError("Empty CSV: " + role)
    return result


def iso_day(value):
    if date.fromisoformat(value).isoformat() != value:
        raise InputError("Expected ISO date")
    return value


def symbols(value, *, empty=False):
    if value == "" and empty:
        return []
    result = value.split(",")
    if (any(not re.fullmatch(r"[A-Za-z0-9.^_/-]+", s) for s in result)
            or len(result) != len(set(result))):
        raise InputError("Empty, invalid or duplicate ticker; no silent normalization")
    return sorted(result)


def parse_history(raw, role="history"):
    result = read_csv(raw, ["date", "tickers"], role)
    prior = None
    for row in result:
        row["date"] = iso_day(row["date"])
        row["tickers"] = symbols(row["tickers"])
        if prior is not None and row["date"] <= prior:
            raise InputError("Duplicate or unordered snapshot dates")
        prior = row["date"]
    return result


def parse_changes(raw):
    result = read_csv(raw, ["date", "add", "remove"], "changes")
    prior = None
    for row in result:
        iso_day(row["date"])
        row["add"], row["remove"] = symbols(row["add"], empty=True), symbols(row["remove"], empty=True)
        if (set(row["add"]) & set(row["remove"]) or not (row["add"] or row["remove"])
                or prior is not None and row["date"] <= prior):
            raise InputError("Ambiguous or unordered change row")
        prior = row["date"]
    return result


def parse_intervals(raw):
    rows = read_csv(raw, ["ticker", "start_date", "end_date"], "intervals")
    by_symbol = defaultdict(list)
    for row in rows:
        if len(symbols(row["ticker"])) != 1:
            raise InputError("One ticker per interval required")
        iso_day(row["start_date"])
        if row["end_date"] and iso_day(row["end_date"]) <= row["start_date"]:
            raise InputError("Nonpositive ticker interval")
        by_symbol[row["ticker"]].append(row)
    for intervals in by_symbol.values():
        intervals.sort(key=lambda r: r["start_date"])
        for a, b in zip(intervals, intervals[1:]):
            if not a["end_date"] or a["end_date"] > b["start_date"]:
                raise InputError("Overlapping ticker intervals; identity is ambiguous")
    return rows


def snapshot_at(history, day):
    """Retrospective as-of candidate, bounded by actual payload dates."""
    if day < history[0]["date"] or day > history[-1]["date"]:
        return None
    i = bisect.bisect_right([r["date"] for r in history], day) - 1
    return history[i]


def interval_members(intervals, day, first, last):
    if not first <= day <= last:
        return None
    return sorted(r["ticker"] for r in intervals if r["start_date"] <= day
                  and (not r["end_date"] or day < r["end_date"]))


def candidate_events(history, changes, intervals):
    groups = defaultdict(list)
    for previous, current in zip(history, history[1:]):
        before, after = set(previous["tickers"]), set(current["tickers"])
        for action, tickers in (("add", after - before), ("remove", before - after)):
            for ticker in sorted(tickers):
                groups[(current["date"], ticker, action)].append(dict(
                    role="history", locator=current["locator"], priorLocator=previous["locator"],
                    semantics="difference of adjacent retrospective snapshots"))
    for row in changes:
        for action in ("add", "remove"):
            for ticker in row[action]:
                groups[(row["date"], ticker, action)].append(dict(
                    role="changes", locator=row["locator"], semantics="explicit upstream change"))
    for row in intervals:
        for action, day in (("add", row["start_date"]), ("remove", row["end_date"])):
            # A left-censored first observation is a baseline, not an entry event.
            if day and day > history[0]["date"]:
                groups[(day, row["ticker"], action)].append(dict(
                    role="intervals", locator=row["locator"], semantics="derived interval boundary; end exclusive"))
    return [dict(candidateId=f"fja:{d}:{t}:{a}", effectiveDateCandidate=d,
                 ticker=t, action=a, historicalKnownAt=None, securityId=None,
                 allowedUse="quarantine_audit_only", evidence=proof)
            for (d, t, a), proof in sorted(groups.items())]


def official_membership(inputs):
    """Only symbol observations tied to that same notice/security/effective time.

    This is a comparison locator, never a permanent-ID mapping or a rename join.
    """
    result = []
    for event in inputs["events"]:
        if event["kind"] != "membership":
            continue
        aliases = [e for e in inputs["events"] if e["kind"] == "symbol"
                   and e["sourceId"] == event["sourceId"]
                   and e["securityId"] == event["securityId"]
                   and e["effectiveAt"] == event["effectiveAt"]
                   and timestamp(e["knownAt"]) <= timestamp(event["knownAt"])
                   and e["value"]["symbol"] is not None]
        tickers = {e["value"]["symbol"] for e in aliases}
        result.append(dict(eventId=event["eventId"], sourceId=event["sourceId"],
            evidenceLocator=event["evidenceLocator"], knownAt=event["knownAt"],
            effectiveAt=event["effectiveAt"], securityId=event["securityId"],
            date=timestamp(event["effectiveAt"]).astimezone(NY).date().isoformat(),
            ticker=next(iter(tickers)) if len(tickers) == 1 else None,
            action="add" if event["value"] else "remove",
            symbolEventIds=sorted(e["eventId"] for e in aliases)))
    return result


def compare_event(candidate, official, date_window=7):
    exact, conflicts = [], []
    for event in official:
        if not event["ticker"] or event["ticker"] != candidate["ticker"]:
            continue
        gap = abs((date.fromisoformat(event["date"]) - date.fromisoformat(candidate["effectiveDateCandidate"])).days)
        if gap == 0 and event["action"] == candidate["action"]:
            exact.append(event["eventId"])
        elif gap == 0 or (gap <= date_window and event["action"] == candidate["action"]):
            conflicts.append(event["eventId"])
    # Contradictory evidence wins; an exact match cannot hide an unresolved conflict.
    status = "conflict" if conflicts else "match" if exact else "unconfirmed"
    return dict(status=status, matchedOfficialEventIds=sorted(exact),
                conflictingOfficialEventIds=sorted(conflicts),
                reason="contradictory_action_or_nearby_effective_date" if conflicts else
                "same_ticker_action_and_effective_day_only" if exact else "no_comparable_official_notice")


def reconcile_official(official, candidates):
    result = []
    for event in official:
        exact, conflicts = [], []
        for candidate in candidates:
            comparison = compare_event(candidate, [event])
            if comparison["status"] == "match":
                exact.append(candidate["candidateId"])
            elif comparison["status"] == "conflict":
                conflicts.append(candidate["candidateId"])
        result.append(dict(event, status="conflict" if conflicts else "match" if exact else "unconfirmed",
            matchedCandidateIds=exact, conflictingCandidateIds=conflicts,
            reason="ticker_action_day_comparison_only" if exact or conflicts else
            "missing_candidate_evidence_or_unresolved_notice_symbol"))
    return result


def consistency_audit(history, original, changes, intervals):
    """Cross-file consistency is NOT independent corroboration or completeness."""
    by_day = {r["date"]: r for r in history}
    discrepancies, suffix_rows, collapsed_rows = [], 0, []
    for row in original:
        stripped = [t.split("-", 1)[0] for t in row["tickers"]]
        suffix_rows += any(a != b for a, b in zip(row["tickers"], stripped))
        collisions = sorted(t for t, count in Counter(stripped).items() if count > 1)
        if collisions:
            collapsed_rows.append(dict(date=row["date"], tickers=collisions, locator=row["locator"]))
        current = by_day.get(row["date"])
        # Replay only the transformations explicitly present in the pinned notebook.
        expected = set(stripped)
        if row["date"] > "2018-10-31":
            expected.add("LIN")
        if current is None or expected != set(current["tickers"]):
            discrepancies.append(dict(kind="original_transform_mismatch", date=row["date"],
                locator=row["locator"], expectedOnly=sorted(expected - set(current["tickers"] if current else [])),
                updatedOnly=sorted(set(current["tickers"] if current else []) - expected)))
    prior = original[-1]["date"]
    previous = by_day.get(prior)
    for row in changes:
        current = by_day.get(row["date"])
        if previous is None or current is None or row["date"] <= prior:
            discrepancies.append(dict(kind="change_chain_missing_or_overlapping", locator=row["locator"]))
        else:
            before, after = set(previous["tickers"]), set(current["tickers"])
            actual_add, actual_remove = after - before, before - after
            if actual_add != set(row["add"]) or actual_remove != set(row["remove"]):
                discrepancies.append(dict(kind="explicit_change_vs_snapshot_delta", date=row["date"],
                    locator=row["locator"], snapshotLocator=current["locator"],
                    declaredAdds=row["add"], declaredRemoves=row["remove"],
                    observedAdds=sorted(actual_add), observedRemoves=sorted(actual_remove)))
        previous, prior = current, row["date"]
    expected_intervals, starts = [], {}
    for row in history:
        members = set(row["tickers"])
        for ticker in sorted(starts.keys() - members):
            expected_intervals.append((ticker, starts.pop(ticker), row["date"]))
        for ticker in members - starts.keys():
            starts[ticker] = row["date"]
    expected_intervals.extend((t, d, "") for t, d in starts.items())
    expected = set(expected_intervals)
    observed = {(r["ticker"], r["start_date"], r["end_date"]) for r in intervals}
    return dict(independentEvidence=False, originalSuffixStrippedRowCount=suffix_rows,
        originalCollapsedTickerRows=collapsed_rows, discrepancies=discrepancies,
        intervalExpectedOnly=[list(x) for x in sorted(expected - observed)],
        intervalObservedOnly=[list(x) for x in sorted(observed - expected)],
        semantics="Pinned upstream strips suffixes, adds LIN after 2018-10-31, deduplicates; diagnostic replay only. No security continuity inferred.")


def origin_audit(requests, history, intervals, candidates, official, reference_report, changes):
    dates = sorted({r["origin"] for r in requests})
    original_reports = {r["request"]["origin"]: r for r in reference_report["requests"]}
    results = []
    previous = history[0]["date"]
    for day in dates:
        row = snapshot_at(history, day)
        members = set(row["tickers"]) if row else set()
        interval_set = interval_members(intervals, day, history[0]["date"], history[-1]["date"])
        # Use the existing session-open helper, never candidate retrieval as knownAt.
        cutoff = session_open(day)
        eligible = [e for e in official if timestamp(e["knownAt"]) < cutoff
                    and timestamp(e["effectiveAt"]) <= cutoff]
        latest = {}
        for event in sorted(eligible, key=lambda e: (e["effectiveAt"], e["knownAt"], e["eventId"])):
            latest[event["securityId"]] = event
        comparisons = []
        for event in latest.values():
            status = "unconfirmed"
            if row is not None and event["ticker"] is not None:
                status = "match" if ((event["ticker"] in members) == (event["action"] == "add")) else "conflict"
            comparisons.append(dict(eventId=event["eventId"], sourceId=event["sourceId"],
                evidenceLocator=event["evidenceLocator"], ticker=event["ticker"],
                expectedPresent=event["action"] == "add", status=status,
                scope="latest seeded membership fact only; not complete subsequent history"))
        window = [c for c in candidates if previous < c["effectiveDateCandidate"] <= day]
        counts = {role: sum(any(e["role"] == role for e in c["evidence"]) for c in window)
                  for role in ("history", "changes", "intervals")}
        results.append(dict(origin=day, requests=[r for r in requests if r["origin"] == day],
            ready=False, status="blocked_quarantine_only", historicalKnownAt=None,
            trustedBaseline=False, candidateBaseline=None if row is None else dict(
                effectiveDateCandidate=row["date"], locator=row["locator"],
                tickers=row["tickers"], tickerCount=len(members),
                ageCalendarDays=(date.fromisoformat(day)-date.fromisoformat(row["date"])).days,
                sameDayTimingUnverified=day == row["date"], permanentSecurityCount=None),
            intervalCrossCheck=dict(status="outside_observed_range" if interval_set is None or row is None else
                "match" if members == set(interval_set) else "conflict",
                snapshotOnly=sorted(members - set(interval_set or [])),
                intervalsOnly=sorted(set(interval_set or []) - members),
                independentEvidence=False, endConvention="exclusive; blank end censored at last history date"),
            changeWindow=dict(fromExclusive=previous, throughInclusive=day,
                candidateEventIds=[c["candidateId"] for c in window], countsByArtifact=counts,
                officialComparisonCounts=dict(Counter(c["officialComparison"]["status"] for c in window)),
                explicitChangeLedgerDateRangeContainsWindow=changes[0]["date"] <= previous and day <= changes[-1]["date"],
                dedicatedChangeLedgerMissingBefore=changes[0]["date"],
                complete=False, missingEvidence="No independent complete baseline/change-history or original-vintage attestation"),
            officialBaselineComparison=comparisons,
            referenceReady=original_reports[day]["complete"],
            preservedReferenceBlockers=original_reports[day]["blockers"],
            blockers=BLOCKERS + ([] if row else ["origin_outside_candidate_history_range"])))
        previous = day
    return results


def build_audit(folder=FOLDER):
    folder = Path(folder)
    lock, raw = load_sources(folder)
    if not lock["referenceFiles"]:
        raise InputError("Frozen reference dependencies required")
    for path, expected in lock["referenceFiles"].items():
        if sha256(safe_path(ROOT, path).read_bytes()) != expected:
            raise InputError("Preserved PIT/prior research changed: " + path)
    reference_report, _ = audit_bundle(ROOT / REFERENCE)
    if (ROOT / REFERENCE / "coverage-audit.json").read_bytes() != canonical(reference_report):
        raise InputError("Reference PIT audit no longer replays")
    inputs = json.loads((ROOT / REFERENCE / "inputs.json").read_text())
    requests = json.loads((ROOT / REFERENCE / "origins.json").read_text())["requests"]
    history, original = parse_history(raw["history"]), parse_history(raw["original"], "original")
    changes, intervals = parse_changes(raw["changes"]), parse_intervals(raw["intervals"])
    official = official_membership(inputs)
    candidates = candidate_events(history, changes, intervals)
    for candidate in candidates:
        candidate["officialComparison"] = compare_event(candidate, official)
    reconciled = reconcile_official(official, candidates)
    out_of_scope = [dict(eventId=e["eventId"], sourceId=e["sourceId"], kind=e["kind"],
        evidenceLocator=e["evidenceLocator"], status="unconfirmed",
        reason="ticker_membership_source_cannot_verify_this_domain")
        for e in inputs["events"] if e["kind"] != "membership"]
    origins = origin_audit(requests, history, intervals, candidates, official, reference_report, changes)
    official_registry = [s for s in inputs["sources"] if s["temporalQuality"] == "dated_notice"]
    report = dict(version=VERSION, researchOnly=True, status="blocked_quarantine_only",
        sourceResearchHead=BASE_HEAD, sourceCommit=SOURCE_COMMIT,
        sourceLockSha256=sha256((folder / "source-lock.json").read_bytes()),
        modelTrainingAllowed=False, productionChangesAllowed=False, cohortExportAllowed=False,
        fullHistoricalCoverage=False, originCount=len(origins), readyOriginCount=0,
        unchangedPITReadyOriginCount=reference_report["readyOriginCount"],
        blockers=BLOCKERS, officialSources=official_registry,
        scope=dict(comparison="retrospective ticker/action/effective-day only; no historical availability or identity certification",
            dateConflictWindowCalendarDays=7, missingEvent="unconfirmed, not an invented conflict or evidence of no change",
            currentSnapshot="archived for provenance only; never used for past membership or sector",
            intervalCensoring="start at first snapshot is left-censored; blank end is right-censored at last snapshot",
            chronology="candidate knownAt null; post-origin notices excluded from per-origin comparison"),
        sourceSummary=dict(snapshotRows=len(history), firstCandidateDate=history[0]["date"],
            lastCandidateDate=history[-1]["date"], originalRows=len(original),
            originalThrough=original[-1]["date"], changeRows=len(changes),
            explicitChangesFrom=changes[0]["date"], explicitChangesThrough=changes[-1]["date"],
            intervals=len(intervals), noOpSnapshotTransitions=sum(a["tickers"] == b["tickers"] for a,b in zip(history,history[1:])),
            candidateEvents=len(candidates), candidateBaselineOrigins=sum(o["candidateBaseline"] is not None for o in origins),
            completeCoverageAttestations=0, permanentIdentityMappings=0, priceRows=0, outcomeRows=0),
        candidateComparisonCounts={s:sum(c["officialComparison"]["status"] == s for c in candidates)
                                   for s in ("match","conflict","unconfirmed")},
        candidateComparisonPartitions={s:[c["candidateId"] for c in candidates if c["officialComparison"]["status"] == s]
                                       for s in ("match","conflict","unconfirmed")},
        officialMembershipComparisonCounts={s:sum(c["status"] == s for c in reconciled)
                                            for s in ("match","conflict","unconfirmed")},
        officialMembershipComparisons=reconciled, unsupportedOfficialFacts=out_of_scope,
        internalConsistency=consistency_audit(history, original, changes, intervals), origins=origins)
    observations = dict(version=VERSION, allowedUse="quarantine_audit_only", historicalKnownAt=None,
        trustedForPIT=False, sourceCommit=SOURCE_COMMIT, events=candidates,
        note="Ticker observations with source CSV record locators, not PIT events or security mappings")
    report["observationsSha256"] = sha256(canonical(observations))
    return report, observations


def render_origins_csv(report):
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["origin","candidate_baseline_date","candidate_tickers","baseline_age_days",
                     "interval_comparison","window_history_events","window_explicit_change_events",
                     "official_baseline_matches","official_baseline_conflicts","ready","blockers"])
    for row in report["origins"]:
        baseline = row["candidateBaseline"] or {}
        counts = row["changeWindow"]["countsByArtifact"]
        writer.writerow([row["origin"],baseline.get("effectiveDateCandidate",""),baseline.get("tickerCount",""),
            baseline.get("ageCalendarDays",""),row["intervalCrossCheck"]["status"],counts["history"],counts["changes"],
            sum(e["status"]=="match" for e in row["officialBaselineComparison"]),
            sum(e["status"]=="conflict" for e in row["officialBaselineComparison"]),"false",";".join(row["blockers"])])
    return out.getvalue().encode()


def artifacts(report, observations):
    return {"coverage-audit.json": canonical(report),
            "observations.json.gz": gzip.compress(canonical(observations), mtime=0),
            "origin-coverage.csv": render_origins_csv(report)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=FOLDER)
    parser.add_argument("--source-repo", type=Path)
    parser.add_argument("--source-commit")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--import-source", action="store_true")
    mode.add_argument("--audit", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--export-cohorts", action="store_true", help="Always refused: quarantine has no export path")
    args = parser.parse_args(argv)
    try:
        if args.export_cohorts:
            raise InputError("Quarantine is audit-only; cohort export is forbidden")
        if args.import_source:
            if args.source_repo is None or args.source_commit is None:
                raise InputError("Explicit source repo and immutable commit required")
            import_source(args.source_repo, args.source_commit, args.folder)
            print(json.dumps(dict(version=VERSION, imported=True, sourceCommit=SOURCE_COMMIT, trustedForPIT=False)))
            return 0
        report, observations = build_audit(args.folder)
        expected = artifacts(report, observations)
        if args.verify:
            for name, raw in expected.items():
                stored = (args.folder / name).read_bytes()
                # Gzip headers may differ across Python/zlib builds; verify canonical payload.
                if (gzip.decompress(stored) != gzip.decompress(raw) if name.endswith(".gz") else stored != raw):
                    raise InputError("Frozen quarantine audit differs: " + name)
        else:
            freeze_files(args.folder, expected)
        print(json.dumps({k:report[k] for k in ("version","status","originCount","readyOriginCount",
            "candidateComparisonCounts","officialMembershipComparisonCounts","modelTrainingAllowed","productionChangesAllowed")}))
        return 0
    except (InputError, KeyError, OSError, ValueError, csv.Error, subprocess.CalledProcessError) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
