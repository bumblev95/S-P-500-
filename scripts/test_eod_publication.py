"""Synthetic collection failures and real local Git transaction regressions."""
import contextlib
import csv
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import build_forecasts
import eod_publication as publication


class CalendarTests(unittest.TestCase):
    def test_latest_completed_close_handles_weekends_holidays_and_early_close(self):
        cases = {
            "2026-10-05T23:30:00Z": "2026-10-05",
            "2026-10-06T01:00:00Z": "2026-10-05",
            "2026-10-04T23:30:00Z": "2026-10-02",
            "2026-10-05T20:14:59Z": "2026-10-02",
            "2026-10-05T20:15:00Z": "2026-10-05",
            "2026-11-02T21:14:59Z": "2026-10-30",
            "2026-11-02T21:15:00Z": "2026-11-02",
            "2026-11-26T23:30:00Z": "2026-11-25",
            "2026-11-27T18:14:59Z": "2026-11-25",
            "2026-11-27T18:15:00Z": "2026-11-27",
        }
        for at, expected in cases.items():
            with self.subTest(at=at):
                self.assertEqual(publication.latest_closed_session(at), expected)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.remote = self.base / "checkout", self.base / "remote.git"
        self.bundle = self.base / "transfer"
        self.symbols = ["AAPL", "MSFT", "NVDA", "SOXX", "SPY"]
        self.root.mkdir()
        (self.root / ".gitignore").write_text("prices/history/\n")
        self.write_snapshot(self.root, "2026-10-02", "2026-10-04T01:26:05+00:00")
        (self.root / "ml").mkdir()
        (self.root / "ml/latest.json").write_text('{"status":"failed","unchangedGate":true}')
        (self.root / "market").mkdir()
        (self.root / "market/home.json").write_text('{"recap":"old"}')
        publication.git(self.root, "init", "-b", "main")
        self.identity(self.root)
        publication.git(self.root, "add", ".")
        publication.git(self.root, "commit", "-m", "Initial complete snapshot")
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        publication.git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        publication.git(self.root, "remote", "add", "origin", str(self.remote))
        publication.git(self.root, "push", "-u", "origin", "main")
        self.original = self.remote_head()
        self.receipt = self.write_snapshot(self.root, "2026-10-05", "2026-10-05T23:40:00+00:00")

    def identity(self, root):
        publication.git(root, "config", "user.name", "Synthetic EOD test")
        publication.git(root, "config", "user.email", "test@example.invalid")

    def write_snapshot(self, root, as_of, collected):
        rows = []
        for i, symbol in enumerate(self.symbols):
            close = 100 + i + .1234564
            history = [{"date": "2026-10-01", "close": 90 + i, "volume": 1000},
                       {"date": as_of, "close": close, "volume": 1200}]
            build_forecasts.atomic_json(root / f"prices/history/{symbol}.json",
                                        {"symbol": symbol, "updatedAt": collected, "prices": history})
            rows.append({"symbol": symbol, "date": as_of, "close": round(close, 6),
                         "updatedAt": collected, "volatility4m": .2, "return1m": .01,
                         "return3m": .03, "return6m": .05})
        self.write_prices(rows, root)
        with contextlib.redirect_stdout(io.StringIO()):
            build_forecasts.build(root, as_of + "T23:41:00+00:00")
        return {"schemaVersion": 1, "symbols": sorted(self.symbols),
                "minimumSymbolCount": len(self.symbols), "updatedAt": collected}

    def prices(self):
        with (self.root / "prices/latest_prices.csv").open(newline="") as stream:
            return list(csv.DictReader(stream))

    def write_prices(self, rows, root=None):
        path = (root or self.root) / "prices/latest_prices.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def remote_head(self):
        return publication.git(self.remote, "rev-parse", "main")

    def remote_file(self, path):
        return publication.git(self.remote, "show", "main:" + path)

    def publish(self):
        return publication.publish_public(self.root, self.receipt, self.bundle)

    def reject_without_remote_change(self):
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.publish()
        self.assertEqual(self.remote_head(), self.original)
        self.assertEqual(publication.staged_paths(self.root), [])
        self.assertFalse((self.bundle / "publication.json").exists())
        old = json.loads(self.remote_file("forecasts/latest.json"))["stocks"]
        self.assertEqual({s["asOf"] for s in old.values()}, {"2026-10-02"})

    def other_checkout(self):
        other = self.base / "other"
        subprocess.run(["git", "clone", str(self.remote), str(other)], check=True, capture_output=True)
        self.identity(other)
        return other

    def test_505_prices_and_forecasts_are_one_commit_without_ml(self):
        self.symbols = ["SOXX", "SPY"] + [f"X{i:04d}" for i in range(503)]
        self.receipt = self.write_snapshot(self.root, "2026-10-05", self.receipt["updatedAt"])
        (self.root / "ml/unpublished-result.json").write_text('{"neverStageThis":true}')
        manifest = self.publish()
        self.assertEqual(manifest["symbolCount"], 505)
        self.assertEqual(manifest["sourceCommit"], self.remote_head())
        changed = publication.git(self.remote, "diff", "--name-only", self.original, "main").splitlines()
        self.assertEqual(set(changed), {"prices/latest_prices.csv", "forecasts/latest.json",
                                        "forecasts/archive/2026-10.csv"})
        self.assertEqual(json.loads(self.remote_file("ml/latest.json"))["status"], "failed")
        remote_prices = list(csv.DictReader(io.StringIO(self.remote_file("prices/latest_prices.csv"))))
        self.assertEqual(len(remote_prices), 505)
        self.assertEqual({r["date"] for r in remote_prices}, {"2026-10-05"})
        self.assertEqual(len(manifest["historyFiles"]), 505)

    def test_retained_failed_download_row_blocks_entire_publication(self):
        rows = self.prices()
        rows[0].update(date="2026-10-02", updatedAt="2026-10-04T01:26:05+00:00")
        self.write_prices(rows)
        self.reject_without_remote_change()

    def test_retained_same_session_row_from_another_run_also_blocks_publication(self):
        rows = self.prices()
        rows[0]["updatedAt"] = "2026-10-05T23:35:00+00:00"
        self.write_prices(rows)
        self.reject_without_remote_change()

    def test_missing_requested_symbol_blocks_publication(self):
        self.write_prices(self.prices()[1:])
        self.reject_without_remote_change()

    def test_truncated_input_universe_cannot_publish_a_smaller_complete_subset(self):
        self.receipt["symbols"].remove("AAPL")
        self.write_prices(self.prices()[1:])
        path = self.root / "forecasts/latest.json"
        payload = json.loads(path.read_bytes())
        del payload["stocks"]["AAPL"]
        build_forecasts.atomic_json(path, payload)
        self.reject_without_remote_change()

    def test_duplicate_symbol_cannot_hide_a_missing_symbol(self):
        rows = self.prices()
        rows[0]["symbol"] = rows[1]["symbol"]
        self.write_prices(rows)
        self.reject_without_remote_change()

    def test_uniform_but_outdated_provider_date_is_not_latest_eod(self):
        rows = self.prices()
        for row in rows:
            row["date"] = "2026-10-02"
        self.write_prices(rows)
        self.reject_without_remote_change()

    def test_nonfinite_or_nonpositive_close_is_rejected(self):
        for value in ("nan", "inf", "0", "-1", ""):
            with self.subTest(value=value):
                rows = self.prices()
                rows[0]["close"] = value
                self.write_prices(rows)
                self.reject_without_remote_change()

    def test_forecast_missing_or_mismatched_price_date_or_collection_is_rejected(self):
        path = self.root / "forecasts/latest.json"
        original = path.read_bytes()
        for field, value in (("price", 1), ("asOf", "2026-10-02"),
                             ("sourceUpdatedAt", "2026-10-05T23:35:00Z"), ("history", [])):
            with self.subTest(field=field):
                payload = json.loads(original)
                payload["stocks"]["AAPL"][field] = value
                build_forecasts.atomic_json(path, payload)
                self.reject_without_remote_change()
        payload = json.loads(original)
        del payload["stocks"]["AAPL"]
        build_forecasts.atomic_json(path, payload)
        self.reject_without_remote_change()

    def test_missing_full_history_blocks_publication(self):
        (self.root / "prices/history/AAPL.json").unlink()
        self.reject_without_remote_change()

    def test_downloaded_history_endpoint_must_match_csv_close(self):
        path = self.root / "prices/history/AAPL.json"
        payload = json.loads(path.read_bytes())
        payload["prices"][-1]["close"] = 1
        build_forecasts.atomic_json(path, payload)
        self.reject_without_remote_change()

    def test_actual_collector_failure_retains_rows_but_gate_prevents_publication(self):
        import pandas as pd
        import update_eod_prices as collector

        self.write_snapshot(self.root, "2026-10-02", "2026-10-04T01:26:05+00:00")
        one = pd.DataFrame({"Close": [90, 100], "Volume": [1000, 1200]},
                           index=pd.to_datetime(["2026-10-01", "2026-10-05"]))
        receipt_path = self.base / "request.json"
        with patch.object(collector, "OUT_PATH", self.root / "prices/latest_prices.csv"), \
             patch.object(collector, "download_public_chart", return_value=pd.concat({"SPY": one}, axis=1)), \
             patch.object(collector, "read_symbols", side_effect=AssertionError("Public mode must not read Sheets")), \
             patch.object(collector, "datetime") as clock, contextlib.redirect_stdout(io.StringIO()):
            clock.now.return_value = publication.timestamp(self.receipt["updatedAt"])
            self.assertEqual(collector.main(["--public-prices-only", "--receipt", str(receipt_path)]), 0)
        self.receipt = json.loads(receipt_path.read_text())
        self.assertEqual(set(self.receipt["symbols"]), set(self.symbols))
        self.assertEqual(len(self.prices()), len(self.symbols))
        self.assertEqual({r["date"] for r in self.prices()}, {"2026-10-02", "2026-10-05"})
        with contextlib.redirect_stdout(io.StringIO()):
            build_forecasts.build(self.root, "2026-10-05T23:41:00+00:00")
        self.reject_without_remote_change()

    def prepare_recovered_collection(self):
        import pandas as pd
        import update_eod_prices as collector
        from test_eod_close_fallback import AS_OF, FixedClock, recovered_fixture, sample_frame

        self.write_snapshot(self.root, "2026-10-02", "2026-10-04T01:26:05+00:00")
        fixed, evidence = recovered_fixture("AAPL")
        good = sample_frame()
        good.loc[good.index[-1], "Close"] = 95.4
        frames = {s: fixed if s == "AAPL" else good for s in self.symbols}
        data = pd.concat(frames, axis=1)
        data.attrs["eodRecoveries"] = {"AAPL": evidence}
        receipt_path = self.base / "recovered-request.json"
        with patch.object(collector, "OUT_PATH", self.root / "prices/latest_prices.csv"), \
             patch.object(collector, "download_public_chart", return_value=data), \
             patch.object(collector, "datetime", FixedClock), \
             patch.object(collector, "read_symbols", side_effect=AssertionError("Must not read Sheets")), \
             contextlib.redirect_stdout(io.StringIO()):
            collector.main(["--public-prices-only", "--receipt", str(receipt_path)])
            build_forecasts.build(self.root, "2026-10-06T02:00:00Z")
        self.receipt = json.loads(receipt_path.read_text())
        self.assertEqual({row["date"] for row in self.prices()}, {AS_OF})
        return evidence

    def test_recovered_bar_requires_evidence_and_publishes_with_all_other_symbols(self):
        from eod_close_fallback import SOURCE, decode_evidence

        evidence = self.prepare_recovered_collection()
        manifest = self.publish()
        self.assertEqual(manifest["symbolCount"], len(self.symbols))
        rows = list(csv.DictReader(io.StringIO(self.remote_file("prices/latest_prices.csv"))))
        recovered = next(row for row in rows if row["symbol"] == "AAPL")
        self.assertEqual(recovered["source"], SOURCE)
        self.assertEqual(decode_evidence(recovered["eodProvenance"]), evidence)
        self.assertEqual(float(recovered["close"]), 95.4)
        self.assertEqual(float(recovered["volume"]), 1305)
        changed = publication.git(self.remote, "diff", "--name-only", self.original, "main").splitlines()
        self.assertTrue(all(path.startswith(("prices/", "forecasts/")) for path in changed))

    def test_missing_tampered_or_mismatched_secondary_evidence_blocks_entire_publication(self):
        from eod_close_fallback import encode_evidence

        evidence = self.prepare_recovered_collection()
        original_rows = self.prices()
        path = self.root / "prices/history/AAPL.json"
        original_history = json.loads(path.read_bytes())
        for fault in ("missing", "hash", "ohlcv", "source"):
            rows = [dict(row) for row in original_rows]
            history = json.loads(json.dumps(original_history))
            row = next(row for row in rows if row["symbol"] == "AAPL")
            if fault == "missing":
                row["eodProvenance"] = ""
                history.pop("eodRecovery")
            elif fault == "hash":
                bad = {**evidence, "responseSha256": "0" * 64}
                row["eodProvenance"] = encode_evidence(bad)
                history["eodRecovery"] = bad
            elif fault == "ohlcv":
                row["volume"] = "1300"
            else:
                row["source"] = "Yahoo only"
            self.write_prices(rows)
            build_forecasts.atomic_json(path, history)
            with self.subTest(fault=fault):
                self.reject_without_remote_change()

    def test_successful_secondary_recovery_cannot_hide_another_stale_symbol(self):
        self.prepare_recovered_collection()
        rows = self.prices()
        next(row for row in rows if row["symbol"] == "MSFT")["date"] = "2026-10-02"
        self.write_prices(rows)
        self.reject_without_remote_change()

    def test_unrelated_main_update_is_preserved_during_public_rebase(self):
        other = self.other_checkout()
        (other / "market/home.json").write_text('{"recap":"Monday"}')
        publication.git(other, "add", "market/home.json")
        publication.git(other, "commit", "-m", "Concurrent homepage update")
        publication.git(other, "push", "origin", "main")
        self.publish()
        self.assertEqual(json.loads(self.remote_file("market/home.json"))["recap"], "Monday")

    def test_concurrent_newer_public_snapshot_cannot_be_overwritten_by_rebase(self):
        other = self.other_checkout()
        self.write_snapshot(other, "2026-10-06", "2026-10-06T23:40:00+00:00")
        publication.git(other, "add", "prices/latest_prices.csv", "forecasts")
        publication.git(other, "commit", "-m", "Concurrent complete newer EOD")
        publication.git(other, "push", "origin", "main")
        advanced = self.remote_head()
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            self.publish()
        self.assertEqual(self.remote_head(), advanced)
        current = json.loads(self.remote_file("forecasts/latest.json"))["stocks"]
        self.assertEqual({s["asOf"] for s in current.values()}, {"2026-10-06"})

    def test_first_issued_archive_survives_the_early_publication(self):
        before = list(csv.DictReader(io.StringIO(self.remote_file("forecasts/archive/2026-10.csv"))))
        self.publish()
        after = list(csv.DictReader(io.StringIO(self.remote_file("forecasts/archive/2026-10.csv"))))
        self.assertEqual(after[:len(before)], before)
        self.assertEqual(len(after), len(before) + 2 * len(self.symbols))

    def test_research_restores_exact_full_histories_without_redownload(self):
        manifest = self.publish()
        for path in (self.root / "prices/history").glob("*.json"):
            path.unlink()
        publication.restore_research(self.root, self.bundle)
        actual = publication.validate(self.root, self.receipt)
        self.assertEqual(actual["historyFiles"], manifest["historyFiles"])
        self.assertEqual(publication.git(self.root, "rev-parse", "HEAD"), manifest["sourceCommit"])

    def test_incomplete_research_transfer_is_rejected(self):
        manifest = self.publish()
        with tarfile.open(self.bundle / "histories.tar.gz", "w:gz") as archive:
            for path in list(manifest["historyFiles"])[1:]:
                archive.add(self.root / path, arcname=path)
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            publication.restore_research(self.root, self.bundle)

    def test_changed_research_transfer_is_rejected_before_history_replacement(self):
        manifest = self.publish()
        path = self.root / "prices/history/AAPL.json"
        path.write_text('{"changed":true}')
        with tarfile.open(self.bundle / "histories.tar.gz", "w:gz") as archive:
            for relative in manifest["historyFiles"]:
                archive.add(self.root / relative, arcname=relative)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            publication.restore_research(self.root, self.bundle)
        self.assertEqual(path.read_text(), '{"changed":true}')

    def test_research_uses_separate_ml_only_commit_and_preserves_public_inputs(self):
        self.publish()
        published_head = self.remote_head()
        prices_before = self.remote_file("prices/latest_prices.csv")
        forecasts_before = self.remote_file("forecasts/latest.json")
        (self.root / "ml/latest.json").write_text('{"status":"failed","newResearch":true}')
        self.assertTrue(publication.publish_research(self.root, self.bundle))
        self.assertEqual(publication.git(self.remote, "diff", "--name-only", published_head, "main"), "ml/latest.json")
        self.assertEqual(self.remote_file("prices/latest_prices.csv"), prices_before)
        self.assertEqual(self.remote_file("forecasts/latest.json"), forecasts_before)

    def test_superseded_research_does_not_overwrite_a_new_public_session(self):
        self.publish()
        (self.root / "ml/latest.json").write_text('{"status":"failed","oldSnapshotResearch":true}')
        other = self.other_checkout()
        self.write_snapshot(other, "2026-10-06", "2026-10-06T23:40:00+00:00")
        publication.git(other, "add", "prices/latest_prices.csv", "forecasts")
        publication.git(other, "commit", "-m", "New complete public EOD")
        publication.git(other, "push", "origin", "main")
        advanced = self.remote_head()
        self.assertFalse(publication.publish_research(self.root, self.bundle))
        self.assertEqual(self.remote_head(), advanced)
        self.assertNotIn("oldSnapshotResearch", self.remote_file("ml/latest.json"))

class WorkflowTests(unittest.TestCase):
    def load(self, filename):
        return yaml.load((publication.ROOT / ".github/workflows" / filename).read_text(), Loader=yaml.BaseLoader)

    def test_home_starts_from_fast_completion_and_research_keeps_original_step_order(self):
        public = self.load("update-eod-prices.yml")
        research = self.load("update-eod-research.yml")
        home = self.load("market-home.yml")
        decision = self.load("update-decision-support.yml")
        self.assertIn(public["name"], home["on"]["workflow_run"]["workflows"])
        self.assertNotIn(research["name"], home["on"]["workflow_run"]["workflows"])
        self.assertEqual(research["on"]["workflow_run"]["workflows"], [public["name"]])
        self.assertIn(research["name"], decision["on"]["workflow_run"]["workflows"])
        self.assertNotIn(public["name"], decision["on"]["workflow_run"]["workflows"])
        self.assertNotEqual(public["concurrency"]["group"], research["concurrency"]["group"])
        self.assertEqual(decision["concurrency"]["group"], research["concurrency"]["group"])
        self.assertEqual(public["on"]["schedule"], [{"cron": "30 23 * * 1-5"}])
        public_steps = public["jobs"]["update-eod-prices"]["steps"]
        runs = [s["run"] for s in public_steps if "run" in s]
        self.assertLess(next(i for i, r in enumerate(runs) if "build_forecasts.py" in r),
                        next(i for i, r in enumerate(runs) if "eod_publication.py publish " in r))
        expected = ["build_learned_forecasts.py", "audit_learned_results.py", "build_stability_research.py",
                    "build_forecast_comparison.py", "build_adaptive_research.py", "score_live_forecasts.py"]
        commands = [s.get("run", "") for s in research["jobs"]["research"]["steps"]]
        self.assertEqual([r.removeprefix("python scripts/") for r in commands
                          if r.startswith("python scripts/") and r.endswith(".py")], expected)
        for script in expected:
            self.assertNotIn(script, "\n".join(runs))
        self.assertNotIn("update_eod_prices.py", "\n".join(commands))
        self.assertNotIn("build_forecasts.py", "\n".join(commands))
        self.assertIn("conclusion == 'success'", research["jobs"]["research"]["if"])
        self.assertEqual(research["on"]["workflow_run"]["branches"], ["main"])


if __name__ == "__main__":
    unittest.main()
