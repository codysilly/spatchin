import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "update_metar.py"


def load_module():
    spec = importlib.util.spec_from_file_location("update_metar", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(code, observed, raw=None):
    return {
        "icaoId": code,
        "obsTime": observed,
        "rawOb": raw or f"{code} SYNTHETIC TEST OBSERVATION",
        "wdir": 180,
        "wspd": 8,
        "fltCat": "VFR",
    }


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class UpdateMetarTests(unittest.TestCase):
    NOW = 1_800_000_000

    def setUp(self):
        self.module = load_module()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.module.DEST = Path(self.temporary.name) / "data" / "metars.json"
        self.time = mock.patch.object(self.module.time, "time", return_value=self.NOW)
        self.sleep = mock.patch.object(self.module.time, "sleep")
        self.time.start()
        self.sleep.start()
        self.addCleanup(self.time.stop)
        self.addCleanup(self.sleep.stop)

    def write_previous(self, metars, updated="2027-01-01T00:00:00Z"):
        self.module.DEST.parent.mkdir(parents=True, exist_ok=True)
        self.module.DEST.write_text(json.dumps({
            "updated_utc": updated,
            "source": self.module.URL,
            "metars": metars,
        }) + "\n")

    def run_with(self, payload):
        with mock.patch.object(self.module.urllib.request, "urlopen", return_value=Response(payload)):
            self.module.main()

    def snapshot(self):
        return json.loads(self.module.DEST.read_text())

    def test_valid_awc_response_and_dashboard_compatible_output(self):
        payload = [report(code, self.NOW - index * 60) for index, code in enumerate(sorted(self.module.AIRPORTS))]
        self.run_with(payload)
        saved = self.snapshot()
        self.assertEqual(set(saved), {"updated_utc", "source", "metars"})
        self.assertTrue(saved["updated_utc"].endswith("Z"))
        self.assertEqual([item["icaoId"] for item in saved["metars"]], sorted(self.module.AIRPORTS))
        for item in saved["metars"]:
            self.assertIsInstance(item["obsTime"], (int, float))
            self.assertTrue(item["rawOb"])

    def test_missing_airports_are_preserved_from_previous_snapshot(self):
        old = [report("KORD", self.NOW - 7200), report("KLAX", self.NOW - 3600)]
        self.write_previous(old)
        self.run_with([report("KORD", self.NOW - 60)])
        saved = {item["icaoId"]: item for item in self.snapshot()["metars"]}
        self.assertEqual(saved["KLAX"], old[1])
        self.assertEqual(saved["KORD"]["obsTime"], self.NOW - 60)

    def test_partial_response_ignores_invalid_item_and_keeps_old_data(self):
        old = report("KJFK", self.NOW - 1800)
        self.write_previous([old])
        self.run_with([report("KMEM", self.NOW - 60), {"icaoId": "KJFK", "obsTime": self.NOW}])
        saved = {item["icaoId"]: item for item in self.snapshot()["metars"]}
        self.assertEqual(saved["KJFK"], old)
        self.assertEqual(saved["KMEM"]["obsTime"], self.NOW - 60)

    def test_invalid_response_fails_and_preserves_file(self):
        self.write_previous([report("KORD", self.NOW - 60)])
        before = self.module.DEST.read_bytes()
        with mock.patch.object(self.module.urllib.request, "urlopen", return_value=Response({"bad": "shape"})):
            with self.assertRaises(SystemExit):
                self.module.main()
        self.assertEqual(self.module.DEST.read_bytes(), before)

    def test_stale_new_observation_is_rejected_but_old_valid_data_is_preserved(self):
        previous = report("KORD", self.NOW - 8 * 86400)
        self.write_previous([previous])
        before = self.module.DEST.read_bytes()
        with mock.patch.object(self.module.urllib.request, "urlopen", return_value=Response([
            report("KORD", self.NOW - 8 * 86400)
        ])):
            with self.assertRaises(SystemExit):
                self.module.main()
        self.assertEqual(self.module.DEST.read_bytes(), before)

    def test_network_failure_is_reported_and_preserves_file(self):
        self.write_previous([report("KORD", self.NOW - 60)])
        before = self.module.DEST.read_bytes()
        error = urllib.error.URLError("synthetic offline failure")
        with mock.patch.object(self.module.urllib.request, "urlopen", side_effect=error):
            with redirect_stderr(io.StringIO()) as stderr, redirect_stdout(io.StringIO()) as stdout, self.assertRaises(SystemExit):
                self.module.main()
        self.assertIn("AWC unavailable after retries", stderr.getvalue())
        self.assertNotIn("reason=missing_upstream", stdout.getvalue())
        self.assertEqual(self.module.DEST.read_bytes(), before)

    def test_older_response_never_replaces_newer_previous_observation(self):
        previous = report("KORD", self.NOW - 60)
        self.write_previous([previous])
        before = self.module.DEST.read_bytes()
        self.run_with([report("KORD", self.NOW - 120)])
        self.assertEqual(self.module.DEST.read_bytes(), before)

    def test_repeated_collection_without_changes_does_not_rewrite_file(self):
        current = report("KMEM", self.NOW - 60)
        self.write_previous([current])
        before = self.module.DEST.read_bytes()
        self.run_with([current])
        self.assertEqual(self.module.DEST.read_bytes(), before)

    def test_log_missing_upstream_distinct_from_rejected_and_no_rewrite(self):
        prior = report("KORD", self.NOW - 7200)
        live = report("KMEM", self.NOW - 30)
        self.write_previous([prior, live])
        before = self.module.DEST.read_bytes()
        with redirect_stdout(io.StringIO()) as stdout:
            self.run_with([live])
        output = stdout.getvalue()
        self.assertIn("METAR KORD retained: reason=missing_upstream", output)
        self.assertIn("candidates=0; rejected=none", output)
        self.assertIn("METAR KMEM retained: reason=unchanged_upstream", output)
        self.assertEqual(self.module.DEST.read_bytes(), before)

    def test_log_invalid_upstream_reports_validation_reasons(self):
        prior = report("KORD", self.NOW - 7200)
        self.write_previous([prior])
        bad = {"icaoId": "KORD", "obsTime": self.NOW - 30}
        good = report("KMEM", self.NOW - 30)
        with redirect_stdout(io.StringIO()) as stdout:
            self.run_with([bad, good])
        self.assertIn("METAR KORD retained: reason=rejected_upstream", stdout.getvalue())
        self.assertIn("candidates=1; rejected=missing_raw_observation:1", stdout.getvalue())
        self.assertEqual({m["icaoId"]:m for m in self.snapshot()["metars"]}["KORD"], prior)

    def test_log_older_upstream_and_preserve_file(self):
        prior = report("KORD", self.NOW - 60)
        self.write_previous([prior])
        before = self.module.DEST.read_bytes()
        with redirect_stdout(io.StringIO()) as stdout:
            self.run_with([report("KORD", self.NOW - 120)])
        self.assertIn("METAR KORD retained: reason=older_upstream", stdout.getvalue())
        self.assertIn("upstream_obs=", stdout.getvalue())
        self.assertEqual(self.module.DEST.read_bytes(), before)

    def test_log_rejected_freshness_future_and_wind(self):
        previous = report("KORD", self.NOW - 300)
        self.write_previous([previous])
        payload = [report("KMEM", self.NOW - 30),
                   report("KORD", self.NOW - 8*86400),
                   report("KORD", self.NOW + 1800),
                   {**report("KORD", self.NOW - 30), "wspd": -1}]
        with redirect_stdout(io.StringIO()) as stdout:
            self.run_with(payload)
        output = stdout.getvalue()
        self.assertIn("reason=rejected_upstream", output)
        self.assertIn("future_observation:1", output)
        self.assertIn("negative_wind_speed:1", output)
        self.assertIn("outside_7_day_window:1", output)

    def test_partial_invalid_and_valid_candidates_prefer_newest(self):
        old = report("KORD", self.NOW - 3600)
        self.write_previous([old])
        payload = [{"icaoId":"KORD", "obsTime":self.NOW-60},
                   report("KORD", self.NOW - 180), report("KORD", self.NOW - 60),
                   report("KMEM", self.NOW - 90)]
        with redirect_stdout(io.StringIO()) as stdout:
            self.run_with(payload)
        self.assertNotIn("METAR KORD retained:", stdout.getvalue())
        self.assertEqual({m["icaoId"]:m for m in self.snapshot()["metars"]}["KORD"]["obsTime"],self.NOW-60)

    def test_all_rejected_logs_reason_and_preserves_file(self):
        prior=report("KORD",self.NOW-3600)
        self.write_previous([prior]); before=self.module.DEST.read_bytes()
        bad={"icaoId":"KORD", "obsTime":self.NOW-30}
        with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
            with mock.patch.object(self.module.urllib.request, "urlopen", return_value=Response([bad])):
                with self.assertRaises(SystemExit):
                    self.module.main()
        self.assertIn("METAR KORD retained: reason=rejected_upstream",stdout.getvalue())
        self.assertIn("AWC unavailable after retries",stderr.getvalue())
        self.assertEqual(self.module.DEST.read_bytes(),before)


if __name__ == "__main__":
    unittest.main()
