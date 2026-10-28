"""Leakage, lost-security, provenance and fail-closed boundary regressions.

All model-independent examples in this file are SYNTHETIC. Real official
notices are separately checked; they are not a certified historical universe.
"""

import copy
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pit_sp500_inputs import (INDEX, VERSION, DOMAINS, InputBlocked, InputError, PITInputs,
                             assert_evaluation_population, canonical, conservative_known_at,
                             session_open, sha256, write_frozen)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "research/joint-indicator/pit-inputs-v1"
BASE = "2019-01-01T14:30:00Z"
ORIGIN = "2020-01-02"


def event(eid, sid, kind, value, effective=BASE, known="2018-12-31T00:00:00Z", **extra):
    return dict(eventId=eid, securityId=sid, kind=kind, value=value, effectiveAt=effective,
                knownAt=known, sourceId="fixture", **({"indexId": INDEX} if kind == "membership" else {}), **extra)


def sector(name):
    return dict(name=name, taxonomy="GICS", taxonomyVersion="fixture-2018")


def fixture():
    """Three securities, two issuers; one ordinary exit later in the horizon."""
    securities = [dict(securityId=s) for s in ("issuer-1-A", "issuer-1-C", "issuer-2-common")]
    events, prices = [], []
    for n, security in enumerate(securities):
        sid = security["securityId"]
        events.extend([
            event(sid + "-identity", sid, "identity", dict(issuerId="issuer-1" if n < 2 else "issuer-2",
                                                         shareClass=["A", "C", "common"][n], verified=True)),
            event(sid + "-alias", sid, "symbol", dict(symbol=["AAA", "AAC", "EXIT"][n], venue="NYSE")),
            event(sid + "-sector", sid, "sector", sector("Information Technology"))])
        prices.append(dict(securityId=sid, sessionDate="2019-12-31", effectiveAt="2019-12-31T21:00:00Z",
                           knownAt="2020-01-01T00:00:00Z", sourceId="fixture", close=100 + n,
                           basis="point_in_time_adjusted"))
    return dict(schemaVersion=1, version=VERSION, datasetId="synthetic-tests-only",
                sources=[dict(sourceId="fixture", uri="fixture://not-market-data", path="fixture.json",
                              sha256="a" * 64, availabilityFloor="2000-01-01T00:00:00Z",
                              retrievedAt="2026-10-07T04:00:00Z", temporalQuality="synthetic",
                              availabilityEvidence="Synthetic chronology, never real research data")],
                securities=securities, events=events,
                baselines=[dict(baselineId="baseline", sourceId="fixture", effectiveAt=BASE,
                                knownAt="2018-12-31T00:00:00Z", indexId=INDEX, completeness="complete",
                                members=[s["securityId"] for s in securities], expectedSecurityCount=3,
                                coverageEvidence="Synthetic complete three-security universe")],
                coverage=[dict(coverageId="history", sourceId="fixture", indexId=INDEX,
                               **{"from": BASE}, throughExclusive="2026-10-07T00:00:00Z",
                               domains=list(DOMAINS), completeness="complete", coverageEvidence="Synthetic all-events fixture")],
                prices=prices, outcomes=[])


def inputs(data=None):
    return PITInputs(data or fixture(), allow_synthetic=True)


def outcome(sid, ratio=1.1, **updates):
    row = dict(securityId=sid, origin=ORIGIN, targetDate="2020-12-31",
               effectiveAt="2020-12-31T21:00:00Z", knownAt="2021-01-01T00:00:00Z", sourceId="fixture",
               status="ready", totalReturnFactor=ratio, basis="total_return_with_distributions_and_delisting",
               lifecycleComplete=True)
    row.update(updates)
    return row


class PITBoundaryTests(unittest.TestCase):
    def test_announced_future_addition_not_member_until_effective(self):
        data = fixture()
        data["securities"].append(dict(securityId="new-security"))
        data["events"].append(event("new-member", "new-security", "membership", True,
                                    effective="2020-06-01T13:30:00Z", known="2019-12-01T00:00:00Z"))
        self.assertEqual(inputs().snapshot(ORIGIN)["members"], inputs(data).snapshot(ORIGIN)["members"])
        later = inputs(data).snapshot("2020-06-01", require_complete=False)
        self.assertIn("new-security", [r["securityId"] for r in later["members"]])
        self.assertIn("member_inputs_missing", later["blockers"])

    def test_future_membership_cannot_change_origin_rows_or_fingerprint(self):
        data = fixture()
        data["events"].append(event("future-exit", "issuer-2-common", "membership", False,
                                    effective="2020-06-01T13:30:00Z", known="2020-05-29T00:00:00Z"))
        before, after = inputs().snapshot(ORIGIN), inputs(data).snapshot(ORIGIN)
        self.assertEqual(before["members"], after["members"])
        self.assertEqual(before["cohortHash"], after["cohortHash"])
        self.assertNotIn("endDate", json.dumps(after["members"]))
        self.assertEqual(inputs(data).snapshot("2020-06-01")["securityCount"], 2)

    def test_effective_past_but_not_yet_known_does_not_rewrite_origin(self):
        data = fixture()
        data["events"].append(event("late-exit", "issuer-2-common", "membership", False,
                                    effective="2020-01-01T14:30:00Z", known="2020-01-03T00:00:00Z"))
        self.assertEqual(inputs(data).snapshot(ORIGIN)["securityCount"], 3)
        self.assertEqual(inputs(data).snapshot("2020-01-03")["securityCount"], 2)

    def test_cutoff_known_equality_excluded_but_effective_equality_included(self):
        data = fixture()
        boundary = session_open(ORIGIN).isoformat()
        data["events"].append(event("boundary-exit", "issuer-2-common", "membership", False,
                                    effective=boundary, known=boundary))
        self.assertEqual(inputs(data).snapshot(ORIGIN)["securityCount"], 3)
        data["events"][-1]["knownAt"] = "2020-01-01T00:00:00Z"
        self.assertEqual(inputs(data).snapshot(ORIGIN)["securityCount"], 2)

    def test_sector_transition_not_backfilled_from_current_identity(self):
        data = fixture()
        data["events"].append(event("sector-change", "issuer-1-A", "sector", sector("Communication Services"),
                                    effective="2020-06-01T13:30:00Z", known="2020-05-29T00:00:00Z"))
        self.assertEqual(inputs(data).snapshot(ORIGIN)["members"][0]["sector"], "Information Technology")
        self.assertEqual(inputs(data).snapshot("2020-06-01")["members"][0]["sector"], "Communication Services")

    def test_later_correction_only_applies_after_its_own_availability(self):
        data = fixture()
        old = "issuer-1-A-sector"
        data["events"].append(event("corrected-sector", "issuer-1-A", "sector", sector("Financials"),
                                    effective=BASE, known="2020-02-01T00:00:00Z", supersedes=old))
        self.assertEqual(inputs().snapshot(ORIGIN)["cohortHash"], inputs(data).snapshot(ORIGIN)["cohortHash"])
        self.assertEqual(inputs(data).snapshot("2020-02-03")["members"][0]["sector"], "Financials")
        data["events"][-1]["supersedes"] = "unknown"
        with self.assertRaisesRegex(InputError, "correction"):
            inputs(data)

    def test_issuer_does_not_collapse_two_share_classes(self):
        snapshot = inputs().snapshot(ORIGIN)
        self.assertEqual(snapshot["securityCount"], 3)
        self.assertEqual(snapshot["issuerCount"], 2)
        self.assertEqual({r["shareClass"] for r in snapshot["members"][:2]}, {"A", "C"})

    def test_ticker_rename_retains_permanent_security_and_dated_aliases(self):
        data = fixture()
        data["events"].append(event("rename", "issuer-2-common", "symbol", dict(symbol="NEW", venue="NYSE"),
                                    effective="2020-06-01T13:30:00Z", known="2020-05-29T00:00:00Z"))
        pit = inputs(data)
        self.assertEqual(pit.snapshot(ORIGIN)["members"][-1]["symbol"], "EXIT")
        self.assertEqual(pit.snapshot("2020-06-01")["members"][-1]["symbol"], "NEW")
        self.assertEqual(pit.security_for_symbol("EXIT", "NYSE", ORIGIN, "2020-06-01"), "issuer-2-common")
        self.assertEqual(pit.security_for_symbol("NEW", "NYSE", "2020-06-01", "2020-06-01"), "issuer-2-common")
        with self.assertRaisesRegex(InputError, "Unknown/ambiguous"):
            pit.security_for_symbol("NEW", "NYSE", ORIGIN, "2020-06-01")

    def test_reused_ticker_does_not_splice_two_securities(self):
        data = fixture()
        data["events"].extend([
            event("retire-alias", "issuer-2-common", "symbol", dict(symbol=None, venue="NYSE"),
                  effective="2020-06-01T13:30:00Z", known="2020-05-29T00:00:00Z"),
            event("reuse-alias", "issuer-1-A", "symbol", dict(symbol="EXIT", venue="NYSE"),
                  effective="2020-06-01T13:30:00Z", known="2020-05-29T00:00:00Z")])
        pit = inputs(data)
        self.assertEqual(pit.security_for_symbol("EXIT", "NYSE", ORIGIN, "2020-06-01"), "issuer-2-common")
        self.assertEqual(pit.security_for_symbol("EXIT", "NYSE", "2020-06-01", "2020-06-01"), "issuer-1-A")
        data["events"] = [e for e in data["events"] if e["eventId"] != "retire-alias"]
        with self.assertRaisesRegex(InputError, "Ambiguous reused ticker"):
            inputs(data).snapshot("2020-06-01")

    def test_missing_member_price_is_retained_and_export_blocked(self):
        data = fixture()
        data["prices"] = data["prices"][:2]
        pit = inputs(data)
        with self.assertRaises(InputBlocked):
            pit.snapshot(ORIGIN)
        audit = pit.snapshot(ORIGIN, require_complete=False)
        self.assertEqual(audit["securityCount"], 3)
        self.assertIn("prices", audit["members"][-1]["missingInputs"])

    def test_current_snapshot_never_accepted_as_historical_membership_or_sector(self):
        data = fixture()
        data["sources"][0].update(temporalQuality="current_only", availabilityFloor="2026-10-07T04:00:00Z")
        with self.assertRaisesRegex(InputError, "Current snapshot"):
            inputs(data)
        data["sources"][0]["availabilityFloor"] = "2000-01-01T00:00:00Z"
        with self.assertRaisesRegex(InputError, "backdated"):
            inputs(data)

    def test_publication_clock_and_date_only_precision_are_enforced(self):
        self.assertEqual(conservative_known_at("2024-09-06"), "2024-09-07T04:00:00+00:00")
        self.assertEqual(conservative_known_at("2025-01-09"), "2025-01-10T05:00:00+00:00")
        data = fixture()
        data["sources"][0].update(temporalQuality="dated_notice", publicationPrecision="day",
                                  publicationDate="2024-09-06", availabilityFloor="2024-09-06T00:00:00Z")
        with self.assertRaisesRegex(InputError, "Date-only"):
            inputs(data)

    def test_record_cannot_precede_source_availability_or_follow_retrieval(self):
        data = fixture()
        data["sources"][0]["availabilityFloor"] = "2020-01-01T00:00:00Z"
        with self.assertRaisesRegex(InputError, "precedes source"):
            inputs(data)
        data = fixture()
        data["events"][0]["knownAt"] = "2027-01-01T00:00:00Z"
        with self.assertRaisesRegex(InputError, "after frozen retrieval"):
            inputs(data)

    def test_naive_timestamps_and_legacy_universe_are_rejected(self):
        data = fixture()
        data["events"][0]["knownAt"] = "2018-12-31"
        with self.assertRaisesRegex(InputError, "timezone"):
            inputs(data)
        with self.assertRaisesRegex(InputError, "schema"):
            PITInputs(json.loads((ROOT / "research/joint-indicator/relative-v1/sources/universe.json").read_text()))

    def test_complete_baseline_does_not_prove_complete_change_history(self):
        data = fixture()
        data["coverage"] = []
        with self.assertRaises(InputBlocked) as error:
            inputs(data).snapshot(ORIGIN)
        self.assertIn("no_complete_membership_history", error.exception.report["blockers"])
        self.assertEqual(error.exception.report["securityCount"], 3)

    def test_partial_baseline_does_not_displace_full_past_population(self):
        data = fixture()
        partial = copy.deepcopy(data["baselines"][0])
        partial.update(baselineId="partial", completeness="partial", effectiveAt="2020-01-01T00:00:00Z",
                       knownAt="2020-01-01T00:00:00Z", members=["issuer-1-A"])
        data["baselines"].append(partial)
        self.assertEqual(inputs(data).snapshot(ORIGIN)["securityCount"], 3)
        data["baselines"] = [partial]
        with self.assertRaises(InputBlocked):
            inputs(data).snapshot(ORIGIN)

    def test_incomplete_baseline_count_and_duplicate_membership_cannot_pass(self):
        data = fixture()
        data["baselines"][0]["expectedSecurityCount"] = 4
        with self.assertRaisesRegex(InputError, "Incomplete baseline"):
            inputs(data)
        data = fixture()
        for n in range(2):
            data["events"].append(event("exit-" + str(n), "issuer-2-common", "membership", False,
                                        effective="2020-01-01T00:00:00Z", known="2019-12-30T00:00:00Z"))
        with self.assertRaisesRegex(InputError, "Conflicting simultaneous"):
            inputs(data).snapshot(ORIGIN)

    def test_future_period_cannot_be_certified_as_already_observed(self):
        data = fixture()
        data["coverage"][0]["throughExclusive"] = "2030-01-01T00:00:00Z"
        with self.assertRaisesRegex(InputError, "unobserved future"):
            inputs(data)

    def test_price_revisions_and_origin_or_future_prices_never_leak(self):
        data = fixture()
        original = inputs(data).past_prices("issuer-1-A", ORIGIN)
        revision = copy.deepcopy(data["prices"][0])
        revision.update(close=999999, knownAt="2020-02-01T00:00:00Z")
        data["prices"].append(revision)
        future = copy.deepcopy(revision)
        future.update(sessionDate=ORIGIN, effectiveAt="2020-01-02T21:00:00Z", knownAt="2020-01-02T21:01:00Z")
        data["prices"].append(future)
        self.assertEqual(inputs(data).past_prices("issuer-1-A", ORIGIN), original)
        data["prices"][-1]["basis"] = "revised_current_adjusted"
        with self.assertRaisesRegex(InputError, "Revised current"):
            inputs(data)

    def test_removed_member_stays_in_horizon_ledger_even_if_future_return_missing(self):
        data = fixture()
        cohort = inputs(data).snapshot(ORIGIN)
        data["events"].append(event("exit", "issuer-2-common", "membership", False,
                                    effective="2020-06-01T13:30:00Z", known="2020-05-29T00:00:00Z"))
        data["outcomes"] = [outcome("issuer-1-A"), outcome("issuer-1-C")]
        pit = inputs(data)
        self.assertEqual(pit.snapshot("2020-06-01")["securityCount"], 2)
        ledger = pit.evaluation_ledger(cohort, "2020-12-31", "2021-01-02T00:00:00Z")
        self.assertEqual(ledger["originPopulation"], ledger["retainedPopulation"])
        self.assertEqual(ledger["retainedPopulation"], 3)
        self.assertEqual(ledger["rows"][-1]["status"], "missing_outcome")
        self.assertFalse(ledger["evaluable"])
        self.assertFalse(ledger["numericMetricsAllowed"])

    def test_zero_terminal_wealth_is_retained_without_price_or_log_metric_floor(self):
        data = fixture()
        data["outcomes"] = [outcome(s["securityId"], 0 if n == 2 else 1.1) for n, s in enumerate(data["securities"])]
        pit = inputs(data)
        ledger = pit.evaluation_ledger(pit.snapshot(ORIGIN), "2020-12-31", "2021-01-02T00:00:00Z")
        self.assertTrue(ledger["evaluable"])
        self.assertEqual(ledger["rows"][-1]["totalReturnFactor"], 0)
        self.assertFalse(ledger["numericMetricsAllowed"])

    def test_unresolved_delisting_or_contingent_rights_blocks_even_supplied_return(self):
        data = fixture()
        cohort = inputs(data).snapshot(ORIGIN)
        data["events"].extend([
            event("remove-exit", "issuer-2-common", "membership", False,
                  effective="2020-06-01T13:30:00Z", known="2020-05-29T00:00:00Z"),
            event("delist", "issuer-2-common", "delisting",
                  dict(reason="acquired", settlementStatus="unresolved", contingentRightsUnresolved=True),
                  effective="2020-06-01T20:00:00Z", known="2020-06-02T00:00:00Z")])
        data["outcomes"] = [outcome(s["securityId"]) for s in data["securities"]]
        ledger = inputs(data).evaluation_ledger(cohort, "2020-12-31", "2021-01-02T00:00:00Z")
        self.assertEqual(ledger["rows"][-1]["status"], "unresolved_delisting")
        self.assertIsNone(ledger["rows"][-1]["totalReturnFactor"])
        self.assertFalse(ledger["evaluable"])

    def test_pending_future_label_is_not_used_and_cannot_change_input_hash(self):
        data = fixture()
        before = inputs(data).snapshot(ORIGIN)
        data["outcomes"] = [outcome(s["securityId"], 999) for s in data["securities"]]
        pit = inputs(data)
        self.assertEqual(before["cohortHash"], pit.snapshot(ORIGIN)["cohortHash"])
        ledger = pit.evaluation_ledger(before, "2020-12-31", "2020-06-02T00:00:00Z")
        self.assertEqual(ledger["statuses"], {"pending_outcome": 3})
        self.assertTrue(all(r["totalReturnFactor"] is None for r in ledger["rows"]))

    def test_population_validator_catches_drop_duplicate_and_wrong_security(self):
        cohort = inputs().snapshot(ORIGIN)
        rows = [dict(securityId=r["securityId"], origin=ORIGIN) for r in cohort["members"]]
        for bad in (rows[:2], rows + rows[:1], rows[:2] + [dict(securityId="other", origin=ORIGIN)]):
            with self.assertRaisesRegex(InputError, "Survivorship/population"):
                assert_evaluation_population(cohort, bad)
        rows[-1]["origin"] = "2020-01-03"
        with self.assertRaisesRegex(InputError, "origin mismatch"):
            assert_evaluation_population(cohort, rows)

    def test_modified_cohort_cannot_be_used_as_smaller_evaluation_population(self):
        pit = inputs()
        cohort = pit.snapshot(ORIGIN)
        cohort["members"] = cohort["members"][:2]
        with self.assertRaisesRegex(InputError, "Frozen cohort was modified"):
            pit.evaluation_ledger(cohort, "2020-12-31", "2021-01-02T00:00:00Z")

    def test_numeric_outcome_requires_full_lifecycle_not_last_available_close(self):
        data = fixture()
        data["outcomes"] = [outcome("issuer-2-common", lifecycleComplete=False)]
        with self.assertRaisesRegex(InputError, "full-lifecycle"):
            inputs(data)
        data["outcomes"] = [outcome("issuer-2-common", status="missing")]
        with self.assertRaisesRegex(InputError, "cannot claim a numeric"):
            inputs(data)

    def test_order_independent_cohort_and_frozen_write_never_overwrites(self):
        data = fixture()
        expected = inputs(data).snapshot(ORIGIN)
        random.Random(41).shuffle(data["events"])
        data["securities"].reverse()
        self.assertEqual(expected, inputs(data).snapshot(ORIGIN))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frozen.json"
            write_frozen(path, expected)
            write_frozen(path, expected)
            with self.assertRaisesRegex(InputError, "Refusing to overwrite"):
                write_frozen(path, {"replacement": True})

    def test_payload_hash_and_path_traversal_cannot_pass(self):
        data = fixture()
        raw = canonical({"synthetic": True})
        data["sources"][0]["sha256"] = sha256(raw)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "fixture.json").write_bytes(raw)
            PITInputs(data, folder, allow_synthetic=True)
            (folder / "fixture.json").write_bytes(b"tampered")
            with self.assertRaisesRegex(InputError, "hash mismatch"):
                PITInputs(data, folder, allow_synthetic=True)
            data["sources"][0]["path"] = "../fixture.json"
            with self.assertRaisesRegex(InputError, "outside bundle"):
                PITInputs(data, folder, allow_synthetic=True)

    def test_synthetic_population_cannot_be_promoted_as_real_research_evidence(self):
        with self.assertRaisesRegex(InputError, "Synthetic evidence"):
            PITInputs(fixture())

    def test_official_notice_partial_inputs_remain_blocked_for_all_legacy_origins(self):
        from build_pit_sp500_inputs import audit_bundle
        report, _ = audit_bundle()
        self.assertEqual(report["originCount"], 34)
        self.assertEqual(report["readyOriginCount"], 0)
        self.assertFalse(report["fullHistoricalCoverage"])
        self.assertFalse(report["modelTrainingAllowed"])
        self.assertEqual(report["sourceSummary"]["completeCoverageAttestations"], 0)
        self.assertTrue(all(not r["complete"] for r in report["requests"]))

    def test_real_addition_and_block_rename_use_both_clocks(self):
        pit = PITInputs.load(BUNDLE)
        before = pit.snapshot("2024-09-20", require_complete=False)
        after = pit.snapshot("2024-09-23", require_complete=False)
        self.assertNotIn("PLTR", [r["symbol"] for r in before["members"]])
        self.assertIn("PLTR", [r["symbol"] for r in after["members"]])
        old = pit.security_for_symbol("SQ", "NYSE", "2025-01-10", "2025-01-21")
        new = pit.security_for_symbol("XYZ", "NYSE", "2025-01-21", "2025-01-21")
        self.assertEqual(old, new)
        with self.assertRaisesRegex(InputError, "Unknown/ambiguous"):
            pit.security_for_symbol("XYZ", "NYSE", "2025-01-10", "2025-01-21")

    def test_frozen_audit_replays_and_missing_data_export_fails_without_writing(self):
        verify = subprocess.run([sys.executable, str(ROOT / "scripts/build_pit_sp500_inputs.py"), "--verify"],
                                text=True, capture_output=True)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        before = (BUNDLE / "coverage-audit.json").read_bytes()
        export = subprocess.run([sys.executable, str(ROOT / "scripts/build_pit_sp500_inputs.py"), "--export-cohorts"],
                                text=True, capture_output=True)
        self.assertEqual(export.returncode, 2, export.stdout + export.stderr)
        self.assertIn("PIT input blocked", export.stdout)
        self.assertFalse((BUNDLE / "origin-cohorts.json").exists())
        self.assertEqual((BUNDLE / "coverage-audit.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
