from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from build_stock_snapshots import publish


class StockSnapshotsTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
