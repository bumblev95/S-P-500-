"""Causal boundaries, immutable records, missing-data and maturity checks."""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import home_top3_study as study


class ProspectiveTop3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cal = study.calendar()
        cls.seed_folder = study.ROOT / study.FOLDER

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'study'
        shutil.copytree(self.seed_folder, self.folder)
        # Tests use only the fixed genesis, even after live collection grows.
        for p in sorted((self.folder / 'ledger').glob('*.json'))[1:]:
            p.unlink()
        (self.folder / 'latest.json').unlink()
        self.state = study.load(self.folder, self.cal)
        self.first = self.state['observations'][0]
        self.symbols = [q['symbol'] for q in self.first['cards']]

    def snapshot(self, day):
        at = self.cal.session_close(day).to_pydatetime() + timedelta(hours=3)
        stamp = study.iso(at)
        ranks = copy.deepcopy(self.first['rankings'])
        ranks.update(asOf=day, evaluatedAt=stamp, priceGeneratedAt=stamp, marketGeneratedAt=stamp)
        for side in ('buy', 'sell'):
            for q in ranks[side]:
                q['asOf'] = day
        forecasts = {'generatedAt': stamp, 'stocks': {
            s: {'asOf': day, 'price': 100., 'sourceUpdatedAt': stamp, 'history': []}
            for s in self.symbols}}
        return {'generatedAt': stamp, 'rankings': ranks}, forecasts, at

    def prices(self, horizon=20, missing=None, now=None):
        entry = self.first['entryDate']
        target = self.first['targetDates'][str(horizon)]
        at = now or self.cal.session_close(target).to_pydatetime() + timedelta(hours=3)
        stamp = study.iso(at)
        data = {'generatedAt': stamp, 'stocks': {}}
        for symbol in [*self.symbols, 'SPY']:
            bars = []
            for i, session in enumerate(self.cal.sessions_in_range(entry, target)):
                date = study.session_date(session)
                if missing == (symbol, date):
                    continue
                bars.append({'date': date, 'close': (200. if symbol == 'SPY' else 100.) *
                             (1 + i * (.0005 if symbol == 'SPY' else .001))})
            data['stocks'][symbol] = {'asOf': target, 'sourceUpdatedAt': stamp, 'history': bars}
        return data, at

    def ingest(self, horizon=20, missing=None):
        data, at = self.prices(horizon, missing)
        study.capture_prices(self.folder, self.state, data, at, {'test': True}, self.cal)
        return data, at

    def rows(self, horizon):
        return study.report(self.state, self.cal)['outcomes'][:6] if horizon == 20 else study.report(self.state, self.cal)['outcomes'][6:]

    def test_first_operational_observation_preserves_all_original_fields(self):
        self.assertEqual(self.first['observedAt'], '2026-10-04T20:07:32Z')
        self.assertEqual(self.first['basisDate'], '2026-10-02')
        self.assertEqual(self.first['entryDate'], '2026-10-05')
        self.assertEqual(self.first['rankings']['eligibleCount'], 505)
        self.assertEqual([q['symbol'] for q in self.first['cards']], ['ILMN', 'RVTY', 'FTNT', 'AON', 'APP', 'CCI'])
        self.assertEqual([q['code'] for q in self.first['cards'][:3]], ['breakout', 'pullback', 'breakout'])
        self.assertTrue(all(q['selection'] == 'relative' for q in self.first['cards'][:3]))
        self.assertTrue(all(q['holdingCode'] == 'reduce' and q['selection'] == 'signal' for q in self.first['cards'][3:]))
        self.assertTrue(all(q['return'] is None for q in study.report(self.state, self.cal)['outcomes']))

    def test_pre_policy_and_historical_backfill_rejected(self):
        home, prices, at = self.snapshot('2026-10-01')
        with self.assertRaises(ValueError):
            study.capture(self.folder, self.state, home, prices, at, {}, self.cal)
        with self.assertRaises(ValueError):
            study.observation(home, prices, '2026-10-04T19:53:07Z', {}, self.cal)

    def test_same_close_date_changed_rankings_and_weekend_are_noop(self):
        before = {p.name: p.read_bytes() for p in (self.folder / 'ledger').glob('*.json')}
        home, prices, at = self.snapshot('2026-10-02')
        home['rankings']['buy'][0].update(score=7, code='buy', selection='signal')
        at = study.instant('2026-10-04T23:59:59Z')
        study.capture(self.folder, self.state, home, prices, at, {}, self.cal)
        study.capture_prices(self.folder, self.state, prices, at, {}, self.cal)
        self.assertEqual(len(self.state['observations']), 1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.folder / 'ledger').glob('*.json')})

    def test_new_day_recorded_at_real_observation_not_close_or_generation(self):
        home, prices, at = self.snapshot('2026-10-05')
        actual = at + timedelta(hours=2)
        study.capture(self.folder, self.state, home, prices, actual, {'test': True}, self.cal)
        last = self.state['observations'][-1]
        self.assertEqual(last['observedAt'], study.iso(actual))
        self.assertNotEqual(last['observedAt'], home['generatedAt'])
        self.assertEqual(last['entryDate'], '2026-10-06')
        self.assertEqual(len(study.load(self.folder, self.cal)['observations']), 2)

    def test_no_synthetic_missing_date_cohorts(self):
        home, prices, at = self.snapshot('2026-10-06')
        study.capture(self.folder, self.state, home, prices, at, {}, self.cal)
        report = study.report(self.state, self.cal)
        self.assertEqual(report['observations'], 2)
        self.assertEqual(report['missedRankingDates'], ['2026-10-05'])

    def test_future_timestamp_mixed_date_and_signal_relabel_rejected(self):
        home, prices, at = self.snapshot('2026-10-05')
        future = copy.deepcopy(prices)
        future['generatedAt'] = study.iso(at + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            study.observation(home, future, study.iso(at), {}, self.cal)
        home['rankings']['buy'][0]['asOf'] = '2026-10-02'
        with self.assertRaises(ValueError):
            study.observation(home, prices, study.iso(at), {}, self.cal)
        home['rankings']['buy'][0]['asOf'] = '2026-10-05'
        home['rankings']['buy'][0]['selection'] = 'signal'
        with self.assertRaises(ValueError):
            study.observation(home, prices, study.iso(at), {}, self.cal)

    def test_next_open_boundary_weekends_holidays_dst_and_early_close(self):
        self.assertEqual(study.next_entry('2026-10-05T13:29:59Z', self.cal), '2026-10-05')
        self.assertEqual(study.next_entry('2026-10-05T13:30:00Z', self.cal), '2026-10-06')
        self.assertEqual(study.next_entry('2026-11-26T23:00:00Z', self.cal), '2026-11-27')
        self.assertEqual(self.cal.session_close('2026-11-27').hour, 18)
        self.assertEqual(self.cal.session_open('2026-11-02').hour, 14)

    def test_future_unfinished_bars_never_enter_ledger(self):
        target = self.first['targetDates']['20']
        now = self.cal.session_close(target).to_pydatetime() + timedelta(minutes=14)
        data, at = self.prices(now=now)
        study.capture_prices(self.folder, self.state, data, at, {}, self.cal)
        self.assertNotIn(('SPY', target), self.state['prices'])
        self.assertTrue(all(q['status'] == 'pending_horizon' for q in self.rows(20)))
        data['generatedAt'] = study.iso(now + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            study.capture_prices(self.folder, self.state, data, now, {}, self.cal)

    def test_twenty_sessions_use_future_anchor_and_exact_matched_spy_dates(self):
        self.ingest(20)
        self.assertTrue(all(q['status'] == 'mature' for q in self.rows(20)))
        for row in self.rows(20):
            self.assertAlmostEqual(row['return'], .02)
            self.assertAlmostEqual(row['spyReturn'], .01)
            self.assertAlmostEqual(row['excessReturn'], .01)
            self.assertEqual(row['entryClose'], 100.)
            self.assertNotEqual(row['entryClose'], row['referenceClose'])
        self.assertTrue(all(q['status'] == 'pending_horizon' for q in self.rows(63)))

    def test_sixty_three_sessions_require_separate_maturity(self):
        self.ingest(63)
        for row in self.rows(63):
            self.assertEqual(row['status'], 'mature')
            self.assertAlmostEqual(row['return'], .063)
            self.assertAlmostEqual(row['excessReturn'], .0315)

    def test_missing_spy_day_does_not_slide_horizon(self):
        date = study.session_date(self.cal.session_offset(self.first['entryDate'], 7))
        self.ingest(20, ('SPY', date))
        self.assertTrue(all(q['status'] == 'missing_benchmark_session' for q in self.rows(20)))
        self.assertTrue(all(q['return'] is None for q in self.rows(20)))

    def test_removed_or_missing_stock_not_dropped_from_sample(self):
        self.ingest(20, ('APP', self.first['targetDates']['20']))
        report = study.report(self.state, self.cal)
        self.assertEqual(len(self.rows(20)), 6)
        self.assertEqual(report['horizons']['20']['statusCounts']['missing_stock_endpoint'], 1)
        self.assertEqual(report['horizons']['20']['fullyMatureCohorts'], 0)
        self.assertEqual(report['horizons']['20']['groups']['buy']['matureRows'], 0)

    def test_missing_endpoint_can_be_added_later_without_rank_rewrite(self):
        self.ingest(20, ('APP', self.first['targetDates']['20']))
        initial = copy.deepcopy(self.state['observations'])
        self.ingest(20)
        self.assertTrue(all(q['status'] == 'mature' for q in self.rows(20)))
        self.assertEqual(initial, self.state['observations'])
        study.load(self.folder, self.cal)

    def test_price_revisions_quarantine_instead_of_rewriting_returns(self):
        data, at = self.ingest(20)
        original = self.state['prices'][('ILMN', self.first['entryDate'])]
        data['stocks']['ILMN']['history'][0]['close'] *= .5
        study.capture_prices(self.folder, self.state, data, at, {}, self.cal)
        self.assertEqual(self.state['prices'][('ILMN', self.first['entryDate'])], original)
        self.assertEqual(self.rows(20)[0]['status'], 'price_revision_quarantined')
        self.assertIsNone(self.rows(20)[0]['return'])
        study.load(self.folder, self.cal)

    def test_small_sample_has_no_aggregate_performance_claim(self):
        self.ingest(63)
        report = study.report(self.state, self.cal)
        for h in ('20', '63'):
            for side in ('buy', 'sell'):
                group = report['horizons'][h]['groups'][side]
                self.assertEqual(group['matureRows'], 3)
                self.assertEqual(group['matureCohorts'], 1)
                self.assertIsNone(group['meanExcessReturn'])
                self.assertEqual(group['status'], 'insufficient_mature_cohorts')
        self.assertFalse(report['performanceValidated'])
        self.assertFalse(report['autoPromotion'])

    def test_summary_requires_distinct_days_and_weights_days_equally(self):
        rows = [{'basisDate': f'2026-10-{i+1:02d}', 'return': .1, 'spyReturn': .03, 'excessReturn': .07}
                for i in range(20)]
        self.assertAlmostEqual(study.group_summary(rows, 20)['meanExcessReturn'], .07)
        repeated = [dict(rows[0]) for _ in range(60)]
        self.assertIsNone(study.group_summary(repeated, 20)['meanReturn'])
        uneven = rows + [{**rows[0], 'return': .3, 'excessReturn': .27}]
        self.assertAlmostEqual(study.group_summary(uneven, 20)['meanReturn'], .105)

    def test_class_share_symbols_resolve_without_changing_original_symbol(self):
        home, prices, at = self.snapshot('2026-10-05')
        home['rankings']['buy'][0]['symbol'] = 'BRK-B'
        prices['stocks']['BRK.B'] = prices['stocks'].pop('ILMN')
        item = study.observation(home, prices, study.iso(at), {}, self.cal)
        self.assertEqual(item['cards'][0]['symbol'], 'BRK-B')
        self.assertEqual(item['cards'][0]['referenceClose'], 100.)

    def test_future_price_vintage_and_history_beyond_source_asof(self):
        data, at = self.prices()
        data['stocks']['ILMN']['sourceUpdatedAt'] = study.iso(at + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            study.capture_prices(self.folder, self.state, data, at, {}, self.cal)
        data['stocks']['ILMN']['sourceUpdatedAt'] = study.iso(at)
        data['stocks']['ILMN']['asOf'] = self.first['entryDate']
        study.capture_prices(self.folder, self.state, data, at, {}, self.cal)
        self.assertNotIn(('ILMN', self.first['targetDates']['20']), self.state['prices'])

    def test_future_close_embedded_in_old_source_vintage_is_not_observed(self):
        data, at = self.prices()
        data['stocks']['ILMN']['sourceUpdatedAt'] = study.FIRST_OBSERVED_AT
        study.capture_prices(self.folder, self.state, data, at, {}, self.cal)
        self.assertFalse(any(symbol == 'ILMN' for symbol, day in self.state['prices']))

    def test_wrong_policy_and_rule_drift_stop_collection(self):
        home, prices, at = self.snapshot('2026-10-05')
        home['rankings']['policy'] = 'daily-top3-v2'
        with self.assertRaisesRegex(ValueError, 'policy'):
            study.capture(self.folder, self.state, home, prices, at, {}, self.cal)
        from unittest.mock import patch
        with patch.object(study, 'rule_hashes', return_value={}):
            with self.assertRaisesRegex(ValueError, 'policy inputs changed'):
                study.update(study.ROOT, at, self.cal)

    def test_twenty_complete_daily_cohorts_unlock_subtype_summary(self):
        sessions = self.cal.sessions_in_range('2026-10-05', '2026-12-31')[:19]
        for session in sessions:
            home, prices, at = self.snapshot(study.session_date(session))
            study.capture(self.folder, self.state, home, prices, at, {}, self.cal)
        final = self.state['observations'][-1]['targetDates']['20']
        at = self.cal.session_close(final).to_pydatetime() + timedelta(hours=3)
        stamp = study.iso(at)
        bars = [study.session_date(s) for s in self.cal.sessions_in_range(self.first['entryDate'], final)]
        data = {'generatedAt': stamp, 'stocks': {}}
        for symbol in [*self.symbols, 'SPY']:
            data['stocks'][symbol] = {'sourceUpdatedAt': stamp, 'asOf': final,
                'history': [{'date': d, 'close': 100. * (1.001 ** i) if symbol != 'SPY' else 100.}
                            for i, d in enumerate(bars)]}
        study.capture_prices(self.folder, self.state, data, at, {}, self.cal)
        report = study.report(self.state, self.cal)
        self.assertEqual(report['horizons']['20']['fullyMatureCohorts'], 20)
        buy = report['horizons']['20']['groups']['buy']
        self.assertAlmostEqual(buy['meanExcessReturn'], 1.001 ** 20 - 1)
        self.assertEqual(buy['bySelection']['relative']['matureCohorts'], 20)
        self.assertEqual(buy['byCode']['breakout']['matureRows'], 40)
        self.assertIsNotNone(buy['byCode']['pullback']['meanExcessReturn'])
        self.assertIsNone(report['horizons']['63']['groups']['buy']['meanExcessReturn'])

    def git_fixture(self):
        root = Path(self.temp.name) / 'repo'
        root.mkdir()
        def run(*args):
            return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
        run('init')
        run('config', 'user.name', 'Test')
        run('config', 'user.email', 'test@example.invalid')
        return root, run

    def test_git_guard_rejects_modification_and_deletion_of_old_records(self):
        root, run = self.git_fixture()
        shutil.copytree(self.folder, root / study.FOLDER)
        study.publish(root / study.FOLDER / 'latest.json', study.report(self.state, self.cal))
        run('add', '.')
        run('commit', '-m', 'Seed test ledger')
        base = run('rev-parse', 'HEAD')
        path = next((root / study.FOLDER / 'ledger').glob('*.json'))
        path.write_text(path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'modified/deleted'):
            study.verify(root, base, self.cal)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'modified/deleted'):
            study.verify(root, base, self.cal)

    def test_committed_source_provenance_rejects_dirty_inputs(self):
        root, run = self.git_fixture()
        for name in ('market/home.json', 'forecasts/latest.json'):
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('{}\n')
        run('add', '.')
        run('commit', '-m', 'Test source snapshot')
        self.assertEqual(study.source(root)['gitCommit'], run('rev-parse', 'HEAD'))
        (root / 'market/home.json').write_text('{"changed":true}\n')
        with self.assertRaisesRegex(ValueError, 'committed snapshot'):
            study.source(root)

    def test_derived_cache_noop_and_bootstrap_cannot_replace_existing_study(self):
        cache = self.folder / 'latest.json'
        study.publish(cache, study.report(self.state, self.cal))
        before = cache.stat().st_mtime_ns
        study.publish(cache, study.report(self.state, self.cal))
        self.assertEqual(cache.stat().st_mtime_ns, before)
        with self.assertRaises(ValueError):
            study.bootstrap(study.ROOT, study.instant(study.FIRST_OBSERVED_AT), self.cal)

    def test_hash_tampering_clock_rewind_and_truncation_rejected(self):
        with self.assertRaises(ValueError):
            study.append(self.folder, self.state, 'prices', {'prices': [], 'revisions': []},
                         study.instant(self.state['records'][0]['recordedAt']) - timedelta(seconds=1))
        self.ingest(20)
        study.publish(self.folder / 'latest.json', study.report(self.state, self.cal))
        paths = sorted((self.folder / 'ledger').glob('*.json'))
        paths[-1].unlink()
        with self.assertRaises(ValueError):
            study.load(self.folder, self.cal)
        record = json.loads(paths[0].read_text())
        record['data']['cards'][0]['score'] = 1
        paths[0].write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            study.load(self.folder, self.cal)


if __name__ == '__main__':
    unittest.main()
