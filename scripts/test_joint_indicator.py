"""Meaningful checks for chronology, joint-distribution math and misleading gates."""
import copy
import json
import unittest

import numpy as np
from research_joint_indicator import (ROOT, LABELS, Mixture, date_weights, gates,
                                     matrix, score, split_matured, validate_source)

PROTOCOL = json.loads((ROOT/'research/joint-indicator/PROTOCOL.json').read_text())


def row(day, target, ratio=1.1):
    return dict(symbol='TEST', origin=day, targetDate=target, y=ratio,
        regime='상승·보통변동', inputCount=3, contextThrough=None, inputThrough=None,
        priceOnly=1.03, environment=1.04, balanced=1.05, independentReturn=1.06,
        secDynamics=1.07, independentReturnScores={'raw': [.3, .1, .6]},
        secDynamicsScores={'raw': [.4, .1, .5]})


class JointResearchTests(unittest.TestCase):
    def test_purge_maturity_and_calibration_overlap(self):
        rows = []
        for month in range(1, 7):
            for ratio in (.8, 1., 1.2):
                rows += [row(f'2020-{month:02}-01', f'2020-{month:02}-20', ratio) for _ in range(25)]
        rows.append(row('2020-01-02', '2020-05-01'))
        rows.append(row('2020-02-02', '2020-07-01'))
        fit, calibration, matured = split_matured(rows, '2020-07-01', PROTOCOL)
        self.assertTrue(all(r['targetDate'] < '2020-05-01' for r in fit))
        self.assertTrue(all(r['targetDate'] < '2020-07-01' for r in matured))
        self.assertEqual({r['origin'] for r in calibration}, {'2020-05-01', '2020-06-01'})

    def test_feature_matrix_does_not_read_future_outcome(self):
        a = row('2020-01-01', '2020-07-01', .7)
        b = copy.deepcopy(a)
        b.update(y=5., targetDate='2099-01-01')
        np.testing.assert_array_equal(matrix([a]), matrix([b]))

    def test_distribution_quantiles_respect_class_mass(self):
        rows = [row('2020-01-01', '2020-07-01', v) for v in (.7, .8, 1., 1.2, 1.4)]
        mixture = Mixture(rows)
        p = np.array([[.6, .1, .3], [.2, .1, .7], [.2, .6, .2]])
        values = mixture.quantiles(p)
        self.assertLess(values[0, 1], .98)
        self.assertGreater(values[1, 1], 1.02)
        self.assertEqual(values[2, 1], 1.)
        self.assertTrue(np.all(values[:, 0] <= values[:, 1]))
        self.assertTrue(np.all(values[:, 1] <= values[:, 2]))

    def test_dates_not_issuers_define_training_weight(self):
        rows = [row('2020-01-01', '2020-07-01')] * 100 + [row('2020-02-01', '2020-08-01')]
        weights = date_weights(rows)
        self.assertAlmostEqual(weights[:100].sum(), weights[-1])

    def test_always_up_cannot_pass_with_perfect_magnitude(self):
        rows = []
        for day in range(1, 7):
            for value in (.8, 1., 1.2):
                r = row(f'2020-01-{day:02}', '2020-07-01', value)
                r['methods'] = {
                    'candidate': dict(value=value, direction=1, probability=[.1, .1, .8],
                                      prior=[1/3]*3, low=.5, high=2.),
                    'baseline': dict(value=1., direction=0)}
                rows.append(r)
        m = score(rows, 'candidate')
        baseline = score(rows, 'baseline')
        self.assertEqual(m['dateMeanMape'], 0.)
        self.assertEqual(m['returnDirectionAccuracy'], 1.)
        self.assertEqual(m['downRecall'], 0.)
        checks = gates(m, baseline, baseline, PROTOCOL)
        self.assertFalse(checks['direction'])
        self.assertFalse(checks['downRecall'])
        self.assertFalse(all(v for k, v in checks.items() if k != 'prospective'))

    def test_source_rejects_future_context_and_unmatured_label(self):
        r = row('2020-01-01', '2020-07-01')
        source = {'generatedAt': '2020-08-01T00:00:00Z',
                  'stocks': {str(h): {'folds': [], 'outcomes': [copy.deepcopy(r)]} for h in (126, 252)}}
        validate_source(source, PROTOCOL)
        source['stocks']['126']['outcomes'][0]['contextThrough'] = '2020-01-01'
        with self.assertRaisesRegex(ValueError, 'available'):
            validate_source(source, PROTOCOL)
        source['stocks']['126']['outcomes'][0]['contextThrough'] = None
        source['stocks']['126']['outcomes'][0]['targetDate'] = '2021-01-01'
        with self.assertRaisesRegex(ValueError, 'matured'):
            validate_source(source, PROTOCOL)


if __name__ == '__main__':
    unittest.main()
