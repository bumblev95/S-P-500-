"""Exchange-boundary timing and complete-snapshot retry regressions."""
import contextlib
import csv
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import build_forecasts
import eod_close_schedule as schedule


def at(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class CloseScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.receipt = self.root / "receipt.json"

    def snapshot(self, as_of, collected, *, incomplete=False):
        rows = []
        for symbol, price in (("SPY", 100), ("SOXX", 200)):
            stale = incomplete and symbol == "SOXX"
            day = "2026-10-05" if stale else as_of
            stamp = "2026-10-05T23:40:00Z" if stale else collected
            build_forecasts.atomic_json(self.root / f"prices/history/{symbol}.json", {
                "symbol": symbol, "updatedAt": stamp,
                "prices": [{"date": "2026-10-01", "close": price - 1, "volume": 100},
                           {"date": day, "close": price, "volume": 200}],
            })
            rows.append({"symbol": symbol, "date": day, "close": price, "updatedAt": stamp,
                         "volatility4m": .2, "return1m": .01, "return3m": .03, "return6m": .05})
        path = self.root / "prices/latest_prices.csv"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0])
            writer.writeheader()
            writer.writerows(rows)
        self.receipt.write_text(json.dumps({"schemaVersion": 1, "symbols": ["SOXX", "SPY"],
                                           "minimumSymbolCount": 2, "updatedAt": collected}))

    def build(self, issued_at):
        with contextlib.redirect_stdout(io.StringIO()):
            build_forecasts.build(self.root, issued_at)

    def seed(self):
        self.snapshot("2026-10-05", "2026-10-05T23:40:00Z")
        self.build("2026-10-05T23:41:00Z")
        return schedule.public_snapshot(self.root)

    def test_regular_dst_and_early_close_have_the_correct_ready_boundary(self):
        for start, expected_day, expected_ready in [
            ("2026-10-06T20:00:00Z", "2026-10-06", "2026-10-06T20:15:00Z"),
            ("2026-11-02T21:00:00Z", "2026-11-02", "2026-11-02T21:15:00Z"),
            ("2026-11-27T18:00:00Z", "2026-11-27", "2026-11-27T18:15:00Z"),
            ("2026-12-24T18:00:00Z", "2026-12-24", "2026-12-24T18:15:00Z"),
        ]:
            with self.subTest(start=start):
                self.assertEqual(schedule.collection_plan(self.root, "schedule", at(start)),
                                 (expected_day, at(expected_ready)))

    def test_unused_early_slot_preclose_holiday_and_weekend_skip(self):
        for start in ("2026-10-06T17:00:00Z", "2026-10-06T19:59:59Z",
                      "2026-11-26T21:00:00Z", "2026-10-10T20:00:00Z"):
            with self.subTest(start=start), contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(schedule.collection_plan(self.root, "schedule", at(start)))

    def test_manual_before_close_retains_the_last_closed_session(self):
        self.assertEqual(schedule.collection_plan(self.root, "workflow_dispatch", at("2026-10-06T17:00:00Z")),
                         ("2026-10-05", at("2026-10-06T17:00:00Z")))

    def test_already_published_backup_skips_but_manual_refresh_still_runs(self):
        self.snapshot("2026-10-06", "2026-10-06T20:16:00Z")
        self.build("2026-10-06T20:17:00Z")
        now = at("2026-10-06T20:35:00Z")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(schedule.collection_plan(self.root, "schedule", now))
        self.assertEqual(schedule.collection_plan(self.root, "push", now), ("2026-10-06", now))
        forecasts = json.loads((self.root / "forecasts/latest.json").read_text())
        forecasts["stocks"]["SOXX"]["price"] = 999
        (self.root / "forecasts/latest.json").write_text(json.dumps(forecasts))
        self.assertEqual(schedule.collection_plan(self.root, "schedule", now), ("2026-10-06", now))

    def test_close_start_waits_until_the_same_buffer_used_by_publication(self):
        self.seed()
        now = [at("2026-10-06T20:00:00Z")]
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            now[0] += timedelta(seconds=seconds)

        def run(command, root):
            self.assertGreaterEqual(now[0], at("2026-10-06T20:15:00Z"))
            if command[1].endswith("update_eod_prices.py"):
                self.snapshot("2026-10-06", "2026-10-06T20:15:00Z")
            else:
                self.build("2026-10-06T20:15:01Z")
            return 0, False

        with patch.object(schedule, "run_command", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(schedule.collect(self.root, self.receipt, True, "push",
                                             clock=lambda: now[0], sleeper=sleep), 0)
        self.assertEqual(sum(waits), 900)
        self.assertLessEqual(max(waits), 30)

    def test_incomplete_first_attempt_is_retried_without_preserving_unpublished_issue_records(self):
        original = self.seed()
        downloads = []
        waits = []

        def run(command, root):
            if command[1].endswith("update_eod_prices.py"):
                self.assertEqual(schedule.public_snapshot(self.root), original)
                downloads.append(command)
                self.assertIn("--public-prices-only", command)
                stamp = "2026-10-06T21:01:00Z" if len(downloads) == 1 else "2026-10-06T21:06:00Z"
                self.snapshot("2026-10-06", stamp, incomplete=len(downloads) == 1)
            else:
                self.build("2026-10-06T21:01:01Z" if len(downloads) == 1 else "2026-10-06T21:06:01Z")
            return 0, False

        with patch.object(schedule, "run_command", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            result = schedule.collect(self.root, self.receipt, True, "push",
                                      clock=lambda: at("2026-10-06T21:00:00Z"), sleeper=waits.append)
        self.assertEqual(result, 0)
        self.assertEqual(len(downloads), 2)
        self.assertEqual(waits, [300])
        with (self.root / "forecasts/archive/2026-10.csv").open() as stream:
            today = [row for row in csv.DictReader(stream) if row["asOf"] == "2026-10-06"]
        self.assertEqual(len(today), 4)
        self.assertEqual({row["issuedAt"] for row in today}, {"2026-10-06T21:06:01Z"})

    def test_retry_limit_keeps_the_last_public_files_byte_for_byte(self):
        original = self.seed()
        waits = []

        def run(command, root):
            if command[1].endswith("update_eod_prices.py"):
                self.snapshot("2026-10-06", "2026-10-06T21:00:00Z", incomplete=True)
                (self.root / "forecasts/archive/2026-11.csv").write_text("unpublished")
            else:
                self.build("2026-10-06T21:00:01Z")
            return 0, False

        with patch.object(schedule, "run_command", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            result = schedule.collect(self.root, self.receipt, False, "push", attempts=2,
                                      clock=lambda: at("2026-10-06T21:00:00Z"), sleeper=waits.append)
        self.assertEqual(result, 1)
        self.assertEqual(waits, [300])
        self.assertEqual(schedule.public_snapshot(self.root), original)

    def test_provider_stop_aborts_without_retrying(self):
        original = self.seed()
        waits = []
        with patch.object(schedule, "run_command", return_value=(0, True)) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            result = schedule.collect(self.root, self.receipt, True, "push",
                                      clock=lambda: at("2026-10-06T21:00:00Z"), sleeper=waits.append)
        self.assertEqual(result, 1)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(waits, [])
        self.assertEqual(schedule.public_snapshot(self.root), original)


if __name__ == "__main__":
    unittest.main()
