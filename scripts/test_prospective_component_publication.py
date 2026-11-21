"""Research publication isolation and real-Git freezer integration.

All generated test rows are synthetic fixtures in temporary local repositories;
none is an issued market forecast or evidence of performance.
"""
import csv
import gzip
import hashlib
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import audit_prospective_blends as audit
import freeze_prospective_blends as freezer
import publish_prospective_components as publication
from prospective_blends import REGISTERED_PROTOCOL_SHA256, target_date

ROOT = Path(__file__).resolve().parents[1]
PREFIX = publication.PREFIX


def chart(symbol='AAA', origin='2026-10-23'):
    end = datetime.fromisoformat(origin).replace(tzinfo=timezone.utc)
    days = [end - timedelta(days=299-i) for i in range(300)]
    return json.dumps({'chart': {'result': [{'meta': {'symbol': symbol},
        'timestamp': [int(d.timestamp()) for d in days],
        'indicators': {'adjclose': [{'adjclose': [100+i/10 for i in range(300)]}],
                       'quote': [{'close': [110+i/10 for i in range(300)]}]}}]}}).encode()


def components(origin='2026-10-23'):
    return dict(v5=[dict(model='environment-challenger-v5-horizon-specific', symbol='AAA',
        asOf=origin, horizon='21', assetClass='stocks', anchor=100, horizonModel=103,
        syntheticFixture=True)], trend=[dict(model='trend-decay-v1', symbol='AAA',
        asOf=origin, horizon=21, anchor=101, bear=95, base=98, bull=105,
        direction='down', dailyDrift=-.001, volatility=.2)])


class PublicationTests(unittest.TestCase):
    def test_original_source_bytes_are_locked_and_match_git(self):
        lock = publication.verify_sources(check_dependencies=False)
        self.assertEqual(lock['stateBranch'], publication.STATE_BRANCH)
        self.assertEqual(lock['requirements'], {'numpy': '2.2.6', 'scikit-learn': '1.8.0'})

    def test_non_research_branch_fails_before_writes(self):
        with patch.object(publication, 'git', return_value='main'):
            with self.assertRaisesRegex(ValueError, 'restricted'):
                publication.assert_state_branch()

    def test_dirty_worktree_cannot_be_published(self):
        with patch.object(publication, 'git', side_effect=[publication.STATE_BRANCH, ' M index.html']):
            with self.assertRaisesRegex(ValueError, 'clean tracked'):
                publication.assert_state_branch()

    def test_disabled_or_future_review_cannot_activate_collection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / PREFIX
            directory.mkdir(parents=True)
            (directory / 'ACTIVATION.json').write_text(json.dumps(dict(
                enabled=False, protocolSha256=REGISTERED_PROTOCOL_SHA256,
                sourceLockSha256=publication.SOURCE_LOCK_SHA256,
                reviewedAt='2026-10-24T05:00:00Z')))
            with patch.object(publication, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'reviewed activation'):
                    publication.verify_activation(publication.parse_time('2026-10-24T06:00:00Z'))

    def test_settlement_calendar_handles_weekends_holidays_early_close(self):
        for at, expected in [('2026-10-24T05:00:00Z', '2026-10-23'),
                             ('2026-11-26T22:00:00Z', '2026-11-25'),
                             ('2026-11-27T18:14:59Z', '2026-11-25'),
                             ('2026-11-27T18:15:00Z', '2026-11-27')]:
            self.assertEqual(publication.latest_settled(publication.parse_time(at)), expected)

    def test_original_adjusted_basis_is_distinct_from_trend_close(self):
        rows = publication.normalize_history(chart(), 'AAA', '2026-10-23')
        self.assertEqual(rows[-1]['close'], 129.9)

    def test_normalizer_excludes_any_after_origin_data(self):
        rows = publication.normalize_history(chart(origin='2026-10-24'), 'AAA', '2026-10-23')
        self.assertEqual(rows[-1]['date'], '2026-10-23')

    def test_missing_latest_context_never_falls_back_to_old_cached_origin(self):
        with self.assertRaisesRegex(ValueError, 'stale'):
            publication.normalize_history(chart(origin='2026-10-22'), 'AAA', '2026-10-23')

    def test_wrong_provider_security_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'identity'):
            publication.normalize_history(chart(symbol='WRONG'), 'AAA', '2026-10-23')

    def test_duplicate_history_dates_are_rejected(self):
        value = json.loads(chart())
        result = value['chart']['result'][0]
        result['timestamp'][-2] = result['timestamp'][-1]
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            publication.normalize_history(json.dumps(value).encode(), 'AAA', '2026-10-23')

    def test_missing_proxy_blocks_publication_instead_of_fabricating_input(self):
        def download(symbol, origin):
            raise ValueError('provider unavailable')
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            with patch.object(publication, 'download_history', side_effect=download):
                with self.assertRaisesRegex(ValueError, 'no issue published'):
                    publication.collect({'AAA': {'cik': 1}}, '2026-10-23', Path(temporary))

    def test_no_cli_backdate_or_model_override_switch_exists(self):
        source = (ROOT / 'scripts/publish_prospective_components.py').read_text()
        self.assertNotIn('argparse', source)
        self.assertNotIn('build_forecasts.build', source)

    def test_only_research_paths_can_be_staged(self):
        with patch.object(publication, 'git', side_effect=['', 'index.html']):
            with self.assertRaisesRegex(ValueError, 'non-research'):
                publication.commit_only(['index.html'], 'must fail')


class RealGitFreezerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / 'repo'
        subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(ROOT), str(self.repo)],
                       check=True, capture_output=True)
        main = subprocess.check_output(['git', 'rev-parse', 'origin/main'], cwd=ROOT).decode().strip()
        self.command('update-ref', 'HEAD', main)
        self.command('read-tree', 'HEAD')
        self.command('checkout', 'HEAD', '--', 'research/issued.json', 'forecasts/archive')
        # Runtime state starts from main (which descends from registration),
        # with the original protocol bytes copied in before any fixture issue.
        protocol = self.repo / publication.STUDY / 'PROTOCOL.json'
        protocol.parent.mkdir(parents=True)
        protocol.write_bytes((ROOT / publication.STUDY / 'PROTOCOL.json').read_bytes())
        self.command('config', 'user.name', 'Synthetic fixture test')
        self.command('config', 'user.email', 'fixture@example.invalid')
        self.command('add', f'{publication.STUDY}/PROTOCOL.json')
        self.command('commit', '-m', 'Synthetic protocol fixture; not evidence',
                     at='2026-10-24T05:29:00Z')
        self.patches = [patch.object(m, 'ROOT', self.repo) for m in (publication, freezer, audit)]
        for change in self.patches:
            change.start()
        self.output = self.repo / publication.STUDY
        self.origin = '2026-10-23'
        self.issued_at = '2026-10-24T05:30:00Z'

    def tearDown(self):
        for change in reversed(self.patches):
            change.stop()
        self.temp.cleanup()

    def command(self, *args, at=None):
        env = os.environ.copy()
        if at:
            env.update(GIT_AUTHOR_DATE=at, GIT_COMMITTER_DATE=at)
        return subprocess.check_output(['git', *args], cwd=self.repo, env=env).decode().strip()

    def issue_and_freeze(self):
        publication.append_components(components(), self.origin, self.issued_at, 'a'*64,
                                      'synthetic-fixture-only.json')
        self.command('add', 'research/issued.json', 'forecasts/archive/2026-10.csv')
        self.command('commit', '-m', 'Synthetic inputs; not evidence', at='2026-10-24T05:30:01Z')
        result = freezer.freeze_one(now=publication.parse_time('2026-10-24T05:30:02Z'),
                                     output_root=self.output)
        self.command('add', f'{publication.STUDY}/issued')
        self.command('commit', '-m', 'Synthetic freeze; not evidence', at='2026-10-24T05:30:03Z')
        return result

    def test_real_git_components_are_accepted_by_unchanged_freezer_and_verifier(self):
        original = json.loads((self.repo / 'research/issued.json').read_bytes())
        result = self.issue_and_freeze()
        self.assertEqual(result['n'], 1)
        self.assertEqual(result['targetDate'], '2026-11-23')
        path = f"{publication.STUDY}/issued/{self.origin}.json"
        raw = (self.repo / path).read_bytes()
        snapshot = json.loads(raw)
        audit.verify_issue_artifact('HEAD', path, raw, snapshot, REGISTERED_PROTOCOL_SHA256)
        self.assertEqual(json.loads((self.repo / 'research/issued.json').read_bytes())[:-1], original)
        self.assertFalse(snapshot['containsTargetData'])
        self.assertEqual(snapshot['rows'][0]['v5IssuedAt'], self.issued_at)
        self.assertIn('inputSha256', json.loads((self.repo/'research/issued.json').read_bytes())[-1])
        # No outcomes or scores are required; a second run waits for target date.
        self.assertIsNone(freezer.freeze_one(now=publication.parse_time('2026-10-24T05:31:00Z'),
                                            output_root=self.output))

    def test_duplicate_first_issue_cannot_be_overwritten(self):
        self.issue_and_freeze()
        before = (self.repo / 'research/issued.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            publication.append_components(components(), self.origin, self.issued_at, 'b'*64, 'fixture')
        self.assertEqual(before, (self.repo / 'research/issued.json').read_bytes())

    def test_retrospective_origin_cannot_be_issued_with_a_new_clock(self):
        with self.assertRaisesRegex(ValueError, 'genuinely new'):
            publication.append_components(components('2026-09-11'), '2026-09-11',
                                          self.issued_at, 'b'*64, 'fixture')

    def test_invalid_model_or_horizon_cannot_pollute_either_archive(self):
        original = (self.repo / 'research/issued.json').read_bytes()
        result = components()
        result['trend'][0]['model'] = 'trend-decay-v2-medium-long'
        result['trend'][0]['horizon'] = 126
        with self.assertRaisesRegex(ValueError, 'invalid component'):
            publication.append_components(result, self.origin, self.issued_at, 'b'*64, 'fixture')
        self.assertEqual(original, (self.repo / 'research/issued.json').read_bytes())

    def test_rewriting_frozen_issue_is_detected_by_first_add_git_proof(self):
        self.issue_and_freeze()
        path = f'{publication.STUDY}/issued/{self.origin}.json'
        value = json.loads((self.repo / path).read_bytes())
        value['rows'][0]['methods']['fixed50']['predictedPrice'] += 1
        raw = publication.canonical(value)
        (self.repo / path).write_bytes(raw)
        self.command('add', path)
        self.command('commit', '-m', 'Tampered synthetic fixture', at='2026-10-24T05:31:00Z')
        with self.assertRaisesRegex(ValueError, 'rewritten'):
            audit.verify_issue_artifact('HEAD', path, raw, value, REGISTERED_PROTOCOL_SHA256)

    def test_existing_csv_bytes_are_not_rewritten(self):
        path = self.repo / 'forecasts/archive/2026-10.csv'
        path.write_bytes((','.join(publication.FIELDS) + '\n' +
            'trend-decay-v2-medium-long,ZZZ,2026-10-22,2026-10-23T01:00:00Z,126,100,90,101,110,up,0.001,0.2\n').encode())
        before = path.read_bytes()
        publication.append_components(components(), self.origin, self.issued_at, 'c'*64, 'fixture')
        self.assertTrue(path.read_bytes().startswith(before))


class LegacyGeneratorTests(unittest.TestCase):
    def test_frozen_generator_replays_and_ignores_after_origin_targets(self):
        # A small multi-security synthetic history exercises actual HGB fitting,
        # CIK share-class deduplication and the original 21-session profile.
        from importlib.util import spec_from_file_location, module_from_spec
        days = []
        day = datetime(2022, 1, 3)
        end = datetime(2026, 10, 23)
        while day <= end:
            if day.weekday() < 5:
                days.append(day.date().isoformat())
            day += timedelta(days=1)
        members = {f'S{i}': {'cik': i+1} for i in range(4)}
        members['S4'] = {'cik': 1}
        histories = {}
        for i, symbol in enumerate(list(members) + list(publication.PROXIES)):
            histories[symbol] = [dict(date=d, close=100*math.exp(.0001*j+.10*math.sin(j/19+i)))
                                 for j, d in enumerate(days)]
        bundle = dict(origin=days[-1], histories=histories, members=members,
            priceRows=[dict(symbol=s, date=days[-1], close=histories[s][-1]['close'],
                            volatility4m=.2, return1m=.03, return3m=-.05, return6m=.07)
                       for s in members])
        with tempfile.TemporaryDirectory() as temp:
            source, out1, out2 = [Path(temp) / n for n in ('input.json.gz', 'one.json', 'two.json')]
            source.write_bytes(gzip.compress(publication.canonical(bundle)))
            runner = ROOT / PREFIX / 'legacy/generate.py'
            for output in (out1, out2):
                subprocess.run([sys.executable, str(runner), str(source), str(output)],
                               check=True, capture_output=True)
            self.assertEqual(out1.read_bytes(), out2.read_bytes())
            result = json.loads(out1.read_bytes())
            self.assertEqual(len(result['v5']), 5)
            self.assertEqual(result['profile']['field'], 'z')
            self.assertLess(result['trainTargetThrough'], bundle['origin'])
            self.assertLess(result['contextThrough'], bundle['origin'])
            self.assertEqual(result['profile']['max_iter'], 70)
            bundle['histories']['S0'].append(dict(date='2026-10-26', close=999999))
            source.write_bytes(gzip.compress(publication.canonical(bundle)))
            failed = subprocess.run([sys.executable, str(runner), str(source), str(out1)],
                                    capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn(b'future target inputs', failed.stderr)


if __name__ == '__main__':
    unittest.main()
