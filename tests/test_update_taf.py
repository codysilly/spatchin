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
from urllib.parse import parse_qs, urlsplit
from scripts.c070_station_registry import load_c070_stations

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
        guard = mock.patch.object(
            self.module.urllib.request,
            "urlopen",
            side_effect=AssertionError("Unexpected network access"),
        )
        guard.start()
        self.addCleanup(guard.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.module.DEST = Path(self.directory.name) / "data" / "tafs.json"
        self.now = datetime.now(timezone.utc).timestamp()

    def report(self, code, *, issue_hours=1, text=None):
        issued = self.now - issue_hours * 3600
        return {
            "icaoId": code,
            "issueTime": datetime.fromtimestamp(issued, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "validTimeFrom": int(issued - 600),
            "validTimeTo": int(issued + 24 * 3600),
            "rawTAF": text or f"TAF {code} SYNTHETIC",
        }

    def previous(self, reports):
        path = self.module.DEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"updated_utc": "2026-01-01T00:00:00Z", "source": self.module.URL, "tafs": reports}
            ),
            encoding="utf-8",
        )
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

    def test_exact_130_station_request_and_registry_parity(self):
        stations = set(load_c070_stations().values())
        self.assertEqual(len(stations), 130)
        self.assertEqual(self.module.AIRPORTS, stations)
        url = urlsplit(self.module.URL)
        self.assertEqual(
            (url.scheme, url.netloc, url.path), ("https", "aviationweather.gov", "/api/data/taf")
        )
        self.assertEqual(
            parse_qs(url.query), {"ids": [",".join(sorted(stations))], "format": ["json"]}
        )
        self.collect([self.report("KIWA")])
        self.assertEqual([item["icaoId"] for item in self.snapshot()["tafs"]], ["KIWA"])

    def test_partial_expansion_with_absent_invalid_and_older_reports(self):
        current = self.report("KABE", issue_hours=1)
        absent = self.report("KABQ", issue_hours=2)
        rejected = self.report("KAFW", issue_hours=2)
        self.previous([current, absent, rejected])
        valid_new = self.report("KIWA")
        bad = dict(self.report("KAFW"), rawTAF=" ")
        with mock.patch("builtins.print") as log:
            self.collect(
                [
                    self.report("KABE", issue_hours=3),
                    bad,
                    valid_new,
                    None,
                    {"icaoId": ["KABE"]},
                    {"icaoId": {}},
                    self.report("ZZZZ"),
                ]
            )
        result = {x["icaoId"]: x for x in self.snapshot()["tafs"]}
        self.assertEqual(
            result, {"KABE": current, "KABQ": absent, "KAFW": rejected, "KIWA": valid_new}
        )
        self.assertTrue(
            any("2 valid station reports of 130" in str(call) for call in log.call_args_list)
        )

    def test_equal_issue_duplicate_does_not_erase_decoded_periods(self):
        item = self.report("KIWA")
        start = item["validTimeFrom"]
        detailed = dict(
            item, fcsts=[{"timeFrom": start, "timeTo": start + 3600, "wdir": "VRB", "wspd": 5}]
        )
        self.assertEqual(self.module.select([detailed, item])["KIWA"], detailed)
        self.assertEqual(self.module.select([item, detailed])["KIWA"], detailed)

    def test_malformed_station_and_timestamp_do_not_abort_other_records(self):
        good = self.report("KIND")
        for changes in (
            {"icaoId": []},
            {"icaoId": {}},
            {"icaoId": None},
            {"issueTime": True},
            {"issueTime": float("nan")},
            {"validTimeTo": "invalid"},
            {"rawTAF": 42},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(self.module.valid(dict(good, **changes)))
        self.assertEqual(self.module.select([dict(good, icaoId=[]), good]), {"KIND": good})

    def test_full_success_and_exact_source_text(self):
        items = [self.report(c) for c in sorted(self.module.AIRPORTS)]
        items[0]["rawTAF"] = f"TAF {items[0]['icaoId']} 201200Z <test> & 18010KT"
        self.collect(items)
        snapshot = self.snapshot()
        self.assertEqual(set(x["icaoId"] for x in snapshot["tafs"]), self.module.AIRPORTS)
        self.assertEqual(snapshot["source"], self.module.URL)
        self.assertTrue(snapshot["updated_utc"].endswith("Z"))
        self.assertEqual(snapshot["tafs"][0]["rawTAF"], items[0]["rawTAF"])
        self.assertEqual(
            set(snapshot["tafs"][0]),
            {"icaoId", "rawTAF", "issueTime", "validTimeFrom", "validTimeTo"},
        )

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

    def test_awc_decoded_forecast_periods_saved_with_raw_text(self):
        item = self.report("KMEM")
        start = item["validTimeFrom"]
        item["fcsts"] = [
            {
                "timeFrom": start,
                "timeTo": start + 3600,
                "fcstChange": None,
                "wdir": 270,
                "wspd": 18,
                "wgst": 26,
                "clouds": [{"cover": "BKN", "base": 1000}],
            },
            {
                "timeFrom": start + 3600,
                "timeTo": start + 7200,
                "fcstChange": "TEMPO",
                "wdir": "VRB",
                "wspd": 12,
                "wgst": 22,
            },
        ]
        self.collect([item])
        saved = self.snapshot()["tafs"][0]
        self.assertEqual(saved["rawTAF"], item["rawTAF"])
        self.assertEqual(saved["fcsts"][0]["wdir"], 270)
        self.assertEqual(saved["fcsts"][0]["wgst"], 26)
        self.assertEqual(saved["fcsts"][1]["fcstChange"], "TEMPO")
        self.assertNotIn("clouds", saved["fcsts"][0])

    def test_existing_same_issue_is_backfilled_with_fcsts(self):
        item = self.report("KJFK")
        self.previous([item])
        start = item["validTimeFrom"]
        incoming = dict(
            item,
            fcsts=[
                {
                    "timeFrom": start,
                    "timeTo": start + 3600,
                    "fcstChange": "FM",
                    "wdir": 80,
                    "wspd": 10,
                }
            ],
        )
        self.collect([incoming])
        self.assertEqual(len(self.snapshot()["tafs"][0]["fcsts"]), 1)
        before = self.module.DEST.read_bytes()
        self.collect([item])
        self.assertEqual(self.module.DEST.read_bytes(), before)

    def test_bad_periods_not_used_for_wind_projection(self):
        item = self.report("KMEM")
        start = item["validTimeFrom"]
        item["fcsts"] = [
            {"timeFrom": start + 3600, "timeTo": start, "wdir": 90, "wspd": 8},
            {"timeFrom": "bad", "timeTo": start + 3600, "wdir": 90, "wspd": 8},
            {"timeFrom": start, "timeTo": start + 3600, "wdir": 210, "wspd": 15},
        ]
        self.collect([item])
        self.assertEqual(len(self.snapshot()["tafs"][0]["fcsts"]), 1)
        self.assertEqual(self.snapshot()["tafs"][0]["fcsts"][0]["wdir"], 210)


if __name__ == "__main__":
    unittest.main()
