"""Research-only, bitemporal S&P 500 input boundary (stdlib, no network/model).

An effective date is not an information-availability date. A complete universe
needs a dated baseline AND an attested complete change history; a handful of
press releases never certifies the missing securities. Future removals and
aliases are not fields in an origin cohort. Outcomes are a separate left join.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import math
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "sp500-pit-inputs-v1"
INDEX = "SP500"
DOMAINS = ("membership", "sector", "symbol", "identity", "delisting", "prices")
KINDS = {"membership", "sector", "symbol", "identity", "delisting"}
QUALITIES = {"dated_notice", "certified_point_in_time", "current_only", "synthetic"}
NY = ZoneInfo("America/New_York")


class InputError(ValueError):
    """Invalid, ambiguous, modified or temporally unsafe source data."""


class InputBlocked(InputError):
    def __init__(self, report):
        self.report = report
        super().__init__("PIT input blocked: " + ", ".join(report["blockers"]))


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       allow_nan=False, separators=(",", ":")) + "\n").encode()


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def timestamp(value):
    if not isinstance(value, str):
        raise InputError("Explicit timestamp with timezone required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputError("Invalid timestamp: " + value) from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise InputError("Timestamp must include timezone: " + value)
    return result.astimezone(timezone.utc)


def session_open(day):
    """Cutoff convention, not an exchange calendar or trading-day generator."""
    return datetime.combine(date.fromisoformat(day), time(9, 30), NY).astimezone(timezone.utc)


def conservative_known_at(day):
    """A date-only US notice cannot be used earlier on its publication day."""
    next_day = date.fromisoformat(day) + timedelta(days=1)
    return datetime.combine(next_day, time(), NY).astimezone(timezone.utc).isoformat()


def unique(rows, key):
    out = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or not value or value in out:
            raise InputError("Missing/duplicate " + key)
        out[value] = row
    return out


def finite(value, minimum=0):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= minimum)


class PITInputs:
    """A frozen normalized export; source availability is evidence, not inferred.

    `knownAt` is the original public/provider availability, not the date the
    researcher downloaded it. Sources without that evidence are quarantine only.
    Synthetic fixtures are opt-in and cannot certify the checked-in dataset.
    """

    def __init__(self, data, folder=None, *, allow_synthetic=False):
        self.data = copy.deepcopy(data)
        self.folder = Path(folder).resolve() if folder is not None else None
        self.allow_synthetic = allow_synthetic
        if data.get("schemaVersion") != 1 or data.get("version") != VERSION:
            raise InputError("Unsupported PIT input schema/version")
        for key in ("sources", "securities", "baselines", "events", "coverage", "prices", "outcomes"):
            if not isinstance(data.get(key), list):
                raise InputError("Missing table: " + key)
        self.sources = unique(self.data["sources"], "sourceId")
        self.securities = unique(self.data["securities"], "securityId")
        self.events = unique(self.data["events"], "eventId")
        unique(self.data["baselines"], "baselineId")
        unique(self.data["coverage"], "coverageId")
        self._validate()
        if self.folder is None and any(s["temporalQuality"] != "synthetic" for s in self.sources.values()):
            raise InputError("Real research data requires a verified source-payload folder")
        if self.folder is not None:
            self.verify_payloads()
        self.dataset_hash = sha256(canonical(self.data))

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        return cls(json.loads((folder / "inputs.json").read_text()), folder)

    def _source(self, row, *, administrative=False):
        source = self.sources.get(row.get("sourceId"))
        if source is None:
            raise InputError("Unregistered sourceId")
        quality = source["temporalQuality"]
        if quality == "current_only":
            raise InputError("Current snapshot cannot enter PIT records or coverage")
        if quality == "synthetic" and not self.allow_synthetic:
            raise InputError("Synthetic evidence cannot enter research inputs")
        if not administrative:
            known = timestamp(row.get("knownAt"))
            if known < timestamp(source["availabilityFloor"]):
                raise InputError("knownAt precedes source availability")
            if known > timestamp(source["retrievedAt"]):
                raise InputError("knownAt after frozen retrieval")
            timestamp(row.get("effectiveAt"))
        return source

    def _validate(self):
        for source in self.sources.values():
            if source.get("temporalQuality") not in QUALITIES:
                raise InputError("Unknown temporal quality")
            if source["temporalQuality"] == "synthetic" and not self.allow_synthetic:
                raise InputError("Synthetic evidence cannot enter research inputs")
            if not source.get("uri") or not source.get("availabilityEvidence"):
                raise InputError("Source URI and availability evidence required")
            floor, retrieved = timestamp(source.get("availabilityFloor")), timestamp(source.get("retrievedAt"))
            if floor > retrieved:
                raise InputError("Source availability after retrieval")
            if source["temporalQuality"] == "dated_notice":
                precision = source.get("publicationPrecision")
                if precision == "day":
                    if floor < timestamp(conservative_known_at(source["publicationDate"])):
                        raise InputError("Date-only notice backdated before next local midnight")
                elif precision == "timestamp":
                    if floor < timestamp(source.get("publishedAt")):
                        raise InputError("Source backdated before publication")
                else:
                    raise InputError("Notice publication precision required")
            if source["temporalQuality"] == "certified_point_in_time" and not source.get("availabilityColumn"):
                raise InputError("Provider original availability column required")
            if source["temporalQuality"] == "current_only" and floor < retrieved:
                raise InputError("Current snapshot availability cannot be backdated")
            digest = source.get("sha256")
            if (not source.get("path") or not isinstance(digest, str) or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)):
                raise InputError("Frozen source path and SHA256 required")
        for baseline in self.data["baselines"]:
            self._source(baseline)
            if baseline.get("indexId") != INDEX or baseline.get("completeness") not in {"complete", "partial"}:
                raise InputError("Invalid baseline scope/completeness")
            members = baseline.get("members", [])
            if len(members) != len(set(members)) or not set(members) <= self.securities.keys():
                raise InputError("Duplicate/unknown baseline security")
            if baseline["completeness"] == "complete":
                if not members or baseline.get("expectedSecurityCount") != len(members):
                    raise InputError("Incomplete baseline security count")
                if not baseline.get("coverageEvidence"):
                    raise InputError("Baseline completeness evidence required")
        for event in self.events.values():
            self._source(event)
            if event.get("securityId") not in self.securities or event.get("kind") not in KINDS:
                raise InputError("Unknown event security/kind")
            kind, value = event["kind"], event.get("value")
            if kind == "membership":
                if event.get("indexId") != INDEX or not isinstance(value, bool):
                    raise InputError("Membership event must carry index and boolean")
            elif not isinstance(value, dict):
                raise InputError("Event value must be an object")
            elif kind == "sector":
                if not all(value.get(k) for k in ("name", "taxonomy", "taxonomyVersion")):
                    raise InputError("Dated sector/taxonomy version required")
            elif kind == "symbol":
                if ("symbol" not in value or not value.get("venue")
                        or value["symbol"] is not None and (not isinstance(value["symbol"], str) or not value["symbol"])):
                    raise InputError("Symbol and venue required; symbols are not security IDs")
            elif kind == "identity":
                if not all(value.get(k) for k in ("issuerId", "shareClass")) or value.get("verified") is not True:
                    raise InputError("Verified issuer AND share-class identity required")
            elif kind == "delisting":
                if not value.get("reason") or value.get("settlementStatus") not in {"resolved", "unresolved"}:
                    raise InputError("Delisting settlement must be explicit")
                if value.get("contingentRightsUnresolved") and value["settlementStatus"] == "resolved":
                    raise InputError("Unresolved contingent rights cannot be resolved settlement")
            if event.get("supersedes"):
                previous = self.events.get(event["supersedes"])
                if (previous is None or previous["kind"] != kind
                        or previous["securityId"] != event["securityId"]
                        or timestamp(previous["effectiveAt"]) != timestamp(event["effectiveAt"])
                        or timestamp(previous["knownAt"]) >= timestamp(event["knownAt"])):
                    raise InputError("Invalid event correction chain")
        for coverage in self.data["coverage"]:
            self._source(coverage, administrative=True)
            if (coverage.get("indexId") != INDEX
                    or coverage.get("completeness") not in {"complete", "partial"}
                    or not coverage.get("domains")
                    or not set(coverage.get("domains", [])) <= set(DOMAINS)
                    or timestamp(coverage["from"]) >= timestamp(coverage["throughExclusive"])):
                raise InputError("Invalid coverage attestation")
            if not coverage.get("coverageEvidence"):
                raise InputError("Coverage evidence required; observed rows are not completeness")
            if coverage["completeness"] == "complete":
                quality = self.sources[coverage["sourceId"]]["temporalQuality"]
                if quality not in {"certified_point_in_time", "synthetic"}:
                    raise InputError("Partial notices cannot certify complete history")
                if timestamp(coverage["throughExclusive"]) > timestamp(self.sources[coverage["sourceId"]]["retrievedAt"]):
                    raise InputError("Cannot attest coverage of an unobserved future period")
        price_keys, outcome_keys = set(), set()
        for price in self.data["prices"]:
            self._source(price)
            day = date.fromisoformat(price["sessionDate"])
            if timestamp(price["effectiveAt"]).astimezone(NY).date() != day:
                raise InputError("Price session/effective date mismatch")
            if timestamp(price["knownAt"]) < timestamp(price["effectiveAt"]):
                raise InputError("Price known before observation")
            if price.get("securityId") not in self.securities or not finite(price.get("close"), 0):
                raise InputError("Invalid price observation")
            if price.get("basis") not in {"unadjusted", "point_in_time_adjusted"}:
                raise InputError("Revised current adjusted history cannot enter past features")
            key = (price["securityId"], price["sessionDate"], timestamp(price["knownAt"]))
            if key in price_keys:
                raise InputError("Duplicate price vintage")
            price_keys.add(key)
        for outcome in self.data["outcomes"]:
            self._source(outcome)
            start, end = date.fromisoformat(outcome["origin"]), date.fromisoformat(outcome["targetDate"])
            if (start >= end or outcome.get("securityId") not in self.securities
                    or timestamp(outcome["effectiveAt"]).astimezone(NY).date() != end
                    or timestamp(outcome["knownAt"]) < timestamp(outcome["effectiveAt"])):
                raise InputError("Invalid outcome chronology/security")
            if outcome.get("status") not in {"ready", "missing", "unresolved_delisting"}:
                raise InputError("Explicit outcome status required")
            if outcome["status"] == "ready":
                if (not finite(outcome.get("totalReturnFactor"))
                        or outcome.get("basis") != "total_return_with_distributions_and_delisting"
                        or outcome.get("lifecycleComplete") is not True):
                    raise InputError("Resolved full-lifecycle return required (zero is valid)")
            elif outcome.get("totalReturnFactor") is not None:
                raise InputError("Missing/unresolved outcome cannot claim a numeric return")
            key = (outcome["securityId"], outcome["origin"], outcome["targetDate"], timestamp(outcome["knownAt"]))
            if key in outcome_keys:
                raise InputError("Duplicate outcome vintage")
            outcome_keys.add(key)

    def verify_payloads(self):
        for source in self.sources.values():
            path = (self.folder / source["path"]).resolve()
            if not path.is_relative_to(self.folder) or not path.is_file():
                raise InputError("Frozen source outside bundle/missing: " + source["sourceId"])
            raw = path.read_bytes()
            if sha256(raw) != source["sha256"]:
                raise InputError("Frozen source hash mismatch: " + source["sourceId"])
            if source.get("rawSha256"):
                decoded = gzip.decompress(raw) if source.get("compression") == "gzip" else raw
                if sha256(decoded) != source["rawSha256"]:
                    raise InputError("Raw source hash mismatch")

    def visible_events(self, cutoff, kind=None):
        """Filter knowledge FIRST, then apply only already-known corrections."""
        known = [e for e in self.events.values() if timestamp(e["knownAt"]) < cutoff]
        superseded = {e["supersedes"] for e in known if e.get("supersedes")}
        return [e for e in known if e["eventId"] not in superseded
                and timestamp(e["effectiveAt"]) <= cutoff and (kind is None or e["kind"] == kind)]

    def _latest(self, events, security, kind):
        rows = [e for e in events if e["securityId"] == security and e["kind"] == kind]
        if not rows:
            return None
        last_time = max(timestamp(e["effectiveAt"]) for e in rows)
        latest = [e for e in rows if timestamp(e["effectiveAt"]) == last_time]
        if len(latest) != 1:
            raise InputError("Ambiguous simultaneous " + kind + " for " + security)
        return latest[0]

    def coverage_at(self, cutoff):
        # This is retrospective provenance/coverage, never a predictive feature.
        # A later export may attest completeness, but every feature record still
        # needs its ORIGINAL knownAt. Retrieval/certification is not backdated.
        complete = set()
        for row in self.data["coverage"]:
            if (row["completeness"] == "complete" and timestamp(row["from"]) <= cutoff
                    < timestamp(row["throughExclusive"])):
                complete.update(row["domains"])
        return {domain: domain in complete for domain in DOMAINS}

    def snapshot(self, origin, *, require_complete=True):
        cutoff = session_open(origin)
        events = self.visible_events(cutoff)
        baselines = [b for b in self.data["baselines"]
                     if timestamp(b["knownAt"]) < cutoff and timestamp(b["effectiveAt"]) <= cutoff]
        baseline = None
        if baselines:
            # A later partial list cannot replace a certified full population.
            complete_baselines = [b for b in baselines if b["completeness"] == "complete"]
            baselines = complete_baselines or baselines
            last_time = max(timestamp(b["effectiveAt"]) for b in baselines)
            latest = [b for b in baselines if timestamp(b["effectiveAt"]) == last_time]
            if len(latest) != 1:
                raise InputError("Ambiguous membership baseline")
            baseline = latest[0]
        members = set(baseline["members"]) if baseline else set()
        membership_refs = {s: baseline["baselineId"] for s in members}
        changes = [e for e in events if e["kind"] == "membership" and
                   (baseline is None or timestamp(e["effectiveAt"]) > timestamp(baseline["effectiveAt"]))]
        changes.sort(key=lambda e: (timestamp(e["effectiveAt"]), e["securityId"], e["eventId"]))
        seen_changes, unanchored = set(), []
        for event in changes:
            sid = event["securityId"]
            key = (sid, timestamp(event["effectiveAt"]))
            if key in seen_changes:
                raise InputError("Conflicting simultaneous membership changes")
            seen_changes.add(key)
            if event["value"]:
                if sid in members:
                    unanchored.append(event["eventId"])
                members.add(sid)
                membership_refs[sid] = event["eventId"]
            else:
                if sid not in members:
                    unanchored.append(event["eventId"])
                members.discard(sid)
                membership_refs.pop(sid, None)
        coverage = self.coverage_at(cutoff)
        blockers = ["no_complete_" + k + "_history" for k, complete in coverage.items() if not complete]
        if baseline is None or baseline["completeness"] != "complete":
            blockers.append("no_complete_past_baseline")
        if unanchored:
            blockers.append("unanchored_membership_change")
        rows = []
        for sid in sorted(members):
            current = {k: self._latest(events, sid, k) for k in ("identity", "symbol", "sector", "delisting")}
            identity, symbol, sector = [current[k]["value"] if current[k] else {} for k in ("identity", "symbol", "sector")]
            missing = [k for k in ("identity", "symbol", "sector") if current[k] is None]
            if current["symbol"] and symbol.get("symbol") is None:
                missing.append("symbol")
            if current["delisting"] is not None:
                # Never remove the row to hide an inconsistent feed.
                missing.append("member_after_delisting")
            if not self.past_prices(sid, origin):
                missing.append("prices")
            refs = {"membership": membership_refs[sid]}
            refs.update({k: current[k]["eventId"] for k in ("identity", "symbol", "sector") if current[k]})
            rows.append(dict(securityId=sid, issuerId=identity.get("issuerId"), shareClass=identity.get("shareClass"),
                             symbol=symbol.get("symbol"), venue=symbol.get("venue"), sector=sector.get("name"),
                             taxonomy=sector.get("taxonomy"), taxonomyVersion=sector.get("taxonomyVersion"),
                             provenance=refs, missingInputs=missing))
        if any(row["missingInputs"] for row in rows):
            blockers.append("member_inputs_missing")
        if not rows:
            blockers.append("empty_universe")
        alias_keys = [(r["venue"], r["symbol"]) for r in rows if r["symbol"] is not None]
        if len(set(alias_keys)) != len(alias_keys):
            raise InputError("Ambiguous reused ticker at origin")
        result = dict(version=VERSION, indexId=INDEX, origin=origin, cutoff=cutoff.isoformat(),
                      complete=not blockers, blockers=sorted(set(blockers)), members=rows,
                      securityCount=len(rows), issuerCount=len({r["issuerId"] for r in rows if r["issuerId"]}),
                      coverage=coverage, baselineId=baseline["baselineId"] if baseline else None,
                      unanchoredEvents=sorted(unanchored))
        # Hash only origin-visible cohort rows; future events cannot change this.
        result["cohortHash"] = sha256(canonical(dict(origin=origin, cutoff=result["cutoff"], members=rows)))
        if require_complete and not result["complete"]:
            raise InputBlocked(result)
        return result

    def past_prices(self, security, origin):
        """Stable-security left join with original price vintage, never aliases."""
        cutoff = session_open(origin)
        selected = {}
        for row in self.data["prices"]:
            if (row["securityId"] != security or row["sessionDate"] >= origin
                    or timestamp(row["effectiveAt"]) >= cutoff or timestamp(row["knownAt"]) >= cutoff):
                continue
            old = selected.get(row["sessionDate"])
            if old is None or timestamp(old["knownAt"]) < timestamp(row["knownAt"]):
                selected[row["sessionDate"]] = row
        return [copy.deepcopy(selected[d]) for d in sorted(selected)]

    def security_for_symbol(self, symbol, venue, session_date, knowledge_origin):
        """Resolve a dated alias even for a former member; never current ticker.

        A rename is an alias event on the same security; a merger/spinoff creates
        a different security unless the evidence explicitly proves continuity.
        """
        cutoff = session_open(knowledge_origin)
        effective = session_open(session_date)
        if effective > cutoff:
            raise InputError("Future alias lookup is not an origin input")
        events = [e for e in self.visible_events(cutoff, "symbol") if timestamp(e["effectiveAt"]) <= effective]
        matches = []
        for sid in self.securities:
            alias = self._latest(events, sid, "symbol")
            if alias and alias["value"].get("symbol") == symbol and alias["value"].get("venue") == venue:
                matches.append(sid)
        if len(matches) != 1:
            raise InputError("Unknown/ambiguous dated alias; provide permanent security identity")
        return matches[0]

    def evaluation_ledger(self, cohort, target_date, evaluated_at):
        """Every frozen-origin security survives a LEFT join to future outcomes.

        This function is for labels/audit only, never origin features. Removal
        from SP500 does not truncate the horizon, invent liquidation, carry the
        last close forward or switch to an acquirer's ticker.
        """
        if not cohort.get("complete"):
            raise InputBlocked(cohort)
        expected_hash = sha256(canonical({k: cohort[k] for k in ("origin", "cutoff", "members")}))
        if expected_hash != cohort.get("cohortHash"):
            raise InputError("Frozen cohort was modified")
        end = date.fromisoformat(target_date)
        if end <= date.fromisoformat(cohort["origin"]):
            raise InputError("Outcome target must follow origin")
        asof = timestamp(evaluated_at)
        lifecycle = self.visible_events(asof, "delisting")
        rows = []
        for member in cohort["members"]:
            sid = member["securityId"]
            candidates = [o for o in self.data["outcomes"] if o["securityId"] == sid
                          and o["origin"] == cohort["origin"] and o["targetDate"] == target_date
                          and timestamp(o["knownAt"]) < asof and timestamp(o["effectiveAt"]) < asof]
            label = max(candidates, key=lambda o: timestamp(o["knownAt"])) if candidates else None
            terminated = [e for e in lifecycle if e["securityId"] == sid and
                          session_open(cohort["origin"]) < timestamp(e["effectiveAt"])
                          and timestamp(e["effectiveAt"]).astimezone(NY).date() <= end]
            unresolved = any(e["value"]["settlementStatus"] == "unresolved" for e in terminated)
            # Without an exchange-calendar target timestamp, a date-only label
            # remains pending through that local day; observed labels can still
            # become ready once their explicit knownAt has strictly passed.
            status = "pending_outcome" if asof.astimezone(NY).date() <= end else "missing_outcome"
            if label is not None:
                status = "ready" if label["status"] == "ready" else label["status"]
            if unresolved:
                status = "unresolved_delisting"
            rows.append(dict(securityId=sid, origin=cohort["origin"], targetDate=target_date,
                             originSymbol=member["symbol"], originSector=member["sector"],
                             status=status, totalReturnFactor=label.get("totalReturnFactor") if status == "ready" else None,
                             sourceId=label["sourceId"] if label else None,
                             delistingEvents=sorted(e["eventId"] for e in terminated)))
        assert_evaluation_population(cohort, rows)
        statuses = dict(sorted(Counter(r["status"] for r in rows).items()))
        total = len(rows)
        missing = total - statuses.get("ready", 0)
        return dict(version=VERSION, cohortHash=cohort["cohortHash"], rows=rows,
                    originPopulation=total, retainedPopulation=total, unresolvedRows=missing,
                    evaluable=missing == 0, statuses=statuses,
                    numericMetricsAllowed=missing == 0 and all(r["totalReturnFactor"] > 0 for r in rows),
                    policy="No incomplete-cohort metric; zero terminal wealth retained, ratio metrics undefined")


def assert_evaluation_population(cohort, rows):
    expected = {r["securityId"] for r in cohort["members"]}
    actual = [r["securityId"] for r in rows]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise InputError("Survivorship/population mismatch (missing, duplicate or unexpected security)")
    if any(r["origin"] != cohort["origin"] for r in rows):
        raise InputError("Outcome row origin mismatch")


def write_frozen(path, value):
    """A rerun may verify identical bytes; different data requires a NEW bundle."""
    path = Path(path)
    raw = canonical(value)
    if path.exists():
        if path.read_bytes() != raw:
            raise InputError("Refusing to overwrite frozen artifact: " + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
