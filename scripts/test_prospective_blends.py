"""Deterministic regression tests for prospective-blend-v1."""
import hashlib
import unittest
from pathlib import Path

from prospective_blends import (
    REGISTERED_PROTOCOL_SHA256, build_methods, direction, joint_gate, metric,
    sessions_after, target_date,
)


class ProspectiveBlendTests(unittest.TestCase):
    def test_direction_thresholds_are_strict_and_fixed(self):
        self.assertEqual(direction(-0.020001), -1)
        self.assertEqual(direction(-0.02), 0)
        self.assertEqual(direction(0.02), 0)
        self.assertEqual(direction(0.020001), 1)

    def test_fixed_weight_and_downside_override_are_frozen(self):
        methods = build_methods(0.01, -0.03, 100.0)
        self.assertAlmostEqual(methods["fixed50"]["predictedReturn"], -0.01)
        self.assertAlmostEqual(methods["fixed50"]["predictedPrice"], 99.0)
        self.assertEqual(methods["downsideOverride"]["predictedReturn"], -0.03)
        self.assertEqual(methods["downsideOverride"]["predictedPrice"], 97.0)
        flat_trend = build_methods(0.04, -0.02, 100.0)
        self.assertEqual(flat_trend["downsideOverride"]["predictedReturn"], 0.04)

    def test_returns_are_reexpressed_at_the_common_anchor(self):
        # Component anchors may differ; their returns are blended, then all
        # methods use the v5 anchor for the target-price comparison.
        from prospective_blends import component_return
        v5 = component_return(105.0, 100.0)
        trend = component_return(102.0, 120.0)
        methods = build_methods(v5, trend, 100.0)
        self.assertAlmostEqual(methods["v5"]["predictedPrice"], 105.0)
        self.assertAlmostEqual(methods["simpleTrend"]["predictedPrice"], 85.0)
        self.assertAlmostEqual(methods["fixed50"]["predictedPrice"], 95.0)

    def test_official_session_examples_include_early_closes_and_skip_holidays(self):
        self.assertEqual(target_date("2026-10-23"), "2026-11-23")
        self.assertEqual(target_date("2026-11-23"), "2026-12-23")
        self.assertEqual(target_date("2026-12-23"), "2027-01-26")
        self.assertEqual(target_date("2027-01-26"), "2027-02-25")
        self.assertEqual(target_date("2027-02-25"), "2027-03-29")
        self.assertEqual(sessions_after("2026-11-25", 1), ["2026-11-27"])
        self.assertEqual(sessions_after("2026-12-23", 1), ["2026-12-24"])
        with self.assertRaises(ValueError):
            target_date("2027-12-31")
        with self.assertRaises(ValueError):
            target_date("2026-10-24")

    def test_registered_protocol_hash_is_locked_in_code(self):
        path = Path(__file__).resolve().parents[1] / "research/joint-indicator/prospective-blend-v1/PROTOCOL.json"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), REGISTERED_PROTOCOL_SHA256)

    def test_target_archive_commit_cutoffs_account_for_early_closes(self):
        from audit_prospective_blends import target_close_utc
        self.assertEqual(target_close_utc("2026-11-27").isoformat(), "2026-11-27T18:00:00+00:00")
        self.assertEqual(target_close_utc("2026-12-24").isoformat(), "2026-12-24T18:00:00+00:00")
        self.assertEqual(target_close_utc("2026-11-23").isoformat(), "2026-11-23T21:00:00+00:00")

    def test_issue_join_uses_only_component_rows_issued_after_registration(self):
        import csv
        import io
        from datetime import datetime, timezone
        from freeze_prospective_blends import issue_rows

        issued = [
            {"model": "environment-challenger-v5-horizon-specific", "horizon": 21,
             "asOf": "2026-10-23", "symbol": "AAA", "issuedAt": "2026-10-23T12:29:00Z"},
            {"model": "environment-challenger-v5-horizon-specific", "horizon": 21,
             "asOf": "2026-10-23", "symbol": "BBB", "issuedAt": "2026-10-23T12:20:00Z"},
        ]
        fields = ["model", "horizon", "asOf", "symbol", "issuedAt"]
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows([
            {"model": "trend-decay-v1", "horizon": 21, "asOf": "2026-10-23",
             "symbol": "AAA", "issuedAt": "2026-10-23T12:30:00Z"},
            {"model": "trend-decay-v1", "horizon": 21, "asOf": "2026-10-23",
             "symbol": "BBB", "issuedAt": "2026-10-23T12:31:00Z"},
        ])
        rows = issue_rows(issued, {"forecasts/archive/2026-10.csv": stream.getvalue().encode()},
                          datetime(2026, 10, 23, 12, 28, tzinfo=timezone.utc))
        self.assertEqual([row[0] for row in rows["2026-10-23"]], ["AAA"])

    def test_metrics_use_full_cohort_denominators_and_percent_units(self):
        rows = [
            {"actualReturn": 0.05, "targetPrice": 105.0,
             "methods": {"candidate": {"predictedReturn": 0.03, "predictedPrice": 103.0}}},
            {"actualReturn": -0.05, "targetPrice": 95.0,
             "methods": {"candidate": {"predictedReturn": -0.03, "predictedPrice": 97.0}}},
            {"actualReturn": 0.0, "targetPrice": 100.0,
             "methods": {"candidate": {"predictedReturn": -0.03, "predictedPrice": 97.0}}},
        ]
        result = metric(rows, "candidate")
        self.assertAlmostEqual(result["mape"], 2.336675)
        self.assertAlmostEqual(result["returnMaePctPoints"], 7.0 / 3.0)
        self.assertEqual(result["upRecall"], 100.0)
        self.assertEqual(result["downRecall"], 100.0)
        self.assertEqual(result["downWarningPrecision"], 50.0)
        self.assertAlmostEqual(result["falseDownWarningRate"], 100.0 / 3.0)
        self.assertEqual(result["n"], 3)

    def test_joint_gate_requires_all_five_origins_and_two_down_dates(self):
        one_origin = {name: [{"actualDown": 1}] for name in ("v5", "simpleTrend", "fixed50", "downsideOverride")}
        result = joint_gate(one_origin)
        self.assertFalse(result["evaluable"])
        self.assertFalse(result["passed"])

    def test_joint_gate_uses_the_preregistered_candidate_checks(self):
        origin_metrics = {name: [] for name in ("v5", "simpleTrend", "fixed50", "downsideOverride")}
        values = {
            "v5": (5.0, 5.0, 40.0, 0.0, 100.0, 0.0),
            "simpleTrend": (6.0, 6.0, 60.0, 50.0, 100.0, 0.0),
            "fixed50": (4.9, 5.0, 60.0, 50.0, 100.0, 0.0),
            "downsideOverride": (5.0, 4.5, 40.0, 50.0, 100.0, 0.0),
        }
        for index in range(5):
            for name, (mape, mae, up, down, precision, false_rate) in values.items():
                origin_metrics[name].append({
                    "actualDown": 1 if index < 2 else 0,
                    "downWarnings": 1 if name != "v5" else 0,
                    "mape": mape,
                    "returnMaePctPoints": mae,
                    "upRecall": up,
                    "downRecall": down,
                    "downWarningPrecision": precision,
                    "falseDownWarningRate": false_rate,
                })
        result = joint_gate(origin_metrics)
        self.assertTrue(result["evaluable"])
        self.assertTrue(result["passed"])
        self.assertEqual(result["candidateChecks"], {"fixed50": True, "downsideOverride": True})
        self.assertFalse(result["productionPromotion"])


if __name__ == "__main__":
    unittest.main()
