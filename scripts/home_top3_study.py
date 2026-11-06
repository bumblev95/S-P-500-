"""Prospective, append-only evidence for the homepage display policy.

Read the published ranking; never run a selector, create orders, or backfill
rankings. Price histories are inputs only for observations already in the ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

import exchange_calendars as xcals

ROOT = Path(__file__).resolve().parents[1]
STUDY = "daily-top3-v1-prospective-v1"
FOLDER = Path("simulation/home-top3") / STUDY
POLICY = "daily-top3-v1"
FIRST_COMMIT = "861c2f0ad86a4d076e9243e0bb02b22f02beccb5"
FIRST_OBSERVED_AT = "2026-10-04T20:07:32Z"
POLICY_COMMIT = "0974763563dd137ccc6dd22631296260edd48e5e"
POLICY_INTRODUCED_AT = "2026-10-04T19:53:08Z"
CALENDAR_VERSION = "4.13.2"
RULE_FILES = ("scripts/build_home_rankings.cjs", "assets/stock-assessment.js",
              "assets/technical-guide.js")
HORIZONS = (20, 63)
MIN_COHORTS = 20
ENTRY_CODES = {"buy", "breakout", "pullback", "riskwait", "overextended",
               "confirm", "watch", "unavailable", "avoid"}
HOLDING_CODES = {"reduce", "protect", "hold"}
UTC = timezone.utc


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timezone required")
    return result.astimezone(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def quote_for(forecasts, symbol):
    # Homepage symbols use BRK-B while the EOD/forecast source can use BRK.B.
    stocks = forecasts["stocks"]
    return stocks.get(symbol) or stocks.get(symbol.replace("-", "."))


def calendar():
    if xcals.__version__ != CALENDAR_VERSION:
        raise ValueError("Calendar version changed; preserve this study and review a new version")
    # Explicit bounds avoid package defaults tied to the runner's current date.
    return xcals.get_calendar("XNYS", start="2026-01-01", end="2040-12-31")


def session_date(session):
    return session.strftime("%Y-%m-%d")


def next_entry(observed_at, cal):
    """First session whose open is strictly after the observation, then its close."""
    now = instant(observed_at)
    session = cal.date_to_session(now.astimezone(cal.tz).date().isoformat(), direction="next")
    if cal.session_open(session).to_pydatetime() <= now:
        session = cal.next_session(session)
    return session_date(session)


def completed(day, now, cal):
    return cal.is_session(day) and cal.session_close(day).to_pydatetime() + timedelta(minutes=15) <= now


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def source(root, commit=None):
    ref = commit or git(root, "rev-parse", "HEAD")
    paths = ("market/home.json", "forecasts/latest.json")
    blobs = {p: git(root, "rev-parse", ref + ":" + p) for p in paths}
    # A committed source is the provenance anchor. Never claim that dirty input
    # bytes were published in HEAD.
    for p in paths:
        if (root / p).read_bytes() != subprocess.check_output(["git", "show", ref + ":" + p], cwd=root):
            raise ValueError("Ranking/price source is not the committed snapshot: " + p)
    return {"gitCommit": ref, "homeGitBlob": blobs[paths[0]],
            "forecastsGitBlob": blobs[paths[1]]}


def rule_hashes(root, commit=None):
    return {p: hashlib.sha256(subprocess.check_output(["git", "show", commit + ":" + p], cwd=root)
                            if commit else (root / p).read_bytes()).hexdigest() for p in RULE_FILES}


def write_exclusive(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical(value) + "\n")


def publish(path, value):
    text = canonical(value) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def observation(home, forecasts, observed_at, evidence, cal):
    ranks = home["rankings"]
    if ranks.get("policy") != POLICY:
        raise ValueError("Wrong homepage policy")
    day = ranks["asOf"]
    now = instant(observed_at)
    if now < instant(FIRST_OBSERVED_AT) or not completed(day, now, cal):
        raise ValueError("Pre-policy or unfinished ranking observation")
    if (now.date() - datetime.fromisoformat(day).date()).days > 5:
        raise ValueError("Historical/stale ranking cannot be backfilled")
    for stamp in (home["generatedAt"], ranks["evaluatedAt"], ranks["priceGeneratedAt"],
                  ranks["marketGeneratedAt"], forecasts["generatedAt"]):
        if instant(stamp) > now:
            raise ValueError("Future source timestamp")
    if ranks["priceGeneratedAt"] != forecasts["generatedAt"]:
        raise ValueError("Ranking and price source vintages disagree")
    expected = (3, 3) if ranks["eligibleCount"] >= 6 else None
    sizes = tuple(len(ranks[s]) for s in ("buy", "sell"))
    if any(n > 3 for n in sizes) or expected and sizes != expected:
        raise ValueError("Invalid TOP3 sizes")
    cards, seen = [], set()
    for side in ("buy", "sell"):
        for rank, original in enumerate(ranks[side], 1):
            symbol = original["symbol"]
            if symbol in seen or original["asOf"] != day:
                raise ValueError("Duplicate or mixed-date ranking")
            seen.add(symbol)
            if original["code"] not in ENTRY_CODES or original["holdingCode"] not in HOLDING_CODES:
                raise ValueError("Unknown signal; start a new study version")
            score = original["score"]
            if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 100:
                raise ValueError("Invalid score")
            signal = original["code"] == "buy" if side == "buy" else original["holdingCode"] == "reduce"
            if original["selection"] != ("signal" if signal else "relative"):
                raise ValueError("Selection does not match original signal")
            quote = quote_for(forecasts, symbol)
            if not quote or quote["asOf"] != day or not positive(quote["price"]) or instant(quote["sourceUpdatedAt"]) > now or not completed(day, instant(quote["sourceUpdatedAt"]), cal):
                raise ValueError("Invalid reference close")
            cards.append({**original, "side": side, "rank": rank,
                          "referenceClose": quote["price"], "referenceCloseDate": day})
    if not cards:
        raise ValueError("No observed cards; do not synthesize a cohort")
    entry = next_entry(observed_at, cal)
    return {"basisDate": day, "observedAt": observed_at, "entryDate": entry,
            "targetDates": {str(h): session_date(cal.session_offset(entry, h)) for h in HORIZONS},
            "rankings": ranks, "cards": cards, "source": evidence,
            "sourceGeneratedAt": home["generatedAt"]}


def validate_observation(item, manifest, cal):
    if instant(item["observedAt"]) < instant(manifest["firstObservedAt"]):
        raise ValueError("Observation predates policy start")
    if item["entryDate"] != next_entry(item["observedAt"], cal):
        raise ValueError("Observation entry date is not causal")
    ranks = item["rankings"]
    if ranks["policy"] != POLICY or ranks["asOf"] != item["basisDate"]:
        raise ValueError("Observation policy/date mismatch")
    if item["targetDates"] != {str(h): session_date(cal.session_offset(item["entryDate"], h)) for h in HORIZONS}:
        raise ValueError("Horizon dates changed")
    originals = [{**q, "side": side, "rank": rank} for side in ("buy", "sell")
                 for rank, q in enumerate(ranks[side], 1)]
    restored = [{k: v for k, v in card.items() if k not in ("referenceClose", "referenceCloseDate")}
                for card in item["cards"]]
    if originals != restored or any(not positive(q["referenceClose"]) or q["referenceCloseDate"] != item["basisDate"]
                                   for q in item["cards"]):
        raise ValueError("Original cards changed")


def load(folder, cal):
    manifest = read(folder / "manifest.json")
    if manifest["studyId"] != STUDY or manifest["policy"] != POLICY or manifest["firstObservedAt"] != FIRST_OBSERVED_AT:
        raise ValueError("Study contract changed")
    if manifest["horizons"] != list(HORIZONS) or manifest["minimumMatureCohorts"] != MIN_COHORTS or manifest["calendar"] != {
            "name": "XNYS", "package": "exchange_calendars", "version": CALENDAR_VERSION, "completionDelayMinutes": 15}:
        raise ValueError("Maturity/calendar contract changed")
    records, observations, prices, revisions = [], [], {}, set()
    previous_hash = None
    for i, path in enumerate(sorted((folder / "ledger").glob("*.json"))):
        record = read(path)
        payload = {k: v for k, v in record.items() if k != "hash"}
        if record["schemaVersion"] != 1 or record["studyId"] != STUDY or record["sequence"] != i or record["previousHash"] != previous_hash or record["manifestHash"] != digest(manifest) or digest(payload) != record["hash"]:
            raise ValueError("Immutable ledger chain invalid: " + path.name)
        if path.name != f'{i:08d}-{record["hash"][:16]}.json':
            raise ValueError("Ledger filename changed")
        at = instant(record["recordedAt"])
        if records and at < instant(records[-1]["recordedAt"]):
            raise ValueError("Record clock went backwards")
        item = record["data"]
        if record["kind"] == "observation":
            validate_observation(item, manifest, cal)
            if instant(item["observedAt"]) > at or observations and (item["basisDate"] <= observations[-1]["basisDate"] or
                    instant(item["observedAt"]) < instant(observations[-1]["observedAt"])):
                raise ValueError("Historical/duplicate observation inserted")
            observations.append(item)
        elif record["kind"] == "prices":
            tracked = {q["symbol"] for o in observations for q in o["cards"]} | {"SPY"}
            start = min(o["entryDate"] for o in observations)
            for q in item["prices"]:
                key = (q["symbol"], q["date"])
                if key in prices or q["symbol"] not in tracked or q["date"] < start or not positive(q["close"]) or not completed(q["date"], at, cal) or instant(q["sourceUpdatedAt"]) > at:
                    raise ValueError("Previously observed/future/invalid price")
                prices[key] = q["close"]
            for q in item["revisions"]:
                key = (q["symbol"], q["date"])
                if key not in prices or prices[key] != q["retainedClose"] or not positive(q["providerClose"]):
                    raise ValueError("Invalid price revision")
                revisions.add(key)
        else:
            raise ValueError("Unknown ledger record kind")
        records.append(record)
        previous_hash = record["hash"]
    if not observations or observations[0]["source"]["gitCommit"] != FIRST_COMMIT or observations[0]["observedAt"] != FIRST_OBSERVED_AT:
        raise ValueError("First operational observation missing")
    cache = folder / "latest.json"
    if cache.exists():
        latest = read(cache)
        if latest["sequence"] >= len(records) or latest["sequence"] == len(records) - 1 and latest["ledgerHash"] != previous_hash:
            raise ValueError("Ledger truncated/replaced")
    return {"manifest": manifest, "records": records, "observations": observations,
            "prices": prices, "revisions": revisions}


def append(folder, state, kind, item, now):
    records = state["records"]
    if records and now < instant(records[-1]["recordedAt"]):
        raise ValueError("Observation clock went backwards")
    payload = {"schemaVersion": 1, "studyId": STUDY, "sequence": len(records),
               "previousHash": records[-1]["hash"] if records else None,
               "manifestHash": digest(state["manifest"]), "recordedAt": iso(now),
               "kind": kind, "data": item}
    record = {**payload, "hash": digest(payload)}
    write_exclusive(folder / "ledger" / f'{len(records):08d}-{record["hash"][:16]}.json', record)
    records.append(record)
    if kind == "observation":
        state["observations"].append(item)
    else:
        state["prices"].update({(q["symbol"], q["date"]): q["close"] for q in item["prices"]})
        state["revisions"].update((q["symbol"], q["date"]) for q in item["revisions"])


def capture(folder, state, home, forecasts, now, evidence, cal):
    if home["rankings"].get("policy") != POLICY:
        raise ValueError("Wrong homepage policy")
    day = home["rankings"].get("asOf")
    last = state["observations"][-1]["basisDate"]
    if day == last:
        return "retained first observation for existing close date"
    if day is None or day < last:
        raise ValueError("Historical ranking backfill/reversion forbidden")
    item = observation(home, forecasts, iso(now), evidence, cal)
    append(folder, state, "observation", item, now)
    return "new observed close date"


def capture_prices(folder, state, forecasts, now, evidence, cal):
    if instant(forecasts["generatedAt"]) > now:
        raise ValueError("Future price source")
    symbols = {q["symbol"] for o in state["observations"] for q in o["cards"]} | {"SPY"}
    start = min(o["entryDate"] for o in state["observations"])
    additions, revisions = [], []
    for symbol in sorted(symbols):
        quote = quote_for(forecasts, symbol)
        if not quote:
            continue  # Delisted/removed/missing symbols stay in the denominator.
        if instant(quote["sourceUpdatedAt"]) > now or instant(quote["sourceUpdatedAt"]) > instant(forecasts["generatedAt"]):
            raise ValueError("Future stock price vintage")
        seen = set()
        for q in quote.get("history", []):
            day = q["date"]
            if day < start:
                continue
            if day in seen:
                raise ValueError("Duplicate history date")
            seen.add(day)
            if day > quote["asOf"] or not positive(q.get("close")) or not completed(day, now, cal) or not completed(day, instant(quote["sourceUpdatedAt"]), cal):
                continue
            key = (symbol, day)
            old = state["prices"].get(key)
            if old is None:
                additions.append({"symbol": symbol, "date": day, "close": q["close"],
                                  "sourceUpdatedAt": quote["sourceUpdatedAt"]})
            elif abs(q["close"] / old - 1) > 1e-6 and key not in state["revisions"]:
                revisions.append({"symbol": symbol, "date": day, "retainedClose": old,
                                  "providerClose": q["close"]})
    if additions or revisions:
        append(folder, state, "prices", {"source": evidence, "sourceGeneratedAt": forecasts["generatedAt"],
                                        "prices": additions, "revisions": revisions}, now)


def outcome(item, card, horizon, state, cal):
    entry, target = item["entryDate"], item["targetDates"][str(horizon)]
    base = {"basisDate": item["basisDate"], "observedAt": item["observedAt"], **card,
            "horizon": horizon, "entryDate": entry, "targetDate": target,
            "return": None, "spyReturn": None, "excessReturn": None}
    at = instant(state["records"][-1]["recordedAt"])
    if not completed(target, at, cal):
        return {**base, "status": "pending_horizon"}
    days = [session_date(s) for s in cal.sessions_in_range(entry, target)]
    if any((s, d) in state["revisions"] for s in (card["symbol"], "SPY") for d in days):
        return {**base, "status": "price_revision_quarantined"}
    prices = state["prices"]
    if any(("SPY", d) not in prices for d in days):
        return {**base, "status": "missing_benchmark_session"}
    if any((card["symbol"], d) not in prices for d in (entry, target)):
        return {**base, "status": "missing_stock_endpoint"}
    stock_return = prices[(card["symbol"], target)] / prices[(card["symbol"], entry)] - 1
    spy_return = prices[("SPY", target)] / prices[("SPY", entry)] - 1
    return {**base, "status": "mature", "entryClose": prices[(card["symbol"], entry)],
            "targetClose": prices[(card["symbol"], target)], "spyEntryClose": prices[("SPY", entry)],
            "spyTargetClose": prices[("SPY", target)], "return": stock_return,
            "spyReturn": spy_return, "excessReturn": stock_return - spy_return}


def group_summary(rows, minimum):
    by_day = {}
    for row in rows:
        by_day.setdefault(row["basisDate"], []).append(row)
    enough = len(by_day) >= minimum
    daily = [mean(q["return"] for q in day) for day in by_day.values()]
    excess = [mean(q["excessReturn"] for q in day) for day in by_day.values()]
    spy = [mean(q["spyReturn"] for q in day) for day in by_day.values()]
    return {"matureRows": len(rows), "matureCohorts": len(by_day), "minimumMatureCohorts": minimum,
            "status": "descriptive_only" if enough else "insufficient_mature_cohorts",
            "meanReturn": mean(daily) if enough else None,
            "meanSpyReturn": mean(spy) if enough else None,
            "meanExcessReturn": mean(excess) if enough else None,
            "positiveCohortRate": mean(r > 0 for r in daily) if enough else None,
            "aboveSpyCohortRate": mean(r > 0 for r in excess) if enough else None,
            "belowSpyCohortRate": mean(r < 0 for r in excess) if enough else None}


def report(state, cal):
    all_rows, summaries = [], {}
    observations = state["observations"]
    for h in HORIZONS:
        rows = [outcome(o, q, h, state, cal) for o in observations for q in o["cards"]]
        all_rows.extend(rows)
        # A cohort contributes only when all six displayed cards have endpoints.
        # Never drop just the missing/delisted loser from a day's average.
        complete = {o["basisDate"] for o in observations if len(o["cards"]) == 6 and
                    all(q["status"] == "mature" for q in rows if q["basisDate"] == o["basisDate"])}
        groups = {}
        for side in ("buy", "sell"):
            selected = [q for q in rows if q["basisDate"] in complete and q["side"] == side]
            groups[side] = group_summary(selected, MIN_COHORTS)
            for field in ("selection", "code", "holdingCode"):
                # Include pending subtypes with zero mature counts in the report.
                values = sorted({q[field] for q in rows if q["side"] == side})
                groups[side]["by" + field[0].upper() + field[1:]] = {
                    value: group_summary([q for q in selected if q[field] == value], MIN_COHORTS)
                    for value in values}
        status_counts = {status: sum(q["status"] == status for q in rows) for status in sorted({q["status"] for q in rows})}
        summaries[str(h)] = {"fullyMatureCohorts": len(complete), "observedCohorts": len(observations),
                            "statusCounts": status_counts, "groups": groups}
    tail = state["records"][-1]
    observed = {o["basisDate"] for o in observations}
    at = instant(tail["recordedAt"])
    latest = cal.date_to_session(at.astimezone(cal.tz).date().isoformat(), direction="previous")
    if not completed(session_date(latest), at, cal):
        latest = cal.previous_session(latest)
    missing = [session_date(s) for s in cal.sessions_in_range(observations[0]["basisDate"], latest)
               if session_date(s) not in observed]
    return {"schemaVersion": 1, "studyId": STUDY, "policy": POLICY,
            "generatedAt": tail["recordedAt"], "sequence": tail["sequence"], "ledgerHash": tail["hash"],
            "manifestHash": digest(state["manifest"]), "firstObservedAt": FIRST_OBSERVED_AT,
            "observations": len(observations), "lastBasisDate": observations[-1]["basisDate"],
            "missedRankingDates": missing, "priceRevisionCount": len(state["revisions"]),
            "horizons": summaries, "outcomes": all_rows,
            "researchOnly": True, "performanceValidated": False, "autoPromotion": False,
            "notes": ["Observed homepage priorities, not a trade/account strategy. No costs or dividends.",
                      "Same-date refreshes retain the first observation; weekends add no cohorts.",
                      "Returns begin at the close of the first session opening after actual observation.",
                      "Sell return is subsequent long price return, not simulated short profit or realized savings.",
                      "Daily cohorts overlap and can repeat symbols; counts are not independent observations.",
                      "At least 20 fully mature six-card cohorts per group before aggregate return statistics."]}


def bootstrap(root, now, cal):
    folder = root / FOLDER
    if folder.exists():
        raise ValueError("Study already exists; bootstrap cannot rewrite it")
    commit_at = iso(instant(git(root, "show", "-s", "--format=%cI", FIRST_COMMIT)))
    if commit_at != FIRST_OBSERVED_AT:
        raise ValueError("First operational commit timestamp mismatch")
    home = json.loads(git(root, "show", FIRST_COMMIT + ":market/home.json"))
    forecasts = json.loads(git(root, "show", FIRST_COMMIT + ":forecasts/latest.json"))
    evidence = {"gitCommit": FIRST_COMMIT,
                "homeGitBlob": git(root, "rev-parse", FIRST_COMMIT + ":market/home.json"),
                "forecastsGitBlob": git(root, "rev-parse", FIRST_COMMIT + ":forecasts/latest.json"),
                "observationBasis": "first published operational commit; imported unchanged"}
    item = observation(home, forecasts, FIRST_OBSERVED_AT, evidence, cal)
    manifest = {"schemaVersion": 1, "studyId": STUDY, "policy": POLICY,
                "policyIntroducedAt": POLICY_INTRODUCED_AT, "policyCommit": POLICY_COMMIT,
                "firstOperationalCommit": FIRST_COMMIT, "firstObservedAt": FIRST_OBSERVED_AT,
                "initializedAt": iso(now), "firstBasisDate": item["basisDate"],
                "ruleHashes": rule_hashes(root, FIRST_COMMIT),
                "universe": "contemporaneous homepage eligible stocks; 505 in first snapshot",
                "calendar": {"name": "XNYS", "package": "exchange_calendars", "version": CALENDAR_VERSION,
                             "completionDelayMinutes": 15},
                "horizons": list(HORIZONS), "minimumMatureCohorts": MIN_COHORTS,
                "returnBasis": "Yahoo Close; split-adjusted, dividends excluded; first-observed prices frozen",
                "entry": "first session open strictly after observedAt; anchor at that session close",
                "targets": "anchor session + 20/63 XNYS sessions, exact stock/SPY dates",
                "aggregation": "equal-weight cards within day, equal-weight complete six-card cohort days",
                "sameCloseDate": "first observation only; later refreshes never replace or multiply it",
                "priceRevision": "retain first observed price; quarantine affected outcome windows",
                "safety": {"researchOnly": True, "backfillRankings": False, "liveTrading": False,
                           "changeProduction": False, "autoPromotion": False}}
    state = {"manifest": manifest, "records": [], "observations": [], "prices": {}, "revisions": set()}
    write_exclusive(folder / "manifest.json", manifest)
    append(folder, state, "observation", item, now)
    publish(folder / "latest.json", report(state, cal))
    return state


def update(root, now, cal):
    folder = root / FOLDER
    state = load(folder, cal)
    if rule_hashes(root) != state["manifest"]["ruleHashes"]:
        raise ValueError("Production policy inputs changed; preserve this version, review a new study")
    home, forecasts = read(root / "market/home.json"), read(root / "forecasts/latest.json")
    evidence = source(root)
    reason = capture(folder, state, home, forecasts, now, evidence, cal)
    capture_prices(folder, state, forecasts, now, evidence, cal)
    result = report(state, cal)
    publish(folder / "latest.json", result)
    return reason, result


def verify(root, base, cal):
    if base:
        changed = git(root, "diff", "--name-status", "--no-renames", base, "--", str(FOLDER))
        for row in changed.splitlines():
            status, name = row.split("\t", 1)
            if (name.endswith("/manifest.json") or "/ledger/" in name) and status != "A":
                raise ValueError("Append-only file modified/deleted: " + name)
    state = load(root / FOLDER, cal)
    if read(root / FOLDER / "latest.json") != report(state, cal):
        raise ValueError("Derived report disagrees with ledger")
    return len(state["records"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("bootstrap", "update", "verify"))
    parser.add_argument("--base", help="Git ref for append-only verification")
    args = parser.parse_args()
    cal, now = calendar(), datetime.now(UTC)
    if args.action == "bootstrap":
        state = bootstrap(ROOT, now, cal)
        print("Imported first operational observation", state["observations"][0]["observedAt"])
    elif args.action == "update":
        reason, result = update(ROOT, now, cal)
        print(reason, "cohorts:", result["observations"], "ledger sequence:", result["sequence"])
    else:
        print("Verified", verify(ROOT, args.base, cal), "immutable research records")


if __name__ == "__main__":
    main()
