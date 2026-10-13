"""Regression failures at the research-selection and operating-default boundaries."""
import copy
import json
import math
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import build_adaptive_research as adapter
import build_decision_support as decision

ADAPTER = 'completed-error-adapter-v1:pooled-hgb-pattern-v3-medium-long:regimeBlend'


def population(mode='good', dates=12):
    rows = []
    for i in range(dates):
        origin = date(2020, 1, 1)+timedelta(days=i*40)
        for j in range(60):
            down = j < 30
            actual, original, candidate = (.8, .5, .8) if down else (1.2, 1.5, 1.2)
            if mode == 'cheap_wrong_direction':
                actual, original, candidate = (.979, .85, .99) if down else (1.021, 1.15, 1.01)
            elif mode == 'mae_mape_conflict':
                actual, original, candidate = (.5, .55, .7) if j < 50 else (3., 4., 3.)
            elif mode == 'direction_price_conflict':
                actual, original, candidate = (.979, .99, .9) if down else (1.021, 1.01, 1.1)
            rows.append(dict(symbol=str(j), origin=origin.isoformat(),
                targetDate=(origin+timedelta(days=20)).isoformat(),
                y=math.log(actual), original=math.log(original), trend=0., noChange=0.,
                biasCorrected=math.log(original), regimeBlend=math.log(candidate),
                correctionTargetThrough=(origin-timedelta(days=1)).isoformat(),
                ma200=.1, vol84=.2))
    return rows


def prospective_pairs(challenger=ADAPTER):
    rows = []
    for i in range(12):
        origin = date(2020, 1, 1)+timedelta(days=i*40)
        for symbol in ('A', 'B', 'C'):
            for model, error in [('old', .2), (challenger, .1)]:
                rows.append(dict(assetClass='stocks', symbol=symbol, horizon=21,
                    asOf=origin.isoformat(), targetDate=(origin+timedelta(days=30)).isoformat(),
                    issuedAt=origin.isoformat()+'T01:00:00Z', source='Yahoo EOD',
                    model=model, status='scored', anchor=100., base=110., low=90., high=130.,
                    mape=error, baselineMape=.3, directionHit=True,
                    eligible=True, passed=True, productionEligible=True))
    return rows


class JointSelectionTests(unittest.TestCase):
    def test_lower_error_with_wrong_direction_is_only_diagnostic(self):
        result = adapter.compare(population('cheap_wrong_direction'))
        self.assertEqual(result['diagnosticChoice'], 'regimeBlend')
        self.assertTrue(result['selectionChecks']['regimeBlend']['average'])
        self.assertFalse(result['selectionChecks']['regimeBlend']['direction'])
        self.assertIsNone(result['selectedCandidate'])
        self.assertEqual(result['chosenScope'], 'diagnostic-only')
        self.assertFalse(result['passed'])
        self.assertEqual(result['retainedModel'], 'original')

    def test_return_mae_gain_cannot_hide_price_mape_loss(self):
        result = adapter.compare(population('mae_mape_conflict'))
        checks = result['selectionChecks']['regimeBlend']
        self.assertTrue(checks['average'])
        self.assertTrue(checks['direction'])
        self.assertFalse(checks['mape'])
        self.assertIsNone(result['selectedCandidate'])

    def test_direction_gain_cannot_hide_price_loss(self):
        result = adapter.compare(population('direction_price_conflict'))
        checks = result['selectionChecks']['regimeBlend']
        self.assertTrue(checks['direction'])
        self.assertFalse(checks['average'])
        self.assertIsNone(result['selectedCandidate'])

    def test_later_outcomes_and_alternative_predictions_cannot_reselect(self):
        rows = population(); first = adapter.compare(rows)
        changed = copy.deepcopy(rows)
        for row in changed:
            if row['origin'] >= first['evaluationStart']:
                row['y'] = .5
                row['regimeBlend'] = -1.
                row['biasCorrected'] = row['y']
        second = adapter.compare(changed)
        for key in ('selectedCandidate', 'chosen', 'diagnosticChoice', 'selectionChecks', 'selectionEvaluation'):
            self.assertEqual(first[key], second[key])
        self.assertFalse(second['passed'])
        self.assertLess(second['selectionTargetThrough'], second['evaluationStart'])

    def test_statistical_success_is_never_live_eligibility(self):
        result = adapter.compare(population())
        self.assertTrue(result['passed'])
        self.assertEqual(result['selectedCandidate'], 'regimeBlend')
        for key in ('productionEligible', 'promotionCandidate', 'pitComplete',
                    'untouchedProspectiveEvidence', 'automaticPromotion', 'liveForecastChanged', 'usedForTrading'):
            self.assertIs(result[key], False)

    def test_no_dates_stays_fail_closed(self):
        result = adapter.compare([])
        self.assertEqual(result['status'], 'insufficient')
        self.assertIsNone(result['selectedCandidate'])
        self.assertFalse(result['passed'])
        self.assertFalse(result['productionEligible'])

    def test_complete_population_required_for_every_candidate(self):
        rows = population(); del rows[-1]['regimeBlend']
        with self.assertRaisesRegex(ValueError, 'paired prediction'):
            adapter.compare(rows)

    def test_duplicate_and_overlapping_origins_are_rejected(self):
        rows = population()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            adapter.compare(rows+[rows[0]])
        rows[0]['targetDate'] = rows[60]['targetDate']
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            adapter.compare(rows)

    def test_nonfinite_boolean_and_overflow_predictions_are_rejected(self):
        for value in (float('nan'), float('inf'), True, 1000., -1000.):
            with self.subTest(value=value):
                rows = population(); rows[-1]['regimeBlend'] = value
                with self.assertRaises(ValueError): adapter.compare(rows)

    def test_same_session_target_cannot_enter_correction(self):
        rows = population(); rows[-1]['correctionTargetThrough'] = rows[-1]['origin']
        with self.assertRaisesRegex(ValueError, 'unmatured'): adapter.compare(rows)

    def test_finite_logs_cannot_create_nonfinite_price_metrics(self):
        rows = population(); rows[-1]['y'] = -700.; rows[-1]['regimeBlend'] = 700.
        with self.assertRaisesRegex(ValueError, 'Nonfinite comparison metric'): adapter.compare(rows)

    def test_more_same_date_stocks_do_not_change_weight_or_evidence(self):
        rows = population(); first = adapter.compare(rows)
        extra = [dict(row, symbol='extra'+row['symbol']) for row in rows if row['origin'] == rows[0]['origin']]
        second = adapter.compare(rows+extra)
        self.assertEqual(first['selectedCandidate'], second['selectedCandidate'])
        self.assertEqual(first['evaluation']['original']['dates'], second['evaluation']['original']['dates'])
        self.assertAlmostEqual(first['selectionEvaluation']['original']['mae'],
                               second['selectionEvaluation']['original']['mae'], places=14)

    def test_direction_endpoints_and_next_float(self):
        low, high = math.log(.98), math.log(1.02)
        values = [np.nextafter(low, -np.inf), low, 0., high, np.nextafter(high, np.inf)]
        np.testing.assert_array_equal(adapter.direction(values), [-1, 0, 0, 0, 1])

    def test_source_fold_identity_and_completion_required(self):
        row = population(dates=1)[0]; row['pred'] = row['original']
        fold = dict(origin=row['origin'], trainTargetThrough='2019-01-01', calibrationTargetThrough='2019-12-01')
        source = dict(outcomes=[row], folds=[fold], generatedAt='2020-02-01T00:00:00Z')
        self.assertEqual(len(adapter.normalize(source)), 1)
        with self.assertRaisesRegex(ValueError, 'Duplicate source fold'):
            adapter.normalize(dict(source, folds=[fold, fold]))
        with self.assertRaisesRegex(ValueError, 'Missing source fold'):
            adapter.normalize(dict(source, folds=[]))
        with self.assertRaisesRegex(ValueError, 'not matured'):
            adapter.normalize(dict(source, generatedAt='2020-01-10T00:00:00Z'))


class OperatingBoundaryTests(unittest.TestCase):
    def test_strong_forward_price_scores_and_forged_flags_cannot_release_adapter(self):
        gate = decision.paired_gate(prospective_pairs(), 'old', ADAPTER)
        self.assertTrue(gate['priceScreenPassed'])
        self.assertFalse(gate['passed'])
        self.assertFalse(gate['productionEligible'])
        self.assertTrue(gate['researchOnly'])
        self.assertTrue(decision.paired_gate(prospective_pairs('new'), 'old', 'new')['passed'])

    def test_empty_forward_sample_is_also_blocked(self):
        gate = decision.paired_gate([], 'old', ADAPTER)
        self.assertFalse(gate['passed'])
        self.assertTrue(gate['researchOnly'])

    def test_full_build_keeps_incumbent_and_registry_events(self):
        rows = prospective_pairs()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'decision/ledger').mkdir(parents=True)
            (root/'decision/ledger/frozen.json').write_text(json.dumps(dict(records=rows)))
            outcomes = {decision.key(row):dict(status='scored', targetDate=row['targetDate'],
                         mape=row['mape'], baselineMape=row['baselineMape'], directionHit=True) for row in rows}
            (root/'decision/outcomes.json').write_text(json.dumps(dict(records=outcomes)))
            registry = dict(champions={'stocks:21':'old'}, events=[])
            (root/'decision/registry.json').write_text(json.dumps(registry))
            now = datetime(2026, 10, 13, tzinfo=timezone.utc)
            with patch.object(decision, 'capture', return_value=(rows[-6:], dict(stocks='old', crypto='coin'))):
                result = decision.build(root, now)
            self.assertEqual(json.loads((root/'decision/registry.json').read_text()), registry)
            self.assertEqual(result['groups']['stocks']['21']['champion'], 'old')
            self.assertTrue(result['groups']['stocks']['21']['gates'][0]['priceScreenPassed'])
            self.assertFalse(result['groups']['stocks']['21']['gates'][0]['passed'])
            self.assertEqual(result['current']['stocks'], {})

    def test_already_contaminated_registry_stops_before_any_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'decision').mkdir()
            registry = root/'decision/registry.json'
            registry.write_text(json.dumps(dict(champions={'stocks:126':ADAPTER}, events=[])))
            before = registry.read_bytes()
            with self.assertRaisesRegex(ValueError, 'cannot be a champion'): decision.build(root)
            self.assertEqual(registry.read_bytes(), before)
            self.assertFalse((root/'decision/ledger').exists())
            self.assertFalse((root/'decision/latest.json').exists())


if __name__ == '__main__':
    unittest.main()
