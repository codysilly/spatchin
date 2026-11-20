"""Offline synthetic TAF collector tests. Never contact AWC."""
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from urllib.error import URLError

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_taf.py"


def load():
    spec = importlib.util.spec_from_file_location("taf_collector_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, value):
        self.stream = io.BytesIO(json.dumps(value).encode("utf-8"))

    def __enter__(self):
        return self.stream

    def __exit__(self, *_):
        return False


class TafCollectorTests(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.module.DEST = Path(self.directory.name) / "data" / "tafs.json"
        self.now = datetime.now(timezone.utc).timestamp()

    def report(self, code, *, issue_hours=1, text=None):
        issued = self.now - issue_hours * 3600
        return {
            "icaoId": code,
            "issueTime": datetime.fromtimestamp(issued, timezone.utc).isoformat().replace("+00:00", "Z"),
            "validTimeFrom": int(issued - 600),
            "validTimeTo": int(issued + 24 * 3600),
            "rawTAF": text or f"TAF {code} SYNTHETIC",
        }

    def previous(self, reports):
        path = self.module.DEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"updated_utc": "2026-01-01T00:00:00Z",
                                    "source": self.module.URL, "tafs": reports}), encoding="utf-8")
        return path.read_bytes()

    def collect(self, response):
        with mock.patch.object(self.module.urllib.request, "urlopen") as open_url:
            if isinstance(response, Exception):
                open_url.side_effect = response
            else:
                open_url.return_value = Response(response)
            self.module.main()
            if not isinstance(response, Exception):
                self.assertEqual(open_url.call_count, 1)
                req = open_url.call_args.args[0]
                self.assertEqual(req.full_url, self.module.URL)

    def snapshot(self):
        return json.loads(self.module.DEST.read_text(encoding="utf-8"))

    def test_full_success_and_exact_source_text(self):
        items = [self.report(c) for c in sorted(self.module.AIRPORTS)]
        items[0]["rawTAF"] = "TAF KJFK 201200Z <test> & 18010KT"
        self.collect(items)
        snapshot = self.snapshot()
        self.assertEqual(set(x["icaoId"] for x in snapshot["tafs"]), self.module.AIRPORTS)
        self.assertEqual(snapshot["source"], self.module.URL)
        self.assertTrue(snapshot["updated_utc"].endswith("Z"))
        self.assertEqual(snapshot["tafs"][0]["rawTAF"], items[0]["rawTAF"])
        self.assertEqual(set(snapshot["tafs"][0]), {
            "icaoId", "rawTAF", "issueTime", "validTimeFrom", "validTimeTo"})

    def test_partial_outage_retains_previous_reports(self):
        old = self.report("KORD", issue_hours=4)
        self.previous([old])
        self.collect([self.report("KLAX")])
        result = {x["icaoId"]: x for x in self.snapshot()["tafs"]}
        self.assertEqual(result["KORD"], old)
        self.assertIn("KLAX", result)

    def test_older_report_does_not_replace_newer(self):
        current = self.report("KMEM", issue_hours=1)
        prior = self.previous([current])
        self.collect([self.report("KMEM", issue_hours=8)])
        self.assertEqual(self.module.DEST.read_bytes(), prior)

    def test_same_report_does_not_rewrite_snapshot(self):
        current = self.report("KJFK")
        prior = self.previous([current])
        self.collect([current])
        self.assertEqual(self.module.DEST.read_bytes(), prior)

    def test_rejects_wrong_airport_blank_future_and_bad_validity(self):
        wrong = self.report("KAAA")
        blank = self.report("KMEM", text=" ")
        future = self.report("KORD", issue_hours=-3)
        bad = self.report("KLAX")
        bad["validTimeTo"] = bad["validTimeFrom"]
        for record in (wrong, blank, future, bad):
            self.assertFalse(self.module.valid(record, now=self.now))
        self.assertFalse(self.module.valid({"icaoId": "KORD", "rawTAF": "TAF"}))
        with self.assertRaises(ValueError):
            self.module.select([wrong, blank, future, bad])

    def test_selects_newest_issue_per_station(self):
        old = self.report("KMEM", issue_hours=3)
        new = self.report("KMEM", issue_hours=1)
        chosen = self.module.select([old, new])
        self.assertEqual(chosen["KMEM"], new)

    def test_complete_provider_failure_preserves_file_and_fails(self):
        prior = self.previous([self.report("KORD")])
        with self.assertRaises(SystemExit) as caught:
            self.collect(URLError("synthetic network failure"))
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(self.module.DEST.read_bytes(), prior)

    def test_empty_and_unexpected_response_preserve_file(self):
        prior = self.previous([self.report("KORD")])
        for payload in ([], {"error": "unexpected"}):
            with self.assertRaises(SystemExit):
                self.collect(payload)
            self.assertEqual(self.module.DEST.read_bytes(), prior)

    def test_utc_zone_free_date_accepted(self):
        item = self.report("KORD")
        item["issueTime"] = item["issueTime"].replace("Z", "")
        self.assertTrue(self.module.valid(item, now=self.now))


if __name__ == "__main__":
    unittest.main()
