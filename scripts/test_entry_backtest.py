import copy
import unittest

from collect_entry_backtest import normalize


class NormalizeTests(unittest.TestCase):
    def payload(self):
        return {"chart": {"result": [{"meta": {"symbol": "AAA", "currency": "USD",
                                               "exchangeTimezoneName": "America/New_York"},
            "timestamp": [1790947800, 1791207000],
            "indicators": {"quote": [{"open": [99, 103], "high": [102, 105],
                                      "low": [98, 101], "close": [100, 104], "volume": [10, 20]}],
                           "adjclose": [{"adjclose": [1, 2]}]}}]}}

    def test_cutoff_and_quote_basis(self):
        bars, rejected = normalize(self.payload(), "AAA", "2026-10-02")
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["close"], 100)
        self.assertEqual(bars[0]["date"], "2026-10-02")
        self.assertEqual(bars[0]["end"], 1790971200000)
        self.assertEqual(rejected, [])

    def test_missing_ohlc_is_not_fabricated(self):
        p = self.payload()
        p["chart"]["result"][0]["indicators"]["quote"][0]["open"][0] = None
        with self.assertRaisesRegex(ValueError, "Latest requested"):
            normalize(p, "AAA", "2026-10-02")

    def test_signal_price_matches_python_csv_precision(self):
        p = self.payload()
        q = p["chart"]["result"][0]["indicators"]["quote"][0]
        q["close"][0] = 2.0078125
        q["open"][0], q["high"][0], q["low"][0] = 2, 3, 1
        bars, _ = normalize(p, "AAA", "2026-10-02")
        self.assertEqual(bars[0]["close"], 2.0078125)
        self.assertEqual(bars[0]["signalPrice"], 2.007812)

    def test_symbol_and_duplicate_validation(self):
        with self.assertRaisesRegex(ValueError, "symbol mismatch"):
            normalize(self.payload(), "BBB", "2026-10-02")
        p = copy.deepcopy(self.payload())
        p["chart"]["result"][0]["timestamp"][1] = p["chart"]["result"][0]["timestamp"][0]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            normalize(p, "AAA", "2026-10-02")


if __name__ == "__main__":
    unittest.main()
