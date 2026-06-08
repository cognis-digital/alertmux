"""Smoke tests for ALERTMUX. Standard library only, no network."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alertmux import (  # noqa: E402
    Engine, Alert, RoutingRule, load_alerts, load_rules,
    DEFAULT_RULES, TOOL_NAME, TOOL_VERSION,
)
from alertmux.cli import main  # noqa: E402

DEMO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "demos", "01-basic", "alerts.json")


class TestCore(unittest.TestCase):
    def setUp(self):
        with open(DEMO, encoding="utf-8") as f:
            self.alerts = load_alerts(json.load(f))

    def test_meta(self):
        self.assertEqual(TOOL_NAME, "alertmux")
        self.assertTrue(TOOL_VERSION)

    def test_load(self):
        self.assertEqual(len(self.alerts), 12)
        self.assertTrue(all(isinstance(a, Alert) for a in self.alerts))

    def test_dedup_collapses_repeats(self):
        eng = Engine()
        buckets = eng.dedup(self.alerts)
        # 12 raw events collapse to fewer distinct fingerprints
        self.assertLess(len(buckets), len(self.alerts))
        # the repeated PostgresDown (4 firing + 1 resolved) collapse to 1 bucket
        pg = [d for d in buckets.values() if d.alert.name == "PostgresDown"]
        self.assertEqual(len(pg), 1)
        self.assertEqual(pg[0].count, 5)
        self.assertEqual(pg[0].resolved, 1)

    def test_correlate_groups_by_service(self):
        eng = Engine()
        incidents = eng.process(self.alerts)
        # payments cascade -> 1 incident, checkout -> 1 incident
        self.assertEqual(len(incidents), 2)
        keys = {i.correlation_key for i in incidents}
        self.assertIn("service=payments", keys)
        self.assertIn("service=checkout", keys)

    def test_routing_pages_critical(self):
        eng = Engine()
        incidents = eng.process(self.alerts)
        payments = next(i for i in incidents if i.correlation_key == "service=payments")
        self.assertEqual(payments.severity, "critical")
        self.assertEqual(payments.receiver, "pagerduty")
        self.assertTrue(payments.page)
        checkout = next(i for i in incidents if i.correlation_key == "service=checkout")
        self.assertFalse(checkout.page)

    def test_window_splits_incidents(self):
        # a tiny window prevents grouping distinct-time alerts together
        eng = Engine(correlation_window_sec=0)
        incidents = eng.process(self.alerts)
        self.assertGreater(len(incidents), 2)

    def test_custom_rules(self):
        rules = load_rules([{"name": "all-slack", "receiver": "slack",
                             "min_severity": "info", "page": False}])
        eng = Engine(rules=rules)
        incidents = eng.process(self.alerts)
        self.assertTrue(all(i.receiver == "slack" and not i.page for i in incidents))

    def test_alert_normalization_aliases(self):
        a = Alert.from_raw({"name": "X", "severity": "crit", "status": "weird"})
        self.assertEqual(a.severity, "critical")
        self.assertEqual(a.status, "firing")

    def test_load_single_and_webhook_shapes(self):
        self.assertEqual(len(load_alerts({"name": "solo"})), 1)
        self.assertEqual(len(load_alerts([{"name": "a"}, {"name": "b"}])), 2)

    def test_default_rules_present(self):
        self.assertTrue(DEFAULT_RULES)
        self.assertIsInstance(DEFAULT_RULES[0], RoutingRule)


class TestCLI(unittest.TestCase):
    def test_mux_json(self):
        rc = main(["--format", "json", "mux", DEMO])
        self.assertEqual(rc, 0)

    def test_dedup_table(self):
        rc = main(["dedup", DEMO])
        self.assertEqual(rc, 0)

    def test_rules(self):
        rc = main(["rules"])
        self.assertEqual(rc, 0)

    def test_bad_path_nonzero(self):
        rc = main(["mux", "/nonexistent/path/alerts.json"])
        self.assertEqual(rc, 1)

    def test_bad_json_nonzero(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not json")
            path = f.name
        try:
            self.assertEqual(main(["mux", path]), 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
