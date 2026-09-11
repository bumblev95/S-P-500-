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
                                  "Adj Close":[100+i/100 for i in range(260)],
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
            saved = json.loads((target.parent/"history/AAA.json").read_text())
            self.assertEqual(len(saved["prices"]),260)
            self.assertEqual(saved["prices"][-1]["close"],102.59)

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
