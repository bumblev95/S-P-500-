"""Causality and loss-mathematics checks for conditional indicator research."""
import copy
import json
import unittest

import numpy as np

from research_conditional_indicator import (FOLDER, conditional_support, historical_clip,
    label, loss_optimal_point, loss_weights, mature_magnitude_rows, paired_date_intervals)

PROTOCOL = json.loads((FOLDER/'PROTOCOL.json').read_text())


class ConditionalResearchTests(unittest.TestCase):
    def test_magnitude_labels_must_be_strictly_matured(self):
        past = dict(origin='2020-01-01', targetDate='2020-07-01', y=.8)
        boundary = dict(origin='2020-01-01', targetDate='2021-01-01', y=10.)
        future = dict(origin='2021-01-01', targetDate='2021-07-01', y=.1)
        rows = mature_magnitude_rows([past, boundary, future], '2021-01-01')
        self.assertEqual(rows, [past])

    def test_mape_weights_equal_the_declared_loss_up_to_constant(self):
        rows = [dict(origin='2020-01-01', y=v) for v in (.6, 1.2, 1.5)] + \
               [dict(origin='2021-01-01', y=.8)]
        forecast = np.array([1., 1., 1.1, 1.05])
        actual = np.array([r['y'] for r in rows])
        date_weights = np.array([2/3, 2/3, 2/3, 2.])
        w = loss_weights(rows, 'mape')
        normalization = len(rows)/np.sum(date_weights/actual)
        self.assertAlmostEqual(np.sum(w*abs(forecast-actual))/normalization,
                               np.sum(date_weights*abs(forecast/actual-1)))
        np.testing.assert_allclose(loss_weights(rows, 'mae'), date_weights)

    def test_mixture_decision_really_minimizes_each_approximate_loss(self):
        support = np.array([[.8, 1., 1.5]])
        probability = np.array([[.4, .05, .55]])
        mae = loss_optimal_point(support, probability, 'mae')[0]
        mape = loss_optimal_point(support, probability, 'mape')[0]
        self.assertEqual(mae, 1.5)
        self.assertEqual(mape, .8)
        for point, scale in ((mae, 1.), (mape, support[0])):
            risk = lambda f: np.sum(probability[0]*abs(f-support[0])/scale)
            self.assertLessEqual(risk(point), min(risk(x) for x in np.linspace(.5, 1.8, 1000)))
        # The MAPE-optimal value can be down even when the biggest class score is up.
        self.assertEqual(label(mape), -1)
        self.assertEqual(np.argmax(probability[0]), 2)

    def test_numeric_bounds_use_previous_support_only(self):
        history = [dict(y=.7), dict(y=1.3)]
        value, info = historical_clip([-2., 1., 10.], history)
        np.testing.assert_allclose(value, [.7, 1., 1.3])
        self.assertEqual(info['clipped'], 2)
        self.assertEqual(info['lower'], .7)
        self.assertEqual(info['upper'], 1.3)

    def test_class_fallback_keeps_all_forecasts_and_class_support(self):
        rows = [dict(origin='2020-01-01', y=v) for v in (.7, .8, 1., 1.2, 1.3)]
        support, info = conditional_support(rows, np.zeros((9, 12)), 'mae', PROTOCOL)
        self.assertTrue(info['fallback'])
        self.assertEqual(support.shape, (9, 3))
        self.assertTrue(np.all(support[:, 0] < .98))
        self.assertTrue(np.all(support[:, 1] == 1.))
        self.assertTrue(np.all(support[:, 2] > 1.02))
        point = loss_optimal_point(support, np.tile([.2, .1, .7], (9, 1)), 'mae')
        self.assertEqual(len(point), 9)

    def test_invalid_probability_and_class_alignment_are_rejected(self):
        atoms = np.array([[.8, 1., 1.2]])
        for probability in (np.array([[.5, .5, .5]]), np.array([[-.1, .4, .7]]), np.ones((1, 2))):
            with self.assertRaises(ValueError):
                loss_optimal_point(atoms, probability, 'mae')
        with self.assertRaisesRegex(ValueError, 'class definition'):
            loss_optimal_point(np.array([[1.1, 1., .8]]), np.array([[.3, .2, .5]]), 'mape')

    def test_paired_interval_has_correct_error_and_direction_signs(self):
        base = {'byDate': {f'202{i}-01-01': dict(mape=.3, returnMae=.4, directionAccuracy=.7)
                          for i in range(3)}}
        candidate = copy.deepcopy(base)
        for m in candidate['byDate'].values():
            m.update(mape=.2, returnMae=.3, directionAccuracy=.6)
        out = paired_date_intervals(candidate, base)
        self.assertAlmostEqual(out['mape']['mean'], .1)
        self.assertAlmostEqual(out['returnMae']['mean'], .1)
        self.assertAlmostEqual(out['directionAccuracy']['mean'], -.1)
        self.assertLess(out['directionAccuracy']['interval'][1], 0)


if __name__ == '__main__':
    unittest.main()
