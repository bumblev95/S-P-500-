"""Execute publication checks without any stock/market snapshot dependencies."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ('test_crypto_page.cjs', 'test_perp.cjs', 'test_decision_support.cjs')


class CryptoValidationBoundaryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for directory in ('assets', 'crypto', 'scripts'):
            (self.root/directory).mkdir()
        for name in ('crypto.js', 'spot-forecast.js', 'perp-engine.js', 'perp-page.js',
                     'decision-support.js', 'market-visuals.js'):
            shutil.copyfile(ROOT/'assets'/name, self.root/'assets'/name)
        for name in ('latest.json', 'learned.json'):
            shutil.copyfile(ROOT/'crypto'/name, self.root/'crypto'/name)
        for name in (*CHECKS, 'check_crypto.sh'):
            shutil.copyfile(ROOT/'scripts'/name, self.root/'scripts'/name)

    def run_checks(self):
        return subprocess.run(['bash', 'scripts/check_crypto.sh'], cwd=self.root,
                              text=True, capture_output=True, timeout=60)

    def test_crypto_validation_works_without_stock_or_market_snapshots(self):
        for directory in ('market', 'forecasts', 'ml'):
            self.assertFalse((self.root/directory).exists())
        # A broken stock-only test must not gate crypto publication.
        (self.root/'scripts/test_technical_guide.cjs').write_text("throw Error('unrelated stock failure');")
        result = self.run_checks()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_every_crypto_and_shared_check_remains_fatal(self):
        for name in CHECKS:
            with self.subTest(check=name):
                target = self.root/'scripts'/name
                original = target.read_text()
                target.write_text("throw Error('injected safety check failure');")
                try:
                    result = self.run_checks()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('injected safety check failure', result.stderr)
                finally:
                    target.write_text(original)

    def test_missing_crypto_page_check_is_fatal(self):
        (self.root/'scripts/test_crypto_page.cjs').unlink()
        result = self.run_checks()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('test_crypto_page.cjs', result.stderr)


if __name__ == '__main__':
    unittest.main()
