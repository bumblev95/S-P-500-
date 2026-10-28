"""Quarantine regressions: clocks, ambiguous tickers, evidence and immutability."""

import copy
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import audit_fja_sp500_quarantine as q
from pit_sp500_inputs import InputError, PITInputs, canonical


def history(text="2020-01-01,AAA\n2020-01-10,BBB\n2020-01-20,BBB\n"):
    return q.parse_history(("date,tickers\n" + text).encode())


def candidate(day="2020-01-10", ticker="BBB", action="add"):
    return dict(candidateId="candidate", effectiveDateCandidate=day, ticker=ticker, action=action)


def official(day="2020-01-10", ticker="BBB", action="add", event_id="notice"):
    return dict(eventId=event_id, date=day, ticker=ticker, action=action,
        knownAt="2020-01-09T05:00:00+00:00", effectiveAt=day+"T14:30:00+00:00",
        securityId="provisional", sourceId="official", evidenceLocator="table row")


class ParsingTests(unittest.TestCase):
    def test_quoted_multi_ticker_and_class_punctuation_remain_distinct(self):
        rows = history('2020-01-01,"BRK.B,BRK-B,AAA-200001"\n')
        self.assertEqual(rows[0]["tickers"], ["AAA-200001","BRK-B","BRK.B"])
        self.assertEqual(rows[0]["locator"]["csvRecord"], 2)

    def test_duplicate_ticker_is_not_silently_deduplicated(self):
        with self.assertRaises(InputError): history('2020-01-01,"AAA,AAA"\n')

    def test_duplicate_and_reversed_dates_fail(self):
        for body in ("2020-01-01,AAA\n2020-01-01,BBB\n", "2020-01-02,AAA\n2020-01-01,BBB\n"):
            with self.subTest(body=body), self.assertRaises(InputError): history(body)

    def test_bad_header_or_ragged_csv_fails(self):
        for raw in (b"day,tickers\n2020-01-01,AAA\n",b"date,tickers\n2020-01-01,AAA,BBB\n"):
            with self.subTest(raw=raw), self.assertRaises(InputError): q.parse_history(raw)

    def test_missing_or_whitespace_ticker_fails(self):
        for value in ("", " AAA", "AAA,", "AAA, BBB"):
            with self.subTest(value=value), self.assertRaises(InputError): q.symbols(value)

    def test_empty_add_or_remove_allowed_but_contradiction_is_not(self):
        rows=q.parse_changes(b'date,add,remove\n2020-01-01,AAA,\n2020-01-02,,BBB\n')
        self.assertEqual(rows[0]["remove"],[])
        for raw in (b'date,add,remove\n2020-01-01,AAA,AAA\n', b'date,add,remove\n2020-01-01,,\n'):
            with self.assertRaises(InputError):q.parse_changes(raw)

    def test_interval_end_is_exclusive_and_open_end_is_censored(self):
        rows=q.parse_intervals(b'ticker,start_date,end_date\nAAA,2020-01-01,2020-01-10\nBBB,2020-01-10,\n')
        self.assertEqual(q.interval_members(rows,"2020-01-10","2020-01-01","2020-01-20"),["BBB"])
        self.assertIsNone(q.interval_members(rows,"2020-01-21","2020-01-01","2020-01-20"))

    def test_reentry_intervals_do_not_become_permanent_identity(self):
        rows=q.parse_intervals(b'ticker,start_date,end_date\nAAA,2020-01-01,2020-01-10\nAAA,2020-01-20,\n')
        self.assertEqual(len(rows),2)
        self.assertEqual(q.interval_members(rows,"2020-01-15","2020-01-01","2020-01-25"),[])
        self.assertTrue(all("securityId" not in r for r in rows))

    def test_overlapping_duplicate_and_zero_length_intervals_fail(self):
        for body in ("AAA,2020-01-01,\nAAA,2020-01-20,\n", "AAA,2020-01-01,2020-01-01\n",
                     "AAA,2020-01-01,2020-01-20\nAAA,2020-01-10,2020-01-30\n"):
            with self.subTest(body=body), self.assertRaises(InputError):
                q.parse_intervals(("ticker,start_date,end_date\n"+body).encode())

    def test_asof_never_uses_future_row_or_extrapolates_beyond_payload(self):
        rows=history()
        self.assertEqual(q.snapshot_at(rows,"2020-01-09")["tickers"],["AAA"])
        self.assertIsNone(q.snapshot_at(rows,"2019-12-31"))
        self.assertIsNone(q.snapshot_at(rows,"2020-01-21"))

    def test_left_censored_baseline_and_open_end_are_not_changes(self):
        rows=history()
        intervals=q.parse_intervals(b'ticker,start_date,end_date\nAAA,2020-01-01,2020-01-10\nBBB,2020-01-10,\n')
        events=q.candidate_events(rows,[],intervals)
        self.assertEqual({(r["ticker"],r["action"]) for r in events},{("AAA","remove"),("BBB","add")})
        self.assertTrue(all(r["historicalKnownAt"] is None and r["securityId"] is None for r in events))


class ComparisonTests(unittest.TestCase):
    def test_match_requires_exact_ticker_action_and_effective_day(self):
        self.assertEqual(q.compare_event(candidate(),[official()])["status"],"match")
        self.assertEqual(q.compare_event(candidate(ticker="BRK-B"),[official(ticker="BRK.B")])["status"],"unconfirmed")

    def test_opposite_action_is_conflict(self):
        self.assertEqual(q.compare_event(candidate(action="remove"),[official()])["status"],"conflict")

    def test_near_date_discrepancy_is_explicit_conflict_not_a_fuzzy_match(self):
        self.assertEqual(q.compare_event(candidate(day="2020-01-11"),[official()])["status"],"conflict")

    def test_distant_reentry_and_missing_official_evidence_are_unconfirmed(self):
        self.assertEqual(q.compare_event(candidate(day="2020-02-11"),[official()])["status"],"unconfirmed")
        self.assertEqual(q.compare_event(candidate(),[])["status"],"unconfirmed")

    def test_exact_match_cannot_hide_a_conflicting_notice(self):
        result=q.compare_event(candidate(),[official(),official(action="remove",event_id="conflicting")])
        self.assertEqual(result["status"],"conflict")
        self.assertEqual(result["matchedOfficialEventIds"],["notice"])

    def test_notice_missing_in_source_remains_unconfirmed(self):
        self.assertEqual(q.reconcile_official([official()],[])[0]["status"],"unconfirmed")

    def test_ambiguous_official_alias_is_not_guessed(self):
        member=dict(eventId="m",kind="membership",sourceId="s",securityId="id",value=True,
                    knownAt="2020-01-01T00:00:00Z",effectiveAt="2020-01-02T14:30:00Z",evidenceLocator="row")
        aliases=[dict(member,eventId=t,kind="symbol",value=dict(symbol=t,venue="N")) for t in ("AAA","BBB")]
        self.assertIsNone(q.official_membership(dict(events=[member]+aliases))[0]["ticker"])

    def test_future_alias_cannot_resolve_earlier_notice(self):
        member=dict(eventId="m",kind="membership",sourceId="s",securityId="id",value=True,
                    knownAt="2020-01-01T00:00:00Z",effectiveAt="2020-01-02T14:30:00Z",evidenceLocator="row")
        alias=dict(member,eventId="a",kind="symbol",value=dict(symbol="BBB",venue="N"),knownAt="2020-01-03T00:00:00Z")
        self.assertIsNone(q.official_membership(dict(events=[member,alias]))[0]["ticker"])

    def test_per_origin_excludes_late_publication_and_future_effective_notice(self):
        requests=[dict(origin="2020-01-10")]
        reference=dict(requests=[dict(request=requests[0],complete=False,blockers=["reference_blocked"])])
        late=official(event_id="late"); late["knownAt"]="2020-01-10T14:30:00Z"
        future=official(day="2020-01-11",event_id="future")
        changes=[dict(date="2020-01-01"),dict(date="2020-01-20")]
        result=q.origin_audit(requests,history(),[],[],[late,future],reference,changes)[0]
        self.assertEqual(result["officialBaselineComparison"],[])
        self.assertFalse(result["ready"])
        self.assertTrue(result["candidateBaseline"]["sameDayTimingUnverified"])

    def test_mismatching_cross_files_are_reported_not_repaired(self):
        updated=history()
        original=history("2020-01-01,AAA\n")
        changes=[dict(date="2020-01-10",add=["WRONG"],remove=["AAA"],locator={})]
        result=q.consistency_audit(updated,original,changes,[])
        self.assertTrue(any(r["kind"]=="explicit_change_vs_snapshot_delta" for r in result["discrepancies"]))
        self.assertTrue(result["intervalExpectedOnly"])


class FrozenIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report,cls.observations=q.build_audit()

    def clone(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        dest=Path(temp.name)/"bundle";shutil.copytree(q.FOLDER,dest)
        return dest

    def test_all_34_origins_remain_blocked_despite_candidate_baselines(self):
        report=self.report
        self.assertEqual((report["originCount"],report["readyOriginCount"],report["unchangedPITReadyOriginCount"]),(34,0,0))
        self.assertEqual(report["sourceSummary"]["candidateBaselineOrigins"],34)
        for row in report["origins"]:
            self.assertFalse(row["ready"])
            self.assertFalse(row["trustedBaseline"])
            self.assertTrue(set(q.BLOCKERS)<=set(row["blockers"]))
            self.assertTrue(row["preservedReferenceBlockers"])
        self.assertFalse(report["modelTrainingAllowed"])
        self.assertFalse(report["productionChangesAllowed"])

    def test_partition_keeps_every_candidate_including_unconfirmed(self):
        report=self.report
        self.assertEqual(report["officialMembershipComparisonCounts"],dict(match=8,conflict=0,unconfirmed=0))
        self.assertEqual(report["candidateComparisonCounts"],dict(match=8,conflict=0,unconfirmed=1526))
        partitions=report["candidateComparisonPartitions"]
        ids=[item for group in partitions.values() for item in group]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(set(ids),{e["candidateId"] for e in self.observations["events"]})

    def test_unsupported_notice_domains_and_wba_remain_unconfirmed(self):
        facts=self.report["unsupportedOfficialFacts"]
        self.assertEqual(len(facts),20)
        self.assertTrue(all(e["status"]=="unconfirmed" for e in facts))
        self.assertTrue(any(e["eventId"]=="wba-trading-ceased" for e in facts))
        self.assertEqual(self.report["sourceSummary"]["outcomeRows"],0)

    def test_independent_completeness_never_inferred_from_three_consistent_files(self):
        self.assertTrue(all(o["intervalCrossCheck"]["status"]=="match" for o in self.report["origins"]))
        self.assertFalse(self.report["internalConsistency"]["independentEvidence"])
        self.assertFalse(self.report["fullHistoricalCoverage"])
        self.assertGreater(self.report["internalConsistency"]["originalSuffixStrippedRowCount"],0)
        self.assertTrue(self.report["internalConsistency"]["originalCollapsedTickerRows"])

    def test_audit_exact_replay_and_frozen_source_hashes(self):
        self.assertEqual(q.main(["--verify"]),0)

    def test_source_payload_tampering_fails(self):
        folder=self.clone(); path=folder/"sources/changes.gz"
        path.write_bytes(path.read_bytes()+b"tampered")
        with self.assertRaisesRegex(InputError,"checksum"): q.load_sources(folder)

    def test_rehashing_payload_cannot_escape_pinned_git_blob(self):
        folder=self.clone(); lock=json.loads((folder/"source-lock.json").read_text())
        source=lock["sources"]["changes"];raw=b"date,add,remove\n2020-01-01,FAKE,\n";packed=gzip.compress(raw,mtime=0)
        (folder/source["path"]).write_bytes(packed)
        source.update(rawSha256=q.sha256(raw),storedSha256=q.sha256(packed),byteCount=len(raw),gitBlobSha=q.git_hash("blob",raw))
        (folder/"source-lock.json").write_bytes(canonical(lock))
        with self.assertRaisesRegex(InputError,"pinned tree"): q.load_sources(folder)

    def test_commit_or_tree_tampering_fails(self):
        for name in ("commit","tree"):
            folder=self.clone();path=folder/("sources/"+name+".git-object");path.write_bytes(path.read_bytes()+b"x")
            with self.subTest(name=name),self.assertRaisesRegex(InputError,"commit/tree"):q.load_sources(folder)

    def test_source_path_traversal_is_rejected(self):
        folder=self.clone();lock=json.loads((folder/"source-lock.json").read_text());lock["sources"]["changes"]["path"]="../escape"
        (folder/"source-lock.json").write_bytes(canonical(lock))
        with self.assertRaisesRegex(InputError,"leaves"):q.load_sources(folder)

    def test_trust_upgrade_or_backdated_known_at_is_rejected(self):
        for key,value in (("trustedForPIT",True),("historicalKnownAt","2009-01-01T00:00:00Z"),("productionChangesAllowed",True)):
            folder=self.clone();lock=json.loads((folder/"source-lock.json").read_text());lock[key]=value
            (folder/"source-lock.json").write_bytes(canonical(lock))
            with self.subTest(key=key),self.assertRaisesRegex(InputError,"quarantine-only"):q.load_sources(folder)

    def test_frozen_audit_cannot_be_overwritten_or_partially_written(self):
        folder=self.clone();original=(folder/"coverage-audit.json").read_bytes()
        with self.assertRaises(InputError):q.freeze_files(folder,{"new.json":b"new", "coverage-audit.json":b"different"})
        self.assertEqual((folder/"coverage-audit.json").read_bytes(),original)
        self.assertFalse((folder/"new.json").exists())

    def test_quarantine_does_not_load_as_pit_inputs(self):
        with self.assertRaises((OSError,InputError)): PITInputs.load(q.FOLDER)

    def test_both_export_commands_fail_without_cohort_file(self):
        for script,folder in (("audit_fja_sp500_quarantine.py",q.FOLDER),("build_pit_sp500_inputs.py",q.ROOT/q.REFERENCE)):
            proc=subprocess.run([sys.executable,str(q.ROOT/"scripts"/script),"--export-cohorts"],capture_output=True,text=True)
            self.assertEqual(proc.returncode,2,proc.stdout+proc.stderr)
            self.assertFalse((folder/"origin-cohorts.json").exists())

    def test_new_source_commit_requires_new_version(self):
        with self.assertRaisesRegex(InputError,"pinned source commit"):
            q.import_source(Path("/does/not/exist"),"0"*40,self.clone())

    def test_csv_lists_every_origin_and_no_true_readiness(self):
        import csv,io
        rows=list(csv.DictReader(io.StringIO(q.render_origins_csv(self.report).decode())))
        self.assertEqual(len(rows),34)
        self.assertTrue(all(r["ready"]=="false" for r in rows))


if __name__ == "__main__":
    unittest.main()
