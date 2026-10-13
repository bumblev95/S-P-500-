"""Offline producer/consumer regression using the failed Actions snapshot."""
import contextlib
import copy
import io
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from build_market_context import age, bond_spreads, build, funding, summarize

ROOT = Path(__file__).resolve().parents[1]
INCIDENT = json.loads((ROOT/'scripts/fixtures/market-freshness-2026-10-13.json').read_text())
NOW = datetime.fromisoformat(INCIDENT['generatedAt'])


def state(snapshot, now):
    result = subprocess.run(
        ['node', '-e', "const g=require('./assets/technical-guide.js');"
         "const x=JSON.parse(require('node:fs').readFileSync(0,'utf8'));"
         "process.stdout.write(g.marketState(x.snapshot,Date.parse(x.now)));"],
        cwd=ROOT, input=json.dumps(dict(snapshot=snapshot, now=now.isoformat())),
        text=True, capture_output=True, check=True)
    return result.stdout


def fetcher(observations):
    def fetch(url):
        if 'fredgraph' in url:
            key = url.split('id=')[1].split('&')[0]
            return 'observation_date,'+key+'\n'+''.join(f'{d},{v}\n' for d,v in observations[key])
        if 'ebp_csv' in url:
            return 'date,gz_spread,ebp\n2026-09-01,0.9259102941329188,-0.3919245963723856\n'
        return '<rss><channel/></rss>'
    return fetch


def fail(_url):
    raise TimeoutError()


class FreshnessContractTests(unittest.TestCase):
    def generate(self, root, now=NOW, fetch=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return build(root, now, fetch or fetcher(INCIDENT['observations']))

    def test_incident_and_fixed_producer_keep_entry_closed(self):
        self.assertEqual(INCIDENT['credit']['status'], 'stable')
        self.assertEqual(state(INCIDENT, NOW), 'unknown')
        self.assertAlmostEqual(age('2026-10-08', NOW), 5.46662698, places=7)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = self.generate(root)
            self.assertEqual(json.loads((root/'market/latest.json').read_text()), json.loads(json.dumps(snapshot)))
        by = {q['id']:q for q in snapshot['indicators']}
        for id_ in ('SOFR', 'FUNDING'):
            self.assertEqual(by[id_]['status'], 'stale')
            self.assertEqual(by[id_]['asOf'], '2026-10-08')
            self.assertEqual(by[id_]['fetchStatus'], 'ready')
            self.assertEqual(by[id_]['lastSuccessAt'], NOW.isoformat())
        self.assertEqual(snapshot['credit']['status'], 'stable')
        self.assertEqual(snapshot['credit']['coverage'], 3)
        self.assertEqual(snapshot['credit']['missingFamilies'], ['단기자금조달'])
        self.assertEqual(state(snapshot, NOW), 'unknown')

    def test_fresh_producer_then_cached_expiry_and_recovery(self):
        boundary = datetime(2026,10,13,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fresh = self.generate(root, boundary)
            self.assertEqual(fresh['credit']['status'], 'stable')
            self.assertEqual(state(fresh, boundary), 'stable')
            for elapsed in (timedelta(milliseconds=1), timedelta(hours=11)):
                cached = self.generate(root, boundary+elapsed, fail)
                fund = next(q for q in cached['indicators'] if q['id']=='FUNDING')
                self.assertEqual(fund['status'], 'stale')
                self.assertEqual(fund['asOf'], '2026-10-08')
                self.assertEqual(fund['lastSuccessAt'], boundary.isoformat())
                self.assertTrue(fund['fromCache'])
                self.assertEqual(state(cached, boundary+elapsed), 'unknown')
            rows = copy.deepcopy(INCIDENT['observations'])
            rows['SOFR'].append(['2026-10-13', 3.87])
            recovered = self.generate(root, NOW, fetcher(rows))
            self.assertEqual(state(recovered, NOW), 'stable')

    def test_legacy_cache_without_observation_rows_uses_actual_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'market').mkdir()
            legacy = {k:v for k,v in INCIDENT.items() if k != 'observations'}
            (root/'market/latest.json').write_text(json.dumps(legacy))
            snapshot = self.generate(root, NOW, fail)
        fund = next(q for q in snapshot['indicators'] if q['id']=='FUNDING')
        self.assertEqual(fund['status'], 'stale')
        self.assertTrue(fund['fromCache'])
        self.assertEqual(state(snapshot, NOW), 'unknown')

    def test_risk_survives_stale_funding_but_not_expired_snapshot(self):
        rows = copy.deepcopy(INCIDENT['observations']); rows['NFCI'] = [['2026-10-02', 1.1]]
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = self.generate(Path(tmp), NOW, fetcher(rows))
        self.assertEqual(snapshot['credit']['status'], 'risk')
        self.assertEqual(state(snapshot, NOW), 'risk')
        self.assertEqual(state(snapshot, NOW+timedelta(days=3, milliseconds=1)), 'unknown')

    def test_every_producer_limit_is_inclusive_and_never_day_rounded(self):
        observed = datetime(2026,10,1,tzinfo=timezone.utc)
        for id_, days in [('NFCI',16), ('STLFSI4',16), ('DRTSCILM',150), ('SOFR',5), ('IORB',5), ('DGS10',7), ('DTWEXBGS',10)]:
            for offset, expected in [(-1,'ready'), (0,'ready'), (1,'stale')]:
                with self.subTest(id=id_, offset=offset):
                    now = observed+timedelta(days=days, milliseconds=offset)
                    self.assertEqual(summarize(id_, [('2026-10-01',0)], now)['status'], expected)
        rows = [('2026-09-29',3.9), ('2026-09-30',3.9), ('2026-10-01',3.9)]
        for offset, expected in [(-1,'ready'), (0,'ready'), (1,'stale')]:
            self.assertEqual(funding(rows, rows, observed+timedelta(days=5, milliseconds=offset))['status'], expected)
            bonds = bond_spreads('date,gz_spread,ebp\n2026-10-01,1,-.1\n', observed+timedelta(days=75, milliseconds=offset))
            self.assertTrue(all(q['status']==expected for q in bonds))
        self.assertEqual(summarize('NFCI',[('2026-10-01',0)],observed-timedelta(milliseconds=1))['status'], 'stale')
        self.assertEqual(funding(rows,rows,observed-timedelta(milliseconds=1))['status'], 'stale')
        offset_time = datetime.fromisoformat('2026-10-13T05:11:56.571358-06:00')
        self.assertEqual(age('2026-10-08', offset_time), age('2026-10-08', NOW))


if __name__ == '__main__':
    unittest.main()
