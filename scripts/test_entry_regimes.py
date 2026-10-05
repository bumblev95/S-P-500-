"""Temporal leakage, exposure timing, and hand-calculated accounting tests."""
import copy
from datetime import datetime, timedelta, timezone
import math
import unittest

from analyze_entry_regimes import (account_days, all_groups, benchmark_return, capture,
                                  compound, regime_features, summarize, volatility_state)


CFG = {"slip": .0005, "fee": .0005}


def prices(count=270):
    first = datetime(2016, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(count):
        stamp = first + timedelta(days=i)
        price = 100 + .1 * i
        rows.append({"date": stamp.date().isoformat(), "t": int(stamp.timestamp() * 1000),
                     "end": int((stamp + timedelta(hours=7)).timestamp() * 1000),
                     "open": price, "close": price, "low": price - 1, "high": price + 1})
    return rows


class RegimeTests(unittest.TestCase):
    def test_same_day_and_future_prices_cannot_change_regime(self):
        spy = prices()
        i = 215
        expected = regime_features(spy, i)
        changed = copy.deepcopy(spy)
        for row in changed[i:]:
            row["close"] *= 20
        self.assertEqual(regime_features(changed, i), expected)
        self.assertEqual(regime_features(spy[:i + 1], i), expected)
        self.assertEqual(expected["asOf"], spy[i - 1]["date"])
        changed[i - 1]["close"] /= 50
        self.assertNotEqual(regime_features(changed, i), expected)

    def test_exact_warmup_and_lookbacks(self):
        spy = prices()
        self.assertIsNone(regime_features(spy, 199))
        self.assertIsNotNone(regime_features(spy, 200))
        q = regime_features(spy, 215)
        self.assertAlmostEqual(q["sma200Known"], sum(r["close"] for r in spy[15:215]) / 200)
        self.assertAlmostEqual(q["trend63Known"], spy[214]["close"] / spy[151]["close"] - 1)
        changed = copy.deepcopy(spy)
        changed[14]["close"] = 100000
        self.assertEqual(regime_features(changed, 215), q)
        changed[15]["close"] = 100000
        self.assertNotEqual(regime_features(changed, 215)["sma200Known"], q["sma200Known"])

    def test_flat_prices_and_boundary_assignments(self):
        spy = prices()
        for r in spy:
            r["close"] = 100
        q = regime_features(spy, 210)
        self.assertEqual((q["sma200"], q["trend63"], q["volatility63"]), ("above", "downFlat", "low"))
        self.assertEqual(q["volatility63Known"], 0)
        self.assertEqual(volatility_state(.15 - 1e-9), "low")
        self.assertEqual(volatility_state(.15), "medium")
        self.assertEqual(volatility_state(.25 - 1e-9), "medium")
        self.assertEqual(volatility_state(.25), "high")

    def test_realized_volatility_uses_63_sample_log_returns(self):
        spy = prices()
        # The prior 63 returns alternate +/- 0.01 log returns.
        spy[146]["close"] = 100
        known = []
        for i in range(147, 210):
            r = .01 if i % 2 else -.01
            spy[i]["close"] = spy[i - 1]["close"] * math.exp(r)
            known.append(r)
        average = sum(known) / 63
        expected = math.sqrt(sum((r - average) ** 2 for r in known) / 62) * math.sqrt(252)
        self.assertAlmostEqual(regime_features(spy, 210)["volatility63Known"], expected)


class BenchmarkTests(unittest.TestCase):
    def test_zero_weight_stays_cash_including_costs(self):
        for first, last in ((True, False), (False, True), (True, True)):
            self.assertEqual(benchmark_return(.2, 0, first, last, CFG), 0)

    def test_full_weight_matches_single_spy_round_trip(self):
        rets = [.05, -.03, .02]
        net = [benchmark_return(r, 1, i == 0, i == 2, CFG) for i, r in enumerate(rets)]
        buy = (1 + CFG["fee"]) * (1 + CFG["slip"])
        sell = (1 - CFG["fee"]) * (1 - CFG["slip"])
        expected = 1.05 * .97 * 1.02 / buy * sell - 1
        self.assertAlmostEqual(compound(net), expected)

    def test_cash_sleeve_endpoint_costs_apply_only_to_spy(self):
        buy, sell = (1.0005 ** 2), (.9995 ** 2)
        first = benchmark_return(.1, .5, True, False, CFG)
        last = benchmark_return(-.1, .5, False, True, CFG)
        self.assertAlmostEqual(first, .5 + .5 * 1.1 / buy - 1)
        self.assertAlmostEqual(last, .5 + .5 * .9 * sell - 1)
        self.assertAlmostEqual(compound([first, last]), (.5 + .5 * 1.1 / buy) * (.5 + .5 * .9 * sell) - 1)

    def test_lagged_exposure_is_prior_close_not_same_day(self):
        spy = prices()
        bars = spy[210:213]
        equity = 10000
        curve = [{"date": bars[0]["date"], "at": bars[0]["t"], "phase": "beforeFirstOpen",
                  "equity": equity, "cash": equity, "exposure": 0}]
        for bar, weight in zip(bars, [0, .8, .1]):
            curve.append({"date": bar["date"], "at": bar["end"], "phase": "",
                          "equity": equity, "cash": equity * (1 - weight), "exposure": equity * weight})
        liquidation = equity - 1000 * (1 - .9995 ** 2)
        portfolio = {"initial": equity, "meanExposure": .3, "markEquity": equity,
                     "liquidationEquivalentEquity": liquidation}
        days = account_days(spy, curve, portfolio, CFG, bars[0]["date"], bars[-1]["date"])
        self.assertEqual([d["laggedExposure"] for d in days], [0, 0, .8])
        self.assertAlmostEqual(days[1]["spyCashLaggedReturn"], 0)
        self.assertAlmostEqual(compound([d["strategyReturn"] for d in days]), liquidation / equity - 1)
        curve[-1]["date"] = "2099-01-01"
        with self.assertRaisesRegex(ValueError, "trading dates"):
            account_days(spy, curve, portfolio, CFG, bars[0]["date"], bars[-1]["date"])


def day(index, r, price_r):
    return {"index": index, "date": f"2020-01-0{index + 1}", "year": "2020",
            "sma200": "above", "trend63": "up", "volatility63": "low",
            "sma200Trend63": "above|up", "joint": "above|up|low", "exposure": .5,
            "laggedExposure": .4, "strategyReturn": r, "spyPriceReturn": price_r,
            "spyNetReturn": price_r, "spyCashFullMeanReturn": .5 * price_r,
            "spyCashLaggedReturn": .4 * price_r, "first": False, "last": False}


class AttributionTests(unittest.TestCase):
    def test_capture_signs_zero_days_and_empty_samples(self):
        self.assertAlmostEqual(capture([.02, .01, .2], [.1, -.1, 0], [.1, -.1, 0], True), 20)
        self.assertAlmostEqual(capture([.02, .01, .2], [.1, -.1, 0], [.1, -.1, 0], False), -10)
        self.assertIsNone(capture([0], [0], [0], True))
        self.assertIsNone(capture([.01], [0], [.1], True))

    def test_stitched_and_contiguous_drawdowns_differ(self):
        days = [day(0, -.1, -.1), day(1, .2, .2), day(2, -.1, -.1)]
        q = summarize(days, [0, 2], CFG)
        self.assertEqual(q["episodes"], 2)
        self.assertAlmostEqual(q["series"]["strategy"]["return"], -.19)
        self.assertAlmostEqual(q["series"]["strategy"]["maxDrawdownStitched"], .19)
        self.assertAlmostEqual(q["series"]["strategy"]["maxDrawdownContinuousEpisode"], .1)

    def test_log_decomposition_adds_exactly_and_level_vs_timing_separate(self):
        q = summarize([day(0, .02, .1), day(1, -.01, -.1)], [0, 1], CFG)
        a = q["attribution"]
        expected = 100 * math.log((1.02 * .99) / (1.1 * .9))
        self.assertAlmostEqual(a["cashLevelLogPP"] + a["exposureTimingLogPP"] + a["residualLogPP"], expected)
        self.assertAlmostEqual(a["totalExcessLogPP"], expected)
        self.assertNotEqual(a["exposureTimingLogPP"], 0)

    def test_empty_regimes_remain_explicit_and_axes_partition(self):
        days = [day(0, .02, .1), day(1, -.01, -.1)]
        groups = all_groups(days)
        joint = [g for g in groups if g[0] == "joint"]
        self.assertEqual(len(joint), 12)
        self.assertEqual(sum(len(g[2]) for g in joint), 2)
        empty = summarize(days, [], CFG)
        self.assertEqual(empty["sessions"], 0)
        self.assertEqual(empty["episodes"], 0)
        self.assertIsNone(empty["meanExposure"])
        self.assertIsNone(empty["series"]["strategy"]["upCapture"])
        self.assertIsNone(empty["series"]["strategy"]["return"])
        self.assertIsNone(empty["attribution"])


if __name__ == "__main__":
    unittest.main()
