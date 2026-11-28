"""Synthetic accounting/chronology regressions; none are historical model results."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pit_sp500_inputs import InputError, InputBlocked, PITInputs
from research_merger_lifecycle import DOMAINS, LifecycleInputs, VERSION
from test_pit_sp500_inputs import fixture, event, ORIGIN

A, OTHER, EXIT, B, C, RIGHT = "issuer-1-A", "issuer-1-C", "issuer-2-common", "successor-B", "successor-C", "contingent-right"
TARGET = "2020-12-31T21:00:00Z"
ASOF = "2021-02-01T00:00:00Z"
ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "research/joint-indicator/merger-lifecycle-v1"


def record(**values):
    row = dict(sourceId="fixture", evidenceLocator="synthetic fixture row",
               effectiveAt="2010-01-01T00:00:00Z", knownAt="2018-01-01T00:00:00Z")
    return {**row, **values}


def cash(amount):
    return dict(kind="cash", perUnit=amount, currency="USD")


def security(sid, ratio):
    return dict(kind="asset", perUnit=ratio, securityId=sid)


def action(aid="merger", sid=A, legs=None, kind="exchange", at="2020-06-01T13:30:00Z", **updates):
    row = record(actionId=aid, eventKey=aid, securityId=sid, kind=kind, status="completed",
        effectiveAt=at, settledAt=at, knownAt="2020-06-02T00:00:00Z", termsVerified=True,
        settlementEvidence="synthetic actually delivered consideration", entitlementConvention="effective_at_per_unit_verified",
        deliveries=[cash(125)] if legs is None else legs)
    row.update(updates)
    return row


def dataset():
    old = fixture()
    for price in old["prices"]:
        price.update(basis="unadjusted", currency="USD")
    assets = [record(securityId=sid, kind="right" if sid == RIGHT else "equity", verified=True,
        permanentId=dict(provider="synthetic", scheme="provider_issue_id", value=sid),
        identityEvidence="synthetic immutable issue mapping") for sid in (A,OTHER,EXIT,B,C,RIGHT)]
    quotes = [record(securityId=sid, basis="unadjusted", currency="USD", close=120,
        effectiveAt=TARGET, knownAt="2021-01-01T00:00:00Z") for sid in (A,OTHER,EXIT,B,C)]
    coverage = [record(coverageId=sid, securityId=sid, completeness="complete", domains=sorted(DOMAINS),
        **{"from":"2019-01-01T00:00:00Z"}, throughExclusive="2021-01-02T00:00:00Z",
        knownAt="2021-01-03T00:00:00Z", coverageEvidence="synthetic full distributions/actions/identity/terminal coverage") for sid in (A,OTHER,EXIT,B,C,RIGHT)]
    data = dict(schemaVersion=1, version=VERSION, policyId=VERSION, researchOnly=True,
        sources=copy.deepcopy(old["sources"]), assets=assets, quotes=quotes, coverage=coverage,
        actions=[], observations=[])
    return old,data


def run(data=None, old=None, asof=ASOF, target=TARGET):
    base,payload=dataset()
    pit=PITInputs(old if old is not None else base, allow_synthetic=True)
    layer=LifecycleInputs(data if data is not None else payload, allow_synthetic=True)
    cohort=pit.snapshot(ORIGIN)
    return layer.ledger(pit,cohort,target,asof)


def result(ledger,sid=A):
    return next(r for r in ledger["rows"] if r["securityId"]==sid)


def forecasts(cohort):
    return dict(cohortHash=cohort["cohortHash"],origin=ORIGIN,targetAt=TARGET,
        rows=[dict(securityId=r["securityId"],origin=ORIGIN,
                   predictedOriginalPriceFactor=1.1,predictedTotalReturnFactor=1.1) for r in cohort["members"]])


class LifecycleTests(unittest.TestCase):
    def test_cash_merger_preserves_origin_and_has_no_original_price_target(self):
        _,data=dataset();data["actions"]=[action()]
        ledger=run(data);row=result(ledger)
        self.assertEqual(row["securityId"],A);self.assertEqual(row["totalReturnFactor"],1.25)
        self.assertEqual(row["cashReceivedUSD"],125);self.assertEqual(row["positions"],[])
        self.assertEqual(row["priceTargetStatus"],"not_applicable_extinguished")
        self.assertIsNone(row["priceFactor"])
        self.assertEqual((ledger["originPopulation"],ledger["retainedPopulation"]),(3,3))

    def test_stock_exchange_uses_exact_ratio_not_successor_price_as_original(self):
        _,data=dataset();data["actions"]=[action(legs=[security(B,.5)])]
        row=result(run(data))
        self.assertEqual(row["totalReturnFactor"],.6)
        self.assertEqual(row["positions"][0]["units"],"0.5")
        self.assertIsNone(row["priceFactor"])

    def test_cash_and_shares_are_both_retained(self):
        _,data=dataset();data["actions"]=[action(legs=[cash(10),security(B,.5)])]
        self.assertEqual(result(run(data))["totalReturnFactor"],.7)

    def test_chained_merger_and_successor_dividend(self):
        _,data=dataset();data["actions"]=[action(legs=[security(B,.5)]),
            action("dividend",B,[cash(4)],kind="distribution",at="2020-08-01T13:30:00Z",knownAt="2020-08-02T00:00:00Z"),
            action("second",B,[cash(20),security(C,2)],at="2020-09-01T13:30:00Z",knownAt="2020-09-02T00:00:00Z")]
        row=result(run(data));self.assertEqual(row["totalWealthUSD"],132)
        self.assertEqual(row["positions"][0]["securityId"],C)

    def test_dividend_is_cash_only_and_not_reinvested(self):
        _,data=dataset();data["actions"]=[action(kind="distribution",legs=[cash(10)])]
        row=result(run(data));self.assertEqual(row["totalReturnFactor"],1.3)
        self.assertEqual(row["priceFactor"],1.2)
        self.assertEqual(row["positions"][0]["units"],"1")

    def test_split_adjusts_units_without_manufacturing_wealth(self):
        _,data=dataset();data["actions"]=[action(kind="split",legs=[],ratio=2)]
        next(q for q in data["quotes"] if q["securityId"]==A)["close"]=60
        row=result(run(data));self.assertEqual(row["totalReturnFactor"],1.2);self.assertEqual(row["priceFactor"],1.2)

    def test_unresolved_right_blocks_even_if_maximum_or_quote_is_supplied(self):
        _,data=dataset();data["actions"]=[action(legs=[cash(11.45),security(RIGHT,1)])]
        data["quotes"].append(record(securityId=RIGHT,basis="unadjusted",currency="USD",close=3,
            effectiveAt=TARGET,knownAt="2021-01-01T00:00:00Z"))
        row=result(run(data));self.assertIsNone(row["totalReturnFactor"])
        self.assertIn("unresolved_contingent_right:"+RIGHT,row["blockers"])
        self.assertEqual(row["cashReceivedUSD"],11.45)

    def test_actual_right_redemption_completes_wealth(self):
        _,data=dataset();data["actions"]=[action(legs=[cash(11.45),security(RIGHT,1)]),
            action("right-payment",RIGHT,[cash(2)],at="2020-10-01T13:30:00Z",knownAt="2020-10-02T00:00:00Z")]
        self.assertAlmostEqual(result(run(data))["totalReturnFactor"],.1345)

    def test_confirmed_worthless_right_is_zero_not_missing(self):
        _,data=dataset();data["actions"]=[action(legs=[cash(11.45),security(RIGHT,1)]),
            action("right-expiry",RIGHT,[],kind="zero_recovery",zeroRecoveryConfirmed=True,
                   at="2020-10-01T13:30:00Z",knownAt="2020-10-02T00:00:00Z")]
        self.assertEqual(result(run(data))["totalReturnFactor"],.1145)

    def test_confirmed_bankruptcy_zero_preserves_row_and_is_scoreable_as_return(self):
        old,data=dataset();data["actions"]=[action(kind="zero_recovery",legs=[],zeroRecoveryConfirmed=True)]
        pit=PITInputs(old,allow_synthetic=True);cohort=pit.snapshot(ORIGIN)
        output=LifecycleInputs(data,allow_synthetic=True).evaluate(pit,cohort,TARGET,ASOF,forecasts(cohort))
        self.assertEqual(result(output["ledger"])["totalReturnFactor"],0)
        self.assertIsNotNone(output["metrics"]["totalReturnMAEPercentagePoints"])
        self.assertIsNone(output["metrics"]["originalPriceMAPEPercent"])

    def test_missing_consideration_cannot_be_assumed_zero(self):
        _,data=dataset();data["actions"]=[action(legs=[])]
        with self.assertRaisesRegex(InputError,"empty"):run(data)

    def test_missing_successor_price_keeps_original_row_and_blocks_all_return_metrics(self):
        _,data=dataset();data["actions"]=[action(legs=[security(B,1)])]
        data["quotes"]=[q for q in data["quotes"] if q["securityId"]!=B]
        ledger=run(data);self.assertEqual(ledger["retainedPopulation"],3)
        self.assertFalse(ledger["totalReturnMetricsAllowed"])
        self.assertIn("missing_exact_target_valuation:"+B,result(ledger)["blockers"])

    def test_last_available_quote_is_not_carried_to_horizon(self):
        _,data=dataset();next(q for q in data["quotes"] if q["securityId"]==A)["effectiveAt"]="2020-12-30T21:00:00Z"
        self.assertIsNone(result(run(data))["totalReturnFactor"])

    def test_missing_successor_identity_cannot_be_rescued_by_ticker(self):
        _,data=dataset();data["actions"]=[action(legs=[security(B,1)])]
        next(a for a in data["assets"] if a["securityId"]==B)["verified"]=False
        self.assertIn("missing_permanent_identity:"+B,result(run(data))["blockers"])

    def test_CIK_is_not_a_permanent_issue_identity(self):
        _,data=dataset();data["assets"][0]["permanentId"]["scheme"]="CIK"
        with self.assertRaisesRegex(InputError,"Permanent"):run(data)

    def test_membership_removal_does_not_sell_or_drop_security(self):
        old,data=dataset();old["events"].append(event("exit",A,"membership",False,effective="2020-06-01T13:30:00Z",known="2020-05-30T00:00:00Z"))
        self.assertEqual(result(run(data,old))["totalReturnFactor"],1.2)
        self.assertEqual(run(data,old)["retainedPopulation"],3)

    def test_ticker_rename_does_not_change_permanent_security_or_wealth(self):
        old,data=dataset();old["events"].append(event("rename",A,"symbol",dict(symbol="NEW",venue="NYSE"),
            effective="2020-06-01T13:30:00Z",known="2020-05-30T00:00:00Z"))
        self.assertEqual(result(run(data,old))["totalReturnFactor"],1.2)

    def test_pending_and_cancelled_announcements_do_not_deliver_cash(self):
        _,data=dataset();data["actions"]=[action(status="announced",settledAt=None)]
        row=result(run(data));self.assertIsNone(row["totalReturnFactor"]);self.assertEqual(row["cashReceivedUSD"],0)
        data["actions"][0].update(status="cancelled",cancelledAt="2020-06-01T14:00:00Z",cancellationEvidence="synthetic withdrawn")
        self.assertEqual(result(run(data))["totalReturnFactor"],1.2)

    def test_post_horizon_settlement_stays_unvalued_receivable(self):
        _,data=dataset();data["actions"]=[action(settledAt="2021-01-04T13:30:00Z",knownAt="2021-01-05T00:00:00Z")]
        row=result(run(data));self.assertEqual(row["cashReceivedUSD"],0)
        self.assertIsNone(row["totalReturnFactor"]);self.assertEqual(row["priceTargetStatus"],"not_applicable_extinguished")
        self.assertEqual(row["unsettledReceivables"][0]["targetValueUSD"],None)
        self.assertFalse(row["positions"])

    def test_late_action_correction_changes_only_later_evaluation(self):
        _,data=dataset();first=action();corrected=action("correction",legs=[cash(130)],eventKey="merger",supersedes="merger",knownAt="2021-03-01T00:00:00Z")
        data["actions"]=[first,corrected]
        self.assertEqual(result(run(data))["totalReturnFactor"],1.25)
        self.assertEqual(result(run(data,asof="2021-04-01T00:00:00Z"))["totalReturnFactor"],1.3)

    def test_price_revision_requires_its_own_knowledge_clock(self):
        _,data=dataset();q=copy.deepcopy(next(q for q in data["quotes"] if q["securityId"]==A))
        q.update(close=200,knownAt="2021-03-01T00:00:00Z");data["quotes"].append(q)
        self.assertEqual(result(run(data))["totalReturnFactor"],1.2)
        self.assertEqual(result(run(data,asof="2021-04-01T00:00:00Z"))["totalReturnFactor"],2)

    def test_future_effective_action_does_not_change_earlier_target(self):
        _,data=dataset();data["actions"]=[action(at="2021-01-05T13:30:00Z",knownAt="2021-01-06T00:00:00Z")]
        self.assertEqual(result(run(data))["totalReturnFactor"],1.2)

    def test_price_quote_known_exactly_at_evaluation_is_not_available(self):
        _,data=dataset();next(q for q in data["quotes"] if q["securityId"]==A)["knownAt"]=ASOF
        self.assertIsNone(result(run(data))["totalReturnFactor"])

    def test_unmatured_target_stays_pending(self):
        ledger=run(asof=TARGET);self.assertTrue(all(r["status"]=="pending_outcome" for r in ledger["rows"]))

    def test_lifecycle_coverage_gap_blocks_even_good_quotes_and_payments(self):
        _,data=dataset();data["coverage"]=[c for c in data["coverage"] if c["securityId"]!=A]
        self.assertTrue(any("coverage:"+A in b for b in result(run(data))["blockers"]))

    def test_coverage_end_is_exclusive_and_cannot_end_at_target(self):
        _,data=dataset();next(c for c in data["coverage"] if c["securityId"]==A)["throughExclusive"]=TARGET
        self.assertFalse(run(data)["totalReturnMetricsAllowed"])

    def test_no_adjusted_price_double_count_or_implicit_FX(self):
        for field,value in (("basis","point_in_time_adjusted"),("currency","CAD")):
            _,data=dataset();data["quotes"][0][field]=value
            with self.subTest(field=field),self.assertRaises(InputError):run(data)

    def test_adjusted_entry_price_cannot_start_per_share_book(self):
        old,data=dataset();old["prices"][0]["basis"]="point_in_time_adjusted"
        self.assertIn("positive_unadjusted_USD_entry_quote_required",result(run(data,old))["blockers"])

    def test_simultaneous_chain_or_duplicate_event_is_not_arbitrarily_ordered(self):
        _,data=dataset();data["actions"]=[action(legs=[security(B,1)]),action("second",B,[cash(125)])]
        with self.assertRaisesRegex(InputError,"Same-time"):run(data)
        data["actions"][1]["securityId"]=A
        with self.assertRaisesRegex(InputError,"simultaneous"):run(data)

    def test_unresolved_PIT_event_cannot_be_overridden_by_cash_only_outcome(self):
        old,data=dataset();old["events"].append(event("terminal",A,"delisting",dict(reason="acquired",settlementStatus="unresolved"),
            effective="2020-06-01T13:30:00Z",known="2020-06-02T00:00:00Z"))
        data["actions"]=[action(pitEventId="terminal")]
        row=result(run(data,old));self.assertIsNone(row["totalReturnFactor"])
        self.assertIn("unresolved_PIT_terminal_event:terminal",row["blockers"])

    def test_terminal_notice_needs_explicit_action_handoff(self):
        old,data=dataset();old["events"].append(event("terminal",A,"delisting",dict(reason="acquired",settlementStatus="resolved"),
            effective="2020-06-01T13:30:00Z",known="2020-06-02T00:00:00Z"))
        self.assertIn("missing_terminal_handoff:terminal",result(run(data,old))["blockers"])

    def test_successor_terminal_notice_also_blocks_original_investment_row(self):
        old,data=dataset();old["securities"].append(dict(securityId=B))
        old["events"].append(event("successor-terminal",B,"delisting",dict(reason="bankrupt",settlementStatus="unresolved"),
            effective="2020-09-01T13:30:00Z",known="2020-09-02T00:00:00Z"))
        data["actions"]=[action(legs=[security(B,.5)])]
        row=result(run(data,old));self.assertIsNone(row["totalReturnFactor"])
        self.assertIn("unresolved_PIT_terminal_event:successor-terminal",row["blockers"])

    def test_late_zero_recovery_correction_does_not_rewrite_earlier_evaluation(self):
        _,data=dataset();first=action(kind="zero_recovery",legs=[],zeroRecoveryConfirmed=True)
        correction=action("recovered",eventKey="merger",supersedes="merger",legs=[cash(5)],knownAt="2021-03-01T00:00:00Z")
        data["actions"]=[first,correction]
        self.assertEqual(result(run(data))["totalReturnFactor"],0)
        self.assertEqual(result(run(data,asof="2021-04-01T00:00:00Z"))["totalReturnFactor"],.05)

    def test_unmodelled_later_payment_on_extinguished_issue_is_not_silently_lost(self):
        _,data=dataset();data["actions"]=[action(),action("late-payment",legs=[cash(5)],kind="distribution",
            at="2020-09-01T13:30:00Z",knownAt="2020-09-02T00:00:00Z")]
        with self.assertRaisesRegex(InputError,"extinguished issue"):run(data)

    def test_no_metrics_on_survivor_only_forecast_subset(self):
        old,data=dataset();pit=PITInputs(old,allow_synthetic=True);cohort=pit.snapshot(ORIGIN);pred=forecasts(cohort)
        pred["rows"].pop()
        with self.assertRaisesRegex(InputError,"population mismatch"):
            LifecycleInputs(data,allow_synthetic=True).evaluate(pit,cohort,TARGET,ASOF,pred)

    def test_price_forecast_is_not_relabelled_as_total_return_prediction(self):
        old,data=dataset();pit=PITInputs(old,allow_synthetic=True);cohort=pit.snapshot(ORIGIN);pred=forecasts(cohort)
        for r in pred["rows"]:r.pop("predictedTotalReturnFactor")
        out=LifecycleInputs(data,allow_synthetic=True).evaluate(pit,cohort,TARGET,ASOF,pred)
        self.assertIsNone(out["metrics"]["totalReturnMAEPercentagePoints"])
        self.assertIsNotNone(out["metrics"]["originalPriceMAPEPercent"])

    def test_merger_blocks_full_population_price_MAPE_but_allows_complete_total_return(self):
        old,data=dataset();data["actions"]=[action()];pit=PITInputs(old,allow_synthetic=True);cohort=pit.snapshot(ORIGIN)
        out=LifecycleInputs(data,allow_synthetic=True).evaluate(pit,cohort,TARGET,ASOF,forecasts(cohort))
        self.assertIsNotNone(out["metrics"]["totalReturnMAEPercentagePoints"])
        self.assertIsNone(out["metrics"]["originalPriceMAPEPercent"])
        self.assertEqual(out["metricPopulation"],3)

    def test_incomplete_or_modified_origin_cohort_is_rejected(self):
        old,data=dataset();pit=PITInputs(old,allow_synthetic=True);cohort=pit.snapshot(ORIGIN);cohort["members"].pop()
        with self.assertRaisesRegex(InputError,"unchanged"):
            LifecycleInputs(data,allow_synthetic=True).ledger(pit,cohort,TARGET,ASOF)
        old["baselines"]=[];pit=PITInputs(old,allow_synthetic=True);cohort=pit.snapshot(ORIGIN,require_complete=False)
        with self.assertRaises(InputBlocked):LifecycleInputs(data,allow_synthetic=True).ledger(pit,cohort,TARGET,ASOF)

    def test_synthetic_data_is_never_accepted_as_real(self):
        _,data=dataset()
        with self.assertRaisesRegex(InputError,"Synthetic"):LifecycleInputs(data)


class FrozenEvidenceTests(unittest.TestCase):
    def test_real_wba_observation_is_unresolved_and_no_outcomes_invented(self):
        from build_merger_lifecycle import audit
        report=audit()
        self.assertEqual((report["originCount"],report["readyOriginCount"],report["realComputedOutcomeCount"]),(34,0,0))
        self.assertEqual(report["normalizedAssetCount"],0);self.assertEqual(report["normalizedActionCount"],0)
        self.assertEqual(report["observedTerms"][0]["status"],"unresolved")
        self.assertEqual(report["observedTerms"][0]["contingentCashMaximumUSD"],3)
        self.assertIsNone(report["observedTerms"][0]["totalReturnFactor"])

    def test_frozen_audit_and_every_preserved_hash_replay(self):
        from build_merger_lifecycle import main
        self.assertEqual(main(["--verify"]),0)

    def test_actual_export_fails_without_writing_for_incomplete_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"outcomes.json"
            proc=subprocess.run([sys.executable,str(ROOT/"scripts/build_merger_lifecycle.py"),"--export-outcomes",
                "--origin","2009-11-13","--target-at","2010-11-15T21:00:00Z",
                "--evaluated-at","2026-10-08T00:00:00Z","--output",str(path)],capture_output=True,text=True)
            self.assertEqual(proc.returncode,2,proc.stdout+proc.stderr);self.assertFalse(path.exists())

    def test_real_payload_tampering_is_rejected(self):
        import shutil
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/"bundle";shutil.copytree(FOLDER,dest)
            payload=dest/"sources/wba-20250828.html.gz";payload.write_bytes(payload.read_bytes()+b"tampered")
            with self.assertRaisesRegex(InputError,"hash mismatch"):LifecycleInputs.load(dest)


if __name__ == "__main__":
    unittest.main()
