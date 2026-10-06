"""Synthetic secondary-provider regressions; no network or invented live prices."""
import copy
import contextlib
import io
import json
import unittest
import urllib.error
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

import eod_close_fallback as recovery

AS_OF = "2026-10-05"
COLLECTED = "2026-10-06T02:00:00Z"
META = {"symbol": "HUBB", "currency": "USD", "instrumentType": "EQUITY",
        "exchangeTimezoneName": "America/New_York"}


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        result = datetime(2026, 10, 6, 1, 59, tzinfo=timezone.utc)
        return result.astimezone(tz) if tz else result.replace(tzinfo=None)


def sample_frame():
    return pd.DataFrame({"Close": [90.1, 91.2, 92.3, float("nan")],
                         "Open": [90, 91, 92, 93], "High": [92, 93, 94, 96],
                         "Low": [89, 90, 91, 92], "Volume": [1000, 1100, 1200, 1300]},
                        index=pd.to_datetime(["2026-09-30", "2026-10-01", "2026-10-02", AS_OF]))


def sample_response():
    return {"status": {"rCode": 200}, "data": {"symbol": "HUBB", "tradesTable": {"rows": [
        {"date": "10/05/2026", "open": "$93.00", "high": "$96.00", "low": "$92.00",
         "close": "$95.40", "volume": "1,305"},
        {"date": "10/02/2026", "close": "$92.30"},
        {"date": "10/01/2026", "close": "$91.20"},
        {"date": "09/30/2026", "close": "$90.10"}]}}}


def recovered_fixture(symbol="HUBB"):
    frame, payload, meta = sample_frame(), sample_response(), dict(META)
    meta["symbol"] = symbol
    payload["data"]["symbol"] = recovery.nasdaq_symbol(symbol)
    with patch.object(recovery, "datetime", FixedClock), \
         patch.object(recovery.urllib.request, "urlopen", return_value=io.StringIO(json.dumps(payload))):
        return recovery.recover(symbol, meta, frame, AS_OF)


class RecoveryTests(unittest.TestCase):
    def test_completed_bar_replaces_ohlcv_together_and_preserves_prior_history(self):
        original = sample_frame()
        frame, evidence = recovered_fixture()
        pd.testing.assert_frame_equal(frame.loc[:, original.columns].iloc[:-1], original.iloc[:-1], check_dtype=False)
        self.assertTrue(pd.isna(original.iloc[-1]["Close"]))
        self.assertEqual(frame.iloc[-1]["Close"], 95.4)
        self.assertEqual(frame.iloc[-1]["Volume"], 1305)
        self.assertEqual(frame.iloc[-1]["Adj Close"], 95.4)
        self.assertEqual(recovery.decode_evidence(recovery.encode_evidence(evidence)), evidence)
        self.assertNotIn(",", recovery.encode_evidence(evidence))

    def test_existing_close_missing_whole_bar_non_us_or_etf_never_requests_secondary(self):
        good = sample_frame()
        good.iloc[-1, good.columns.get_loc("Close")] = 95.4
        cases = [(META, good), (META, sample_frame().iloc[:-1]),
                 ({**META, "currency": "CAD"}, sample_frame()),
                 ({**META, "instrumentType": "ETF"}, sample_frame()),
                 ({**META, "exchangeTimezoneName": "Europe/London"}, sample_frame()),
                 (META, sample_frame().iloc[::-1])]
        with patch.object(recovery.urllib.request, "urlopen") as request:
            for meta, frame in cases:
                with self.subTest(meta=meta):
                    unchanged, evidence = recovery.recover("HUBB", meta, frame, AS_OF)
                    self.assertIs(unchanged, frame)
                    self.assertIsNone(evidence)
            request.assert_not_called()

    def test_unfinished_bar_is_not_recovered_as_the_last_completed_session(self):
        with patch.object(recovery.urllib.request, "urlopen") as request:
            _, evidence = recovery.recover("HUBB", META, sample_frame(), "2026-10-02")
            self.assertIsNone(evidence)
            request.assert_not_called()

    def test_symbol_stale_date_duplicates_missing_anchor_and_adjustment_mismatch_reject(self):
        bad = []
        payload = sample_response(); payload["data"]["symbol"] = "AAPL"; bad.append(payload)
        payload = sample_response(); payload["status"]["rCode"] = 400; bad.append(payload)
        payload = sample_response(); payload["data"]["tradesTable"]["rows"].pop(0); bad.append(payload)
        payload = sample_response(); payload["data"]["tradesTable"]["rows"].append(copy.deepcopy(payload["data"]["tradesTable"]["rows"][0])); bad.append(payload)
        payload = sample_response(); payload["data"]["tradesTable"]["rows"].pop(); bad.append(payload)
        payload = sample_response(); payload["data"]["tradesTable"]["rows"][1]["close"] = "$46.15"; bad.append(payload)
        payload = sample_response(); payload["data"]["tradesTable"]["rows"][0]["date"] = "10/06/2026"; bad.append(payload)
        for payload in bad:
            with self.subTest(payload=payload):
                frame = sample_frame()
                with self.assertRaises(ValueError):
                    recovery.checked_bar(payload, "HUBB", frame, AS_OF)
                self.assertTrue(pd.isna(frame.iloc[-1]["Close"]))

    def test_nonfinite_nonpositive_wrong_currency_and_inconsistent_ohlcv_reject(self):
        for key, value in (("close", "NaN"), ("close", "$0"), ("close", "€95.40"),
                           ("close", "$97"), ("open", "$94"), ("high", "$97"),
                           ("low", "$91"), ("volume", "0"), ("volume", "N/A")):
            with self.subTest(key=key, value=value):
                payload = sample_response()
                payload["data"]["tradesTable"]["rows"][0][key] = value
                with self.assertRaises(ValueError):
                    recovery.checked_bar(payload, "HUBB", sample_frame(), AS_OF)

    def test_previous_session_anchor_and_current_yahoo_ohlc_are_required(self):
        for frame in (sample_frame().drop(pd.Timestamp("2026-10-02")),
                      sample_frame().drop(pd.Timestamp("2026-09-30")),
                      sample_frame().drop(columns="High")):
            with self.subTest(columns=list(frame.columns), count=len(frame)):
                with self.assertRaises(ValueError):
                    recovery.checked_bar(sample_response(), "HUBB", frame, AS_OF)

    def test_provider_error_propagates_without_retry_or_mutating_history(self):
        for code in (403, 429, 500):
            with self.subTest(code=code):
                frame = sample_frame()
                error = urllib.error.HTTPError("https://api.nasdaq.com", code, "test", None, None)
                with patch.object(recovery.urllib.request, "urlopen", side_effect=error) as request:
                    with self.assertRaises(urllib.error.HTTPError):
                        recovery.recover("HUBB", META, frame, AS_OF)
                    self.assertEqual(request.call_count, 1)
                self.assertTrue(pd.isna(frame.iloc[-1]["Close"]))

    def test_provider_identity_mismatch_rejects_before_request(self):
        with patch.object(recovery.urllib.request, "urlopen") as request:
            with self.assertRaises(ValueError):
                recovery.recover("HUBB", {**META, "symbol": "AAPL"}, sample_frame(), AS_OF)
            request.assert_not_called()

    def test_actual_chart_collector_recovers_null_bar_and_keeps_failure_null(self):
        import update_eod_prices as collector

        frame = sample_frame()
        chart = {"chart": {"result": [{"meta": META, "timestamp": [
            int(datetime.fromisoformat(day.date().isoformat() + "T13:30:00+00:00").timestamp())
            for day in frame.index], "indicators": {"quote": [{
                key.lower(): [None if pd.isna(value) else float(value) for value in frame[key]]
                for key in frame.columns}]}}]}}
        for failed in (False, True):
            def response(request, **kwargs):
                if "api.nasdaq.com" in request.full_url:
                    if failed:
                        raise urllib.error.HTTPError(request.full_url, 429, "test", None, None)
                    return io.StringIO(json.dumps(sample_response()))
                return io.StringIO(json.dumps(chart))
            with self.subTest(failed=failed), patch.object(collector, "datetime", FixedClock), \
                 patch.object(recovery, "datetime", FixedClock), \
                 patch.object(recovery.urllib.request, "urlopen", side_effect=response) as request, \
                 contextlib.redirect_stdout(io.StringIO()):
                result = collector.download_public_chart(["HUBB"])
                self.assertEqual(request.call_count, 2)
                if failed:
                    self.assertTrue(pd.isna(result["HUBB"].iloc[-1]["Close"]))
                    self.assertEqual(result.attrs["eodRecoveries"], {})
                else:
                    self.assertEqual(result["HUBB"].iloc[-1]["Close"], 95.4)
                    self.assertIn("HUBB", result.attrs["eodRecoveries"])

    def test_class_share_symbol_identity_is_preserved(self):
        frame, evidence = recovered_fixture("BRK-B")
        history = [{"date": day.date().isoformat(), **{k.lower(): float(v) for k, v in row.items()}}
                   for day, row in frame.iterrows()]
        recovery.verify_evidence(evidence, "BRK.B", AS_OF, COLLECTED, history)

    def test_evidence_bar_response_hash_and_retrieval_session_are_checked(self):
        frame, evidence = recovered_fixture()
        history = [{"date": day.date().isoformat(), **{k.lower(): float(v) for k, v in row.items()}}
                   for day, row in frame.iterrows()]
        recovery.verify_evidence(evidence, "HUBB", AS_OF, COLLECTED, history)
        for field, value in (("retrievedAt", "2026-10-05T20:14:00Z"),
                             ("retrievedAt", "2026-10-06T02:01:00Z"),
                             ("responseSha256", "0" * 64), ("date", "2026-10-02")):
            bad = {**evidence, field: value}
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    recovery.verify_evidence(bad, "HUBB", AS_OF, COLLECTED, history)
        wrong = copy.deepcopy(history); wrong[-1]["volume"] = 1300
        with self.assertRaises(ValueError):
            recovery.verify_evidence(evidence, "HUBB", AS_OF, COLLECTED, wrong)


if __name__ == "__main__":
    unittest.main()
