from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from build_stock_snapshots import explore_trend, publish


class StockSnapshotsTest(unittest.TestCase):
    def test_directory_trend_uses_actual_sorted_closes(self):
        start = date(2026, 11, 1)
        history = [{"date": (start + timedelta(days=i)).isoformat(), "close": 100 + i}
                   for i in range(22)]
        entry = {"asOf": "2026-11-22", "history": list(reversed(history)) + [
            {"date": "2026-11-23", "close": 900},
        ]}
        trend = explore_trend(entry)
        self.assertEqual(trend["from"], "2026-11-01")
        self.assertEqual(trend["asOf"], "2026-11-22")
        self.assertEqual(trend["returnPct"], 21)
        self.assertEqual((len(trend["points"]), trend["points"][0], trend["points"][-1]), (9, 0, 100))
        self.assertIsNone(explore_trend({**entry, "history": history[:-1]}))

    def test_projection_preserves_selected_stock_and_risk_inputs(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "latest.json"
            out = base / "by-symbol"
            out.mkdir()
            (out / "OLD.json").write_text("{}")
            spy = {"symbol": "SPY", "price": 100, "asOf": "2026-11-20", "inputs": {"ma200": 95},
                   "history": [{"close": 100}] * 253}
            stock = {"symbol": "AAPL", "price": 200, "name": "Apple", "asOf": "2026-11-20",
                     "inputs": {"ma200": 110}, "fallback": {"preserve": True}}
            source.write_text(json.dumps({"schemaVersion": 1, "stocks": {"SPY": spy, "AAPL": stock}}))
            publish(source, out)
            catalog = json.loads((out / "index.json").read_text())
            revision = sha256(source.read_bytes()).hexdigest()
            self.assertEqual(catalog["revision"], revision)
            self.assertEqual(catalog["items"][0], {"symbol": "AAPL", "name": "Apple"})
            self.assertEqual(len(catalog["risk"]["SPY"]["history"]), 63)
            self.assertEqual(catalog["risk"]["AAPL"]["inputs"], {"ma200": 110})
            self.assertEqual(json.loads((out / "AAPL.json").read_text()), {"revision": revision, "stock": stock})
            self.assertFalse((out / "OLD.json").exists())
            self.assertEqual(json.loads((out / "explore-trends.json").read_text()),
                             {"schemaVersion": 1, "revision": revision, "trends": {}})


if __name__ == "__main__":
    unittest.main()
