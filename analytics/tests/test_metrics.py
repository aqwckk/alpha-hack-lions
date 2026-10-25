"""Regression checks for empty metric subgroups."""

import unittest

from src.metrics import compute_metrics


class MetricsTests(unittest.TestCase):
    def test_medians_with_empty_subgroups(self):
        cases = [
            ("empty", (), (None, None, None, None)),
            ("draft_only", (None,), (None, None, None, None)),
            ("manual_only", ("MANUAL",), (40, None, 60, 1.0)),
            ("auto_only", ("AUTO",), (20, 20, 60, None)),
            ("mixed", ("MANUAL", "AUTO"), (30, 20, 60, 1.0)),
        ]
        for name, modes, expected in cases:
            with self.subTest(case=name):
                events = []
                for i, mode in enumerate(modes):
                    def add(event_type, occurred_at, payload):
                        events.append({
                            "application_id": str(i), "event_type": event_type,
                            "occurred_at": occurred_at, "payload": payload,
                        })

                    add("APPLICATION_CREATED", "2026-10-01T00:00:00Z", {})
                    if mode is not None:
                        add("APPLICATION_SUBMITTED", "2026-10-01T00:01:00Z", {"fill_duration_sec": 60})
                        duration = 20 if mode == "AUTO" else 40
                        add("DECISION_MADE", f"2026-10-01T00:01:{duration:02d}Z", {
                            "outcome": "DECLINED", "mode": mode,
                            "time_from_submit_sec": duration, "override": False,
                        })
                metrics = compute_metrics(events, "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z")
                self.assertEqual(tuple(metrics[key] for key in (
                    "time_to_decision_median_sec", "time_to_decision_auto_median_sec",
                    "fill_duration_median_sec", "manual_review_sla_share",
                )), expected)


if __name__ == "__main__":
    unittest.main()
