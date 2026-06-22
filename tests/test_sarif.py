"""Tests for the SARIF 2.1.0 exporter and the dual-position --format flag."""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alertmux import Engine, load_alerts  # noqa: E402
from alertmux.core import to_sarif  # noqa: E402
from alertmux.cli import main  # noqa: E402

DEMOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demos")
BASIC = os.path.join(DEMOS, "01-basic", "alerts.json")
SARIF_DEMO = os.path.join(DEMOS, "06-sarif-ci", "alerts.json")


def _incidents(path):
    with open(path, encoding="utf-8") as f:
        alerts = load_alerts(json.load(f))
    return Engine().process(alerts)


class TestSarif(unittest.TestCase):
    def test_basic_shape(self):
        log = to_sarif(_incidents(BASIC), "alertmux", "1.2.3")
        self.assertEqual(log["version"], "2.1.0")
        self.assertIn("$schema", log)
        run = log["runs"][0]
        self.assertEqual(run["tool"]["driver"]["name"], "alertmux")
        self.assertEqual(run["tool"]["driver"]["version"], "1.2.3")
        # one result per incident
        self.assertEqual(len(run["results"]), len(_incidents(BASIC)))

    def test_levels_and_security_severity(self):
        run = to_sarif(_incidents(SARIF_DEMO))["runs"][0]
        by_key = {r["properties"]["correlation_key"]: r for r in run["results"]}
        crit = by_key["service=checkout"]
        self.assertEqual(crit["level"], "error")           # critical -> error
        self.assertEqual(crit["properties"]["security-severity"], "9.0")
        info = by_key["service=monitoring"]
        self.assertEqual(info["level"], "note")            # info -> note
        self.assertEqual(info["properties"]["security-severity"], "1.0")

    def test_rules_registered_once(self):
        run = to_sarif(_incidents(SARIF_DEMO))["runs"][0]
        ids = [r["id"] for r in run["tool"]["driver"]["rules"]]
        self.assertEqual(len(ids), len(set(ids)))          # no duplicate descriptors
        # every result references a registered ruleIndex
        n = len(run["tool"]["driver"]["rules"])
        for res in run["results"]:
            self.assertTrue(0 <= res["ruleIndex"] < n)

    def test_fingerprint_present(self):
        run = to_sarif(_incidents(BASIC))["runs"][0]
        for res in run["results"]:
            self.assertIn("alertmuxIncidentId", res["partialFingerprints"])

    def test_cli_sarif_emits_valid_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "sarif", "mux", SARIF_DEMO])
        self.assertEqual(rc, 0)
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc["version"], "2.1.0")


class TestFormatFlagPosition(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(argv)
        return rc, buf.getvalue()

    def test_format_after_subcommand(self):
        rc, out = self._run(["mux", BASIC, "--format", "json"])
        self.assertEqual(rc, 0)
        self.assertIn("summary", json.loads(out))

    def test_format_before_subcommand(self):
        rc, out = self._run(["--format", "json", "mux", BASIC])
        self.assertEqual(rc, 0)
        self.assertIn("summary", json.loads(out))

    def test_sarif_after_subcommand(self):
        rc, out = self._run(["mux", SARIF_DEMO, "--format", "sarif"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["version"], "2.1.0")

    def test_default_is_table(self):
        rc, out = self._run(["mux", BASIC])
        self.assertEqual(rc, 0)
        self.assertIn("incidents=", out)  # table header


class TestAllDemosFire(unittest.TestCase):
    def test_every_demo_processes(self):
        for name in sorted(os.listdir(DEMOS)):
            apath = os.path.join(DEMOS, name, "alerts.json")
            if not os.path.isfile(apath):
                continue
            argv = ["mux", apath, "--format", "json"]
            rpath = os.path.join(DEMOS, name, "rules.json")
            if os.path.isfile(rpath):
                argv += ["--rules", rpath]
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(argv)
            self.assertEqual(rc, 0, f"demo {name} failed to run")
            doc = json.loads(buf.getvalue())
            self.assertGreaterEqual(doc["summary"]["incidents"], 1,
                                    f"demo {name} produced no incidents")


if __name__ == "__main__":
    unittest.main()
