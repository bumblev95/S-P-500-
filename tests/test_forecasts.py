import csv
import json
import math
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_forecasts as engine


def history(count=1300):
    """Synthetic prices only for logic tests, never user-facing market data."""
    rows, day = [], date(2018, 1, 1)
    while len(rows) < count:
        if day.weekday() < 5:
            i = len(rows)
            rows.append({"date": day.isoformat(),
                         "close": 100 * math.exp(.0002 * i + .07 * math.sin(i / 31)),
                         "volume": 1000})
        day += timedelta(days=1)
    return rows


class ForecastTests(unittest.TestCase):
    def test_published_history_covers_252_return_intervals(self):
        sample = history(350)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "prices/history").mkdir(parents=True)
            (root / "prices/history/TEST.json").write_text(json.dumps({"prices": sample}))
            snapshot = engine.snapshot(sample, len(sample)-1)
            snapshot.update(symbol="TEST", date=sample[-1]["date"])
            with (root / "prices/latest_prices.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(snapshot))
                writer.writeheader()
                writer.writerow(snapshot)
            payload = engine.build(root, sample[-1]["date"] + "T12:00:00Z")
            published = payload["stocks"]["TEST"]["history"]
            self.assertEqual(len(published), 253)
            self.assertEqual(published[0]["date"], sample[-253]["date"])
            self.assertEqual(published[-1]["close"], sample[-1]["close"])

    def test_missing_inputs_never_invent_a_forecast(self):
        row = engine.snapshot(history(250), 249)
        for bad in ("", None, "NaN", "-1"):
            self.assertIsNone(engine.predict({**row, "close": bad}, 21))
        self.assertIsNone(engine.predict({**row, "volatility4m": ""}, 21))
        self.assertIsNone(engine.predict({"close": 100, "volatility4m": .3}, 21))

    def test_constant_price_has_no_artificial_trend_or_width(self):
        sample = history(250)
        for item in sample:
            item["close"] = 100
        for h in engine.HORIZONS:
            pred = engine.predict(engine.snapshot(sample, 249), h)
            self.assertEqual((pred["bear"], pred["base"], pred["bull"]), (100, 100, 100))
            self.assertEqual(pred["direction"], "neutral")

    def test_scale_invariance_and_ordered_positive_ranges(self):
        row = engine.snapshot(history(400), 399)
        for h in engine.HORIZONS:
            pred = engine.predict(row, h)
            scaled = engine.predict({**row, "close": row["close"] * 10}, h)
            self.assertGreater(pred["bear"], 0)
            self.assertLessEqual(pred["bear"], pred["base"])
            self.assertLessEqual(pred["base"], pred["bull"])
            for k in ("bear", "base", "bull"):
                self.assertAlmostEqual(scaled[k], pred[k] * 10)
            self.assertEqual(pred["direction"], scaled["direction"])

    def test_future_prices_cannot_change_forecast_inputs(self):
        sample = history(600)
        original = engine.snapshot(sample, 249)
        for row in sample[250:]:
            row["close"] *= 50
        self.assertEqual(engine.snapshot(sample, 249), original)
        self.assertEqual(engine.predict(original, 84),
                         engine.predict(engine.snapshot(sample, 249), 84))

    def test_backtest_count_uses_nonoverlapping_completed_horizons(self):
        sample = history(900)
        for h in engine.HORIZONS:
            expected = len(range(engine.MIN_TRAIN - 1, len(sample) - h, h))
            result = engine.backtest(sample, h)
            self.assertEqual(result["n"], expected)
            self.assertTrue(0 <= result["directionAccuracy"] <= 1)
            self.assertTrue(0 <= result["rangeCoverage"] <= 1)
            self.assertGreaterEqual(result["baselineMaePct"], 0)
        self.assertEqual(engine.backtest(sample[:200], 21)["n"], 0)

    def record(self, sample, origin=249, horizon=21):
        return {"model": engine.MODEL, "symbol": "TEST",
                "asOf": sample[origin]["date"], "issuedAt": sample[origin]["date"]+"T23:00:00Z",
                **{k:v for k,v in engine.predict(engine.snapshot(sample, origin), horizon).items()
                   if k in engine.FIELDS}}

    def test_issue_archive_is_idempotent_and_never_rewrites_an_old_forecast(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            record = self.record(history())
            engine.archive_records(target, [record, record])
            first = next(target.glob("*.csv")).read_bytes()
            engine.archive_records(target, [{**record, "base": 99999}])
            self.assertEqual(next(target.glob("*.csv")).read_bytes(), first)
            self.assertEqual(len(engine.read_archive(target)), 1)

    def test_issued_evaluation_uses_trading_observations_not_calendar_days(self):
        sample = history(350)
        record = self.record(sample)
        self.assertEqual(engine.score_issued([record], sample[:270], 21)["n"], 0)
        self.assertEqual(engine.score_issued([record], sample[:271], 21)["n"], 1)
        self.assertEqual(engine.score_issued([record], sample[:270], 21)["pending"], 1)

    def test_split_or_late_issue_is_excluded_from_reported_performance(self):
        sample = history(350)
        record = self.record(sample)
        sample[249]["close"] /= 2
        result = engine.score_issued([record], sample, 21)
        self.assertEqual((result["n"], result["revised"]), (0, 1))
        sample = history(350)
        record["issuedAt"] = sample[271]["date"]+"T00:00:00Z"
        result = engine.score_issued([record], sample, 21)
        self.assertEqual((result["n"], result["late"]), (0, 1))

    def test_build_records_only_fresh_valid_data_and_reports_missing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"prices").mkdir()
            columns = ["symbol","date","close","return1m","return3m","return6m","volatility4m"]
            with (root/"prices/latest_prices.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                for symbol, as_of in [("OK","2026-09-10"),("OLD","2026-08-01"),("FUTURE","2027-01-01")]:
                    writer.writerow(dict(zip(columns,[symbol,as_of,100,.03,.05,.1,.3])))
            payload = engine.build(root, "2026-09-11T00:00:00Z")
            self.assertEqual(payload["stocks"]["OK"]["status"], "ready")
            self.assertEqual(payload["stocks"]["OLD"]["status"], "stale")
            self.assertEqual(payload["stocks"]["FUTURE"]["status"], "stale")
            self.assertEqual(payload["stocks"]["OK"]["backtest"]["21"]["n"], 0)
            self.assertEqual(payload["stocks"]["OK"]["issued"]["21"]["pending"], 1)
            self.assertEqual(len(engine.read_archive(root/"forecasts/archive")), 3)
            json.loads((root/"forecasts/latest.json").read_text())


if __name__ == "__main__":
    unittest.main()
