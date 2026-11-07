"""Check chronology and failure modes of point and downside-gated combinations."""
import copy
import json
import unittest

import numpy as np

from research_indicator_blends import (FOLDER, choose_settings, conditional_down_magnitude,
    convex_prediction, guard_ok, label, matured_forecasts, predict_blends,
    project_forecast, routed_prediction, selection_metrics, validate_issuers)

PROTOCOL = json.loads((FOLDER/'PROTOCOL.json').read_text())


def features(value=1.05, specialist=.9, down=.6):
    return dict(symbol='TEST', origin='2023-01-01', priceOnly=value, noChange=1.,
                specialist=specialist, downScore=down, upScore=1-down, downValue=.8)


def past_rows():
    rows = []
    for year in (2020, 2021, 2022):
        for actual in (.8, 1., 1.2):
            for _ in range(20):
                rows.append(dict(origin=f'{year}-01-01', targetDate=f'{year}-07-01',
                    y=actual, features=features(1.08, actual, .8 if actual < .98 else .1)))
    return rows


class BlendResearchTests(unittest.TestCase):
    def test_selector_never_uses_unmatured_or_same_origin_labels(self):
        history = past_rows()
        expected = choose_settings(history, '2023-01-01', PROTOCOL)
        poison = dict(origin='2022-12-01', targetDate='2023-01-01', y=100., features=features())
        future = dict(origin='2023-01-01', targetDate='2023-07-01', y=.01, features=features())
        self.assertEqual(expected, choose_settings(history+[poison, future], '2023-01-01', PROTOCOL))
        self.assertLess(expected['history']['targetThrough'], '2023-01-01')
        self.assertEqual(len(matured_forecasts(history+[poison, future], '2023-01-01')), len(history))

    def test_current_features_cannot_read_target_or_outcome(self):
        row = dict(symbol='TEST', origin='2023-01-01', priceOnly=1.1, y=.4, targetDate='2023-07-01')
        joint = dict(value=1.05, probability=[.6, .1, .3])
        a = project_forecast(row, joint, .8)
        row.update(y=10., targetDate='2099-01-01')
        self.assertEqual(a, project_forecast(row, joint, .8))
        self.assertNotIn('y', a)
        self.assertNotIn('targetDate', a)

    def test_conditional_down_point_minimizes_empirical_mape(self):
        rows = [dict(origin='2020-01-01', y=v) for v in (.5, .9)]
        point = conditional_down_magnitude(rows)
        self.assertEqual(point, .5)
        loss = lambda p: np.mean(abs(p/np.array([.5, .9])-1))
        self.assertLess(loss(point), loss(.7))
        self.assertLessEqual(loss(point), min(loss(p) for p in np.linspace(.3, 1., 1000)))
        with self.assertRaisesRegex(ValueError, 'No matured'):
            conditional_down_magnitude([dict(origin='2020-01-01', y=1.2)])

    def test_convex_endpoints_and_real_signal_cancellation(self):
        f = [features(value=1.4, specialist=.8)]
        self.assertEqual(convex_prediction(f, 'priceOnly', 0)[0], 1.4)
        self.assertEqual(convex_prediction(f, 'priceOnly', 1)[0], .8)
        half = convex_prediction(f, 'priceOnly', .5)[0]
        self.assertAlmostEqual(half, 1.1)
        self.assertEqual(label(half), 1)
        # A high down score must not overwrite the resulting positive forecast.
        settings = choose_settings([], '2023-01-01', PROTOCOL)
        combined = predict_blends(f, settings)
        self.assertEqual(combined['fixed_half'][0]['direction'], 1)
        self.assertEqual(len(combined), len(PROTOCOL['candidates']))

    def test_guard_rejects_error_only_improvement(self):
        rows = past_rows()
        point = np.array([1.03]*len(rows))
        m = selection_metrics(rows, point)
        self.assertEqual(m['downRecall'], 0.)
        self.assertFalse(guard_ok(m, [m, m], PROTOCOL))

    def test_routing_requires_down_score_to_exceed_up(self):
        f = features(down=.45)
        self.assertEqual(routed_prediction([f], 'priceOnly', .35)[0], f['priceOnly'])
        f['downScore'], f['upScore'] = .55, .35
        self.assertEqual(routed_prediction([f], 'priceOnly', .35)[0], .8)

    def test_guards_do_not_remove_fallback_dates(self):
        settings = choose_settings(past_rows(), '2023-01-01', PROTOCOL)
        self.assertEqual(settings['history']['dates'], 3)
        result = predict_blends([features() for _ in range(7)], settings)
        self.assertTrue(all(len(v) == 7 for v in result.values()))
        for forecasts in result.values():
            for p in forecasts:
                self.assertEqual(p['direction'], label(p['value']))
                self.assertNotIn('probability', p)

    def test_issuer_classes_cannot_inflate_same_date_sample(self):
        rows = [dict(symbol=s, origin='2020-01-01') for s in ('GOOG', 'GOOGL')]
        source = {'stocks': {h: {'outcomes': copy.deepcopy(rows)} for h in ('126', '252')}}
        with self.assertRaisesRegex(ValueError, 'Duplicate issuer'):
            validate_issuers(source)


if __name__ == '__main__':
    unittest.main()
