import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    import pandas as pd
    import update_eod_prices as eod
except ImportError:
    eod = None


@unittest.skipIf(eod is None, "pandas/yfinance required for the price pipeline tests")
class PricePipelineTests(unittest.TestCase):
    def test_public_mode_never_reads_sheet_and_preserves_failed_ticker(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/"prices/latest_prices.csv"
            target.parent.mkdir()
            target.write_text("symbol,date,close,source\nAAA,2026-09-09,100,old\nBBB,2026-09-01,50,old\n")
            dates = pd.bdate_range(end="2026-09-10", periods=260)
            frame = pd.DataFrame({"Close":[100+i/100 for i in range(260)],
                                  "Adj Close":[(100+i/100)/2 for i in range(260)],
                                  "High":[101+i/100 for i in range(260)],
                                  "Low":[99+i/100 for i in range(260)],
                                  "Open":[100+i/100 for i in range(260)],
                                  "Volume":[1000]*260}, index=dates)
            downloaded = pd.concat({"AAA":frame}, axis=1)
            with patch.object(eod,"OUT_PATH",target), patch.object(eod,"read_symbols") as shared, \
                    patch.object(eod,"download_public_chart",return_value=downloaded), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(eod.main(["--public-prices-only"]),0)
                shared.assert_not_called()
            rows = pd.read_csv(target).set_index("symbol")
            self.assertEqual(rows.loc["AAA","date"],"2026-09-10")
            self.assertEqual(rows.loc["BBB","date"],"2026-09-01")
            self.assertEqual(rows.loc["BBB","close"],50)
            self.assertEqual(rows.loc["AAA","open"],102.59)
            self.assertEqual(rows.loc["AAA","high"],103.59)
            self.assertEqual(rows.loc["AAA","low"],101.59)
            self.assertTrue(pd.isna(rows.loc["BBB","high"]))
            saved = json.loads((target.parent/"history/AAA.json").read_text())
            self.assertEqual(len(saved["prices"]),260)
            self.assertEqual(saved["prices"][-1]["close"],102.59)
            self.assertEqual(saved["prices"][-1]["high"],103.59)
            self.assertEqual(saved["prices"][-1]["low"],101.59)
            self.assertEqual(saved["prices"][-1]["open"],102.59)

    def test_invalid_or_missing_provider_ohlc_is_not_filled(self):
        cases = [
            ({"Open":100,"High":99,"Low":98}, {}),
            ({"Open":100,"High":101,"Low":0}, {}),
            ({"Open":100,"High":float("inf"),"Low":99}, {}),
            ({"Open":100,"High":101,"Low":float("nan")}, {}),
            ({"Close":100}, {}),
            ({"Open":102,"High":101,"Low":99}, {"high":101,"low":99}),
            ({"Open":float("inf"),"High":101,"Low":99}, {"high":101,"low":99}),
        ]
        for supplied, expected in cases:
            with self.subTest(supplied=supplied):
                self.assertEqual(eod.ohlc_fields(pd.Series(supplied),100),expected)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root/"prices/latest_prices.csv"
            target.parent.mkdir()
            target.write_text("symbol,date,close\nAAA,2026-09-09,100\n")
            dates = pd.bdate_range(end="2026-09-10", periods=260)
            frame = pd.DataFrame({"Close":[100]*260,"Adj Close":[50]*260,
                                  "High":[101]*259+[99],"Low":[99]*260,
                                  "Open":[100]*260,"Volume":[1000]*260},index=dates)
            with patch.object(eod,"OUT_PATH",target), \
                    patch.object(eod,"download_public_chart",return_value=pd.concat({"AAA":frame},axis=1)), \
                    contextlib.redirect_stdout(io.StringIO()):
                eod.main(["--public-prices-only"])
            row = pd.read_csv(target).iloc[0]
            for key in ("open","high","low"):
                self.assertTrue(pd.isna(row[key]))
            self.assertEqual(row["close"],100)
            self.assertEqual(row["adjClose"],50)
            from build_forecasts import build
            with contextlib.redirect_stdout(io.StringIO()):
                published = build(root,now="2026-09-10T23:00:00Z")
            latest = published["stocks"]["AAA"]["history"][-1]
            self.assertEqual(latest["close"],100)
            for key in ("open","high","low"):
                self.assertNotIn(key,latest)
            self.assertEqual(published["stocks"]["AAA"]["history"][-2]["high"],101)

    def test_total_provider_failure_keeps_previous_file_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/"prices/latest_prices.csv"
            target.parent.mkdir()
            original = b"symbol,date,close\nAAA,2026-09-10,100\n"
            target.write_bytes(original)
            with patch.object(eod,"OUT_PATH",target), \
                    patch.object(eod,"download_public_chart",return_value=pd.DataFrame()), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    eod.main(["--public-prices-only"])
            self.assertEqual(target.read_bytes(),original)

    def test_csv_ohlc_precision_matches_close_at_provider_low(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/"prices/latest_prices.csv"
            target.parent.mkdir()
            target.write_text("symbol,date,close\nAAA,2026-10-01,535\n")
            close = 535.9500122070312
            frame = pd.DataFrame({"Close":[close],"Adj Close":[close-1],
                                  "Open":[546.47998046875],"High":[549.8900146484375],
                                  "Low":[close],"Volume":[487600]},
                                 index=pd.to_datetime(["2026-10-02"]))
            with patch.object(eod,"OUT_PATH",target), \
                    patch.object(eod,"download_public_chart",return_value=pd.concat({"AAA":frame},axis=1)), \
                    contextlib.redirect_stdout(io.StringIO()):
                eod.main(["--public-prices-only"])
            row = pd.read_csv(target).iloc[0]
            self.assertEqual(row["low"],row["close"])
            self.assertLessEqual(row["low"],row["open"])
            self.assertLessEqual(row["open"],row["high"])
            bar = json.loads((target.parent/"history/AAA.json").read_text())["prices"][-1]
            self.assertEqual(bar["close"],close)
            self.assertEqual(bar["low"],close)
