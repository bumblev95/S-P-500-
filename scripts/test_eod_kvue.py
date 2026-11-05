"""November 2026 retirement boundary; synthetic prices never serve as evidence."""
import contextlib
import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

import build_forecasts
import eod_publication as publication
import eod_symbol_mapping as mapping
import update_eod_prices as collector
import test_eod_publication as publication_tests


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        value = datetime(2026, 11, 5, 8, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


class KvueTests(unittest.TestCase):
    def test_official_dates_and_separate_identities(self):
        old = ['KVUE', 'SPY', 'SOXX']
        for day in ('2026-10-30', '2026-11-02', '2026-11-03'):
            self.assertEqual(mapping.replace_constituents(old, day), (old, []))
        current, changes = mapping.replace_constituents(old, '2026-11-04')
        self.assertEqual(current, ['OKTA', 'SPY', 'SOXX'])
        self.assertEqual(len(current), len(old))
        mapping.verify_universe_changes({'symbols': current, 'universeChanges': changes}, '2026-11-04')
        for symbol in ('KVUE', 'OKTA', 'KMB'):
            self.assertIsNone(mapping.transition(symbol, '2026-11-04'))
        mapping.assert_trading_session('KVUE', '2026-10-30')
        for day in ('2026-11-02', '2026-11-03', '2026-11-04'):
            with self.assertRaisesRegex(ValueError, 'exchange trading ended 2026-10-30'):
                mapping.assert_trading_session('KVUE', day)
        with self.assertRaises(ValueError):
            mapping.replace_constituents(old + ['OKTA'], '2026-11-04')
        with self.assertRaises(ValueError):
            mapping.verify_universe_changes({'symbols': current, 'universeChanges': changes}, '2026-11-03')

    def setup_repo(self):
        repo = publication_tests.PublicationTests()
        repo.setUp()
        self.addCleanup(repo.doCleanups)
        repo.symbols = ['KVUE', 'AAA', 'BBB', 'CCC', 'DDD', 'EEE', 'SPY', 'SOXX']
        repo.write_snapshot(repo.root, '2026-10-30', '2026-10-30T22:00:00Z')
        publication.git(repo.root, 'add', '--', *publication.PUBLIC_PATHS)
        publication.git(repo.root, 'commit', '-m', 'Synthetic pre-retirement snapshot')
        publication.git(repo.root, 'push', 'origin', 'main')
        repo.original = repo.remote_head()
        return repo

    def collect(self, repo, missing=False):
        requested = []
        def download(symbols):
            requested.extend(symbols)
            days = pd.bdate_range(end='2026-11-04', periods=270)
            # Explicitly synthetic, independent OKTA history with its own price.
            return pd.concat({s: pd.DataFrame({'Close': 200 if s == 'OKTA' else 100,
                'Open': 100, 'High': 201, 'Low': 99, 'Volume': 1000}, index=days)
                for s in symbols if not (missing and s == 'OKTA')}, axis=1)
        receipt_path = repo.base / 'kvue-request.json'
        with patch.object(collector, 'OUT_PATH', repo.root / 'prices/latest_prices.csv'), \
             patch.object(collector, 'datetime', FixedClock), \
             patch.object(collector, 'download_public_chart', side_effect=download), \
             patch.object(collector, 'read_symbols', side_effect=AssertionError('No Sheets in public-only mode')), \
             contextlib.redirect_stdout(io.StringIO()):
            collector.main(['--public-prices-only', '--receipt', str(receipt_path)])
            build_forecasts.build(repo.root, '2026-11-05T08:01:00Z')
        repo.receipt = json.loads(receipt_path.read_text())
        self.assertIn('OKTA', requested)
        self.assertNotIn('KVUE', requested)

    def test_independent_okta_snapshot_passes_original_atomic_gate(self):
        repo = self.setup_repo()
        self.collect(repo)
        manifest = repo.publish()
        self.assertEqual(manifest['symbolCount'], 8)
        self.assertEqual(manifest['asOf'], '2026-11-04')
        self.assertNotIn('prices/history/KVUE.json', manifest['historyFiles'])
        self.assertIn('prices/history/OKTA.json', manifest['historyFiles'])

    def test_missing_replacement_or_another_stale_symbol_never_advances_remote(self):
        for missing in (True, False):
            repo = self.setup_repo()
            self.collect(repo, missing)
            if not missing:
                rows = repo.prices()
                next(r for r in rows if r['symbol'] == 'AAA')['date'] = '2026-11-03'
                repo.write_prices(rows)
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                repo.publish()
            self.assertEqual(repo.remote_head(), repo.original)
            self.assertEqual(publication.staged_paths(repo.root), [])

    def test_relabelled_retired_price_is_rejected_even_with_coherent_files(self):
        repo = self.setup_repo()
        repo.receipt = repo.write_snapshot(repo.root, '2026-11-04', '2026-11-04T22:00:00Z')
        with self.assertRaisesRegex(ValueError, 'KVUE: exchange trading ended'):
            repo.publish()
        self.assertEqual(repo.remote_head(), repo.original)
        self.assertEqual(publication.staged_paths(repo.root), [])

    def test_published_sheet_html_is_exported_as_csv_without_dropping_bad_rows(self):
        url = 'https://docs.google.com/spreadsheets/d/e/2PACX-test/pubhtml?gid=123&single=true'
        expected = 'https://docs.google.com/spreadsheets/d/e/2PACX-test/pub?gid=123&single=true&output=csv'
        self.assertEqual(collector.sheet_csv_url(url), expected)
        for value in (expected, 'https://example.com/pubhtml?gid=123',
                      'https://docs.google.com.evil.example/spreadsheets/d/e/test/pubhtml'):
            self.assertEqual(collector.sheet_csv_url(value), value)
        with patch.dict('os.environ', {'WATCHLIST_CSV_URL': url}):
            self.assertEqual(collector.read_watchlist_sheet_url(), expected)
        with patch.object(collector.pd, 'read_csv', side_effect=pd.errors.ParserError('bad CSV')) as read, \
             contextlib.redirect_stdout(io.StringIO()) as logs:
            self.assertEqual(collector.read_symbol_frame(expected, 'watchlist'), [])
            self.assertIn('Warning:', logs.getvalue())
            read.assert_called_once_with(expected)


if __name__ == '__main__':
    unittest.main()
