"""Leakage, target, weighting and role-separation checks for the drawdown study."""
import unittest

from collect_drawdown_paths import slice_path
from research_drawdown_separation import endpoint_metrics, maximum_drawdown, read_path_snapshot, risk_metrics


class DrawdownSeparationTests(unittest.TestCase):
    def test_path_uses_past_anchor_and_never_reads_after_target(self):
        series = [("2020-01-01", 100), ("2020-01-02", 90), ("2020-01-03", 80), ("2020-01-04", 10)]
        path = slice_path(series, "2020-01-02", "2020-01-03")
        self.assertEqual(path["anchorDate"], "2020-01-01")
        self.assertEqual(path["through"], "2020-01-03")
        self.assertEqual(path["ratios"], [1.0, 0.9, 0.8])

    def test_maximum_drawdown_is_peak_to_later_trough(self):
        self.assertAlmostEqual(maximum_drawdown([1.0, 1.2, 0.9, 1.1]), -0.25)
        self.assertEqual(maximum_drawdown([1.0, 1.1, 1.2]), 0.0)

    def test_recovery_and_endpoint_direction_are_not_conflated(self):
        path = [1.0, 0.7, 1.1]
        self.assertLessEqual(maximum_drawdown(path), -0.20)
        self.assertGreaterEqual(path[-1], 0.98)

    def test_date_weighting_gives_each_origin_equal_mass(self):
        rows = []
        for index in range(100):
            rows.append({"origin": "2020-01-01", "severeDrawdown": True, "warnings": {"x": True}})
        rows.append({"origin": "2021-01-01", "severeDrawdown": True, "warnings": {"x": False}})
        metric = risk_metrics(rows, "x")
        self.assertAlmostEqual(metric["recall"], 0.5)
        self.assertAlmostEqual(metric["pooledAllRows"]["recall"], 100 / 101)

    def test_endpoint_metrics_do_not_read_risk_warning(self):
        base = {"origin": "2020-01-01", "y": 0.8, "priceOnly": 1.1}
        before = endpoint_metrics([dict(base, warnings={"x": False})])
        after = endpoint_metrics([dict(base, warnings={"x": True})])
        self.assertEqual(before, after)

    def test_missing_path_is_explicit(self):
        self.assertEqual(slice_path([], "2020-01-02", "2020-01-03")["status"], "missing")

    def test_frozen_chunks_reassemble_to_registered_snapshot(self):
        from pathlib import Path
        folder = Path(__file__).resolve().parents[1] / "research/joint-indicator/drawdown-separation-v1"
        compressed, snapshot = read_path_snapshot(folder)
        self.assertEqual(len(compressed), 11800296)
        self.assertEqual(snapshot["coverage"]["coveredRows"], 8243)


if __name__ == "__main__":
    unittest.main()
