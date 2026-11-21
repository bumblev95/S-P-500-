import unittest
from datetime import datetime, timezone

from audit_prospective_blend_enrollment import available_groups, required_summary


REGISTERED = datetime(2026, 10, 23, 12, 28, 17, tzinfo=timezone.utc)


class EnrollmentAuditTests(unittest.TestCase):
    def test_required_summary_does_not_count_pre_registration_rows(self):
        rows = [
            {"model": "required", "horizon": "21", "asOf": "2026-09-11",
             "symbol": "OLD", "issuedAt": "2026-09-13T09:48:03Z"},
            {"model": "required", "horizon": "21", "asOf": "2026-10-23",
             "symbol": "TOO_EARLY", "issuedAt": "2026-10-23T12:00:00Z"},
            {"model": "required", "horizon": "21", "asOf": "2026-10-23",
             "symbol": "OK", "issuedAt": "2026-10-23T13:00:00Z"},
        ]
        summary = required_summary(
            rows, model="required", horizon=21, registered_at=REGISTERED,
            minimum_origin="2026-10-23",
        )
        self.assertEqual(summary["totalRows"], 3)
        self.assertEqual(summary["postRegistrationRows"], 1)
        self.assertEqual(summary["postRegistrationOrigins"], ["2026-10-23"])
        self.assertEqual(summary["latestOrigin"], "2026-10-23")

    def test_available_groups_keeps_model_and_horizon_separate(self):
        rows = [
            {"model": "v2", "horizon": "126", "asOf": "2026-10-23",
             "symbol": "A", "issuedAt": "2026-10-23T20:00:00Z"},
            {"model": "v2", "horizon": "252", "asOf": "2026-10-23",
             "symbol": "A", "issuedAt": "2026-10-23T20:00:00Z"},
        ]
        groups = available_groups(
            rows, registered_at=REGISTERED, minimum_origin="2026-10-23")
        self.assertEqual([(row["model"], row["horizon"], row["rows"]) for row in groups],
                         [("v2", "126", 1), ("v2", "252", 1)])


if __name__ == "__main__":
    unittest.main()
