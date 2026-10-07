"""Captured PSKY/SKYD provider regressions and 505-row Git publication replay."""
import contextlib
import copy
import io
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import build_forecasts
import eod_close_fallback as fallback
import eod_publication as publication
import eod_symbol_mapping as mapping
import update_eod_prices as collector
import test_eod_publication as publication_tests

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/eod-psky-2026-10-06.json').read_text())
AS_OF = FIXTURE['asOf']


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        result = datetime(2026, 10, 6, 22, 57, 30, tzinfo=timezone.utc)
        return result.astimezone(tz) if tz else result.replace(tzinfo=None)


def response(name):
    return copy.deepcopy(FIXTURE['requests'][name]['response'])


def chart_frame():
    result = response('yahoo-SKYD')['chart']['result'][0]
    return pd.DataFrame({k.title(): v for k, v in result['indicators']['quote'][0].items()},
                        index=pd.to_datetime(result['timestamp'], unit='s'))


def provider_reply(request, **kwargs):
    url = request.full_url
    if 'api.nasdaq.com' in url:
        name = 'nasdaq-' + url.split('/quote/')[1].split('/')[0]
        payload = response(name)
    else:
        symbol = url.split('/chart/')[1].split('?')[0]
        payload = response('yahoo-' + symbol) if symbol in ('PSKY', 'SKYD', 'WBD') else response('yahoo-SKYD')
        if symbol == 'PSKY':
            # Replay the observed failure, without claiming a raw runner capture.
            payload['chart']['result'][0]['indicators']['quote'][0]['close'][-1] = None
        elif symbol not in ('SKYD', 'WBD'):
            # All non-incident tickers in this replay are explicitly synthetic.
            payload['chart']['result'][0]['meta']['symbol'] = symbol
    return io.StringIO(json.dumps(payload))


class MappingTests(unittest.TestCase):
    def attest(self, payload=None, meta=None, anchors=None, frame=None):
        with patch.object(mapping, 'datetime', FixedClock), patch.object(mapping.urllib.request, 'urlopen',
                return_value=io.StringIO(json.dumps(payload or response('nasdaq-SKYD')))):
            return mapping.attest('PSKY', meta or response('yahoo-SKYD')['chart']['result'][0]['meta'],
                                  frame if frame is not None else chart_frame(), AS_OF,
                                  anchors if anchors is not None else FIXTURE['publishedAnchors'])

    def test_actual_failed_psky_nasdaq_response_has_no_old_symbol(self):
        self.assertEqual(FIXTURE['failedRun']['id'], 37541493288)
        payload = response('nasdaq-PSKY')
        self.assertEqual(payload['status']['rCode'], 400)
        self.assertEqual(payload['status']['bCodeMessage'][0]['errorMessage'], 'Symbol not exists.')
        with self.assertRaisesRegex(ValueError, 'Wrong symbol or failed Nasdaq historical response'):
            fallback.checked_bar(payload, 'PSKY', chart_frame(), AS_OF)

    def test_registry_is_date_bounded_and_cash_acquisition_is_not_an_alias(self):
        self.assertIsNone(mapping.transition('PSKY', '2026-10-05'))
        self.assertEqual(mapping.transition('PSKY', AS_OF)['yahooSymbol'], 'SKYD')
        self.assertIsNone(mapping.transition('WBD', AS_OF))
        self.assertIsNone(mapping.transition('UNKNOWN', AS_OF))
        mapping.assert_trading_session('WBD', '2026-10-05')
        with self.assertRaisesRegex(ValueError, 'exchange trading ended 2026-10-05'):
            mapping.assert_trading_session('WBD', AS_OF)
        self.assertEqual(fallback.nasdaq_symbol('BRK-B'), 'BRK.B')

    def test_captured_new_ticker_matches_original_anchors_and_secondary_ohlc(self):
        evidence = self.attest()
        self.assertEqual(evidence['yahooSymbol'], 'SKYD')
        self.assertEqual(evidence['response']['data']['symbol'], 'SKYD')
        self.assertAlmostEqual(chart_frame().iloc[-1]['Close'], 9.53, places=6)
        self.assertEqual(len(evidence['response']['data']['tradesTable']['rows']), 1)

    def test_unknown_security_currency_exchange_class_and_historical_basis_fail_closed(self):
        for key, value in (('symbol', 'WBD'), ('currency', 'CAD'), ('instrumentType', 'ETF'),
                           ('exchangeTimezoneName', 'Europe/London'), ('exchangeName', 'NMS'),
                           ('longName', 'Another Issuer')):
            meta = response('yahoo-SKYD')['chart']['result'][0]['meta']
            meta[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'security identity'):
                self.attest(meta=meta)
        anchors = copy.deepcopy(FIXTURE['publishedAnchors'])
        anchors[0]['close'] /= 2
        with self.assertRaisesRegex(ValueError, 'price bases disagree'):
            self.attest(anchors=anchors)
        with self.assertRaisesRegex(ValueError, 'Three current published anchors'):
            self.attest(anchors=FIXTURE['publishedAnchors'][:-1])

    def test_missing_stale_unfinished_duplicate_or_zero_volume_new_bar_is_never_recovered(self):
        for fault in ('null', 'missing', 'duplicate', 'zero-volume'):
            frame = chart_frame()
            if fault == 'null': frame.iloc[-1, frame.columns.get_loc('Close')] = float('nan')
            elif fault == 'missing': frame = frame.iloc[:-1]
            elif fault == 'duplicate': frame = pd.concat([frame, frame.iloc[-1:]])
            else: frame.iloc[-1, frame.columns.get_loc('Volume')] = 0
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                self.attest(frame=frame)
        with self.assertRaises(ValueError):
            self.attest(payload=response('nasdaq-PSKY'))
        for key, value in (('date', '10/05/2026'), ('close', '$10.53'), ('low', '$8.125'), ('volume', 'N/A')):
            payload = response('nasdaq-SKYD')
            payload['data']['tradesTable']['rows'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.attest(payload=payload)

    def test_evidence_rechecks_registry_identity_hashes_dates_and_full_history(self):
        history = mapping.frame_history(chart_frame())
        evidence = self.attest()
        evidence['historySha256'] = mapping.history_hash(history)
        collected = '2026-10-06T22:58:00Z'
        mapping.verify_evidence(evidence, 'PSKY', AS_OF, collected, history)
        for field, value in (('yahooSymbol', 'WBD'), ('date', '2026-10-05'),
                             ('sourceUrl', mapping.chart_url('PSKY')), ('responseSha256', '0'*64),
                             ('historySha256', '0'*64), ('retrievedAt', '2026-10-06T20:14:59Z'),
                             ('retrievedAt', '2026-10-06T22:59:00Z'), ('transition', {})):
            bad = {**evidence, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                mapping.verify_evidence(bad, 'PSKY', AS_OF, collected, history)
        history[0]['close'] *= 2
        with self.assertRaisesRegex(ValueError, 'Invalid or stale'):
            mapping.verify_evidence(evidence, 'PSKY', AS_OF, collected, history)

    def test_collector_never_accepts_unattested_mapped_price_or_retries_retired_symbol(self):
        for fault in ('identity', 'secondary', 'unfinished'):
            def reply(request, **kwargs):
                payload = json.loads(provider_reply(request, **kwargs).read())
                if 'api.nasdaq.com' in request.full_url:
                    payload = response('nasdaq-PSKY')
                elif fault == 'identity': payload['chart']['result'][0]['meta']['symbol'] = 'PSKY'
                elif fault == 'unfinished': payload['chart']['result'][0]['indicators']['quote'][0]['close'][-1] = None
                return io.StringIO(json.dumps(payload))
            with self.subTest(fault=fault), patch.object(collector, 'datetime', FixedClock), \
                 patch.object(mapping, 'datetime', FixedClock), \
                 patch.object(mapping, 'published_anchors', return_value=FIXTURE['publishedAnchors']), \
                 patch.object(collector.urllib.request, 'urlopen', side_effect=reply) as requests, \
                 contextlib.redirect_stdout(io.StringIO()):
                data = collector.download_public_chart(['PSKY'])
                self.assertTrue(data.empty)
                urls = [call.args[0].full_url for call in requests.call_args_list]
                self.assertTrue(all('/PSKY' not in url for url in urls))
                self.assertEqual(requests.call_count, 2 if fault == 'secondary' else 1)


class IncidentPublicationTests(unittest.TestCase):
    def setUp(self):
        # Reuse the local bare-Git harness, with no remote API or live publication.
        self.repo = publication_tests.PublicationTests()
        self.repo.setUp()
        self.addCleanup(self.repo.doCleanups)
        self.repo.symbols = ['PSKY', 'SPY', 'SOXX'] + [f'X{i:04d}' for i in range(502)]
        self.repo.write_snapshot(self.repo.root, '2026-10-05', '2026-10-06T03:11:43+00:00')
        self.install_published_anchors()
        publication.git(self.repo.root, 'add', '--', *publication.PUBLIC_PATHS)
        publication.git(self.repo.root, 'commit', '-m', 'Incident baseline: 505 October 5 closes')
        publication.git(self.repo.root, 'push', 'origin', 'main')
        self.repo.original = self.repo.remote_head()

    def install_published_anchors(self):
        path = self.repo.root / 'forecasts/latest.json'
        forecasts = json.loads(path.read_text())
        forecasts['stocks']['PSKY']['history'] = copy.deepcopy(FIXTURE['publishedAnchors'])
        build_forecasts.atomic_json(path, forecasts)

    def collect(self, legacy=False):
        receipt_path = self.repo.base / 'request.json'
        with patch.object(collector, 'OUT_PATH', self.repo.root / 'prices/latest_prices.csv'), \
             patch.object(collector, 'datetime', FixedClock), patch.object(mapping, 'datetime', FixedClock), \
             patch.object(collector.urllib.request, 'urlopen', side_effect=provider_reply), \
             patch.object(collector, 'read_symbols', side_effect=AssertionError('Must not read Sheets')), \
             contextlib.redirect_stdout(io.StringIO()) as logs:
            with contextlib.ExitStack() as stack:
                if legacy: stack.enter_context(patch.object(mapping, 'transition', return_value=None))
                self.assertEqual(collector.main(['--public-prices-only', '--receipt', str(receipt_path)]), 0)
            build_forecasts.build(self.repo.root, '2026-10-06T22:58:00Z')
        self.repo.receipt = json.loads(receipt_path.read_text())
        return logs.getvalue()

    def test_actual_psky_failure_blocks_all_505_prices_before_git_staging(self):
        logs = self.collect(legacy=True)
        self.assertIn(FIXTURE['failedRun']['errors'][0], logs)
        with self.assertRaisesRegex(ValueError, 'PSKY: stale, unfinished or retained price row; expected 2026-10-06'):
            self.repo.publish()
        self.assertEqual(self.repo.remote_head(), self.repo.original)
        self.assertEqual(publication.staged_paths(self.repo.root), [])
        self.assertFalse((self.repo.bundle / 'publication.json').exists())

    def test_verified_psky_and_504_other_complete_rows_publish_then_restore_exact_research(self):
        self.collect()
        row = next(row for row in self.repo.prices() if row['symbol'] == 'PSKY')
        self.assertEqual(row['date'], AS_OF)
        self.assertEqual(row['yahooSymbol'], 'SKYD')
        self.assertEqual(float(row['close']), 9.53)
        self.assertEqual(row['source'], mapping.SOURCE)
        manifest = self.repo.publish()
        self.assertEqual(manifest['symbolCount'], 505)
        self.assertEqual(manifest['asOf'], AS_OF)
        self.assertEqual(len(manifest['historyFiles']), 505)
        published = self.repo.remote_head()
        publication.restore_research(self.repo.root, self.repo.bundle)
        actual = publication.validate(self.repo.root, self.repo.receipt)
        self.assertEqual(actual['historyFiles'], manifest['historyFiles'])
        (self.repo.root / 'ml/latest.json').write_text('{"syntheticResearchReplay":true}')
        self.assertTrue(publication.publish_research(self.repo.root, self.repo.bundle))
        self.assertEqual(publication.git(self.repo.remote, 'diff', '--name-only', published, 'main'), 'ml/latest.json')

    def test_verified_symbol_cannot_hide_another_stale_ticker_or_missing_provenance(self):
        self.collect()
        original = self.repo.prices()
        for fault in ('other-ticker', 'provenance', 'yahoo-symbol'):
            rows = copy.deepcopy(original)
            psky = next(row for row in rows if row['symbol'] == 'PSKY')
            if fault == 'other-ticker': rows[-1]['date'] = '2026-10-05'
            elif fault == 'provenance': psky['eodProvenance'] = ''
            else: psky['yahooSymbol'] = 'PSKY'
            self.repo.write_prices(rows)
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                self.repo.publish()
            self.assertEqual(self.repo.remote_head(), self.repo.original)

    def test_known_wbd_halt_blocks_ghost_price_even_with_matching_csv_forecast_and_chart(self):
        self.repo.symbols[-1] = 'WBD'
        self.repo.write_snapshot(self.repo.root, '2026-10-05', '2026-10-06T03:11:43+00:00')
        self.install_published_anchors()
        self.collect()
        # A zero-volume carry-forward must not pass by relabeling its date.
        rows = self.repo.prices()
        wbd = next(row for row in rows if row['symbol'] == 'WBD')
        wbd.update(date=AS_OF, updatedAt=self.repo.receipt['updatedAt'], volume='0')
        self.repo.write_prices(rows)
        with self.assertRaisesRegex(ValueError, 'WBD: exchange trading ended 2026-10-05'):
            self.repo.publish()
        self.assertEqual(self.repo.remote_head(), self.repo.original)


if __name__ == '__main__':
    unittest.main()
