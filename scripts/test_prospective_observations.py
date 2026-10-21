import json
import tempfile
import unittest
from pathlib import Path

from audit_prospective_observations import FOLDER, build, direction, sessions_after


class ProspectiveObservationTests(unittest.TestCase):
    def test_direction_boundaries_are_fixed(self):
        self.assertEqual(direction(-0.02001), -1)
        self.assertEqual(direction(-0.02), 0)
        self.assertEqual(direction(0.02), 0)
        self.assertEqual(direction(0.02001), 1)

    def test_target_is_twenty_first_open_weekday(self):
        sessions = sessions_after("2026-09-11", "2026-10-12")
        self.assertEqual(len(sessions), 21)
        self.assertEqual(sessions[-1], "2026-10-12")

    def test_saved_result_replays_exactly_and_fails_closed(self):
        saved = (FOLDER / "results.json").read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            result = build(Path(tmp))
            replay = (Path(tmp) / "results.json").read_bytes()
        self.assertEqual(saved, replay)
        self.assertFalse(result["fullCohort"]["aggregateMetricsAllowed"])
        self.assertGreater(result["fullCohort"]["missing"], 0)
        self.assertEqual(result["longHorizonReadiness"]["maturedRows"], {"126": 0, "252": 0})
        self.assertIsNone(result["selection"])
        self.assertEqual(result["blendEvaluation"], "not_run_post_target_design_would_be_diagnostic_only")

    def test_common_cohort_is_complete_and_not_the_full_universe(self):
        result = json.loads((FOLDER / "results.json").read_text())
        self.assertEqual(result["commonCohort"]["n"], 15)
        self.assertEqual(result["commonCohort"]["abstained"], 0)
        self.assertEqual(result["evaluation"]["v5HorizonModel"]["n"], 15)
        self.assertGreater(result["fullCohort"]["issued"], result["commonCohort"]["n"])


if __name__ == "__main__":
    unittest.main()
