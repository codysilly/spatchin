"""Offline regression tests for the independent METAR watchdog."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import metar_watchdog as watchdog

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
SECRET = "https://incidents.betterstack.com/api/v1/heartbeat/synthetic-test-token"


def snapshot(ages=(10, 10, 10, 10), updated=10):
    return {"updated_utc": (NOW-timedelta(minutes=updated)).isoformat(),
            "metars": [{"icaoId": x, "obsTime": (NOW-timedelta(minutes=age)).timestamp()}
                       for x, age in zip(("KJFK", "KLAX", "KMEM", "KORD"), ages)]}


class FakeResponse(io.BytesIO):
    status = 200
    def __init__(self, obj):
        super().__init__(json.dumps(obj).encode())


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "data.json"
        self.state = Path(self.tmp.name) / "state.json"

    def write(self, payload):
        self.data.write_text(json.dumps(payload), encoding="utf-8")

    def evaluate(self):
        with redirect_stdout(io.StringIO()):
            return watchdog.evaluate(self.data, self.state, now=NOW)

    def test_two_consecutive_widespread_stale_checks(self):
        self.write(snapshot((91, 92, 9, 9)))
        self.assertEqual(self.evaluate()["consecutive_widespread_stale"], 1)
        self.assertEqual(self.evaluate()["consecutive_widespread_stale"], 2)
        self.assertEqual(self.evaluate()["consecutive_widespread_stale"], 2)
        self.write(snapshot((10, 10, 10, 10)))
        self.assertEqual(self.evaluate()["consecutive_widespread_stale"], 0)

    def test_state_is_not_rewritten_when_unchanged(self):
        self.write(snapshot())
        self.evaluate()
        self.assertFalse(self.state.exists())
        self.write(snapshot((100, 100, 10, 10)))
        self.evaluate()
        before = self.state.stat().st_mtime_ns
        self.evaluate()
        self.assertNotEqual(self.state.stat().st_mtime_ns, before)
        before = self.state.stat().st_mtime_ns
        self.evaluate()
        self.assertEqual(self.state.stat().st_mtime_ns, before)

    def test_single_stale_station_is_not_an_incident(self):
        self.write(snapshot((999, 10, 10, 10)))
        self.assertEqual(self.evaluate()["consecutive_widespread_stale"], 0)

    def test_exact_90_min_is_not_stale(self):
        self.assertEqual(watchdog.count_stale(snapshot((90, 90, 10, 10)), NOW), (0, 4))

    def test_insufficient_coverage_refuses_to_pretend_healthy(self):
        with self.assertRaises(ValueError):
            watchdog.count_stale({"metars": [{"obsTime": 1}]}, NOW)

    def test_invalid_timestamp_is_not_silently_ignored(self):
        data = snapshot()
        data["metars"][0]["obsTime"] = True
        with self.assertRaises(ValueError):
            watchdog.count_stale(data, NOW)

    def test_no_secret_makes_no_network_calls(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(watchdog.notify(self.data, self.state, now=NOW,
                                             fetcher=lambda *a, **kw: self.fail("network"),
                                             sender=lambda *a, **kw: self.fail("network")))

    def test_healthy_heartbeat_without_site_lag(self):
        self.write(snapshot(updated=8))
        sent = []
        def sender(req, timeout):
            sent.append(req.full_url)
            return FakeResponse({})
        with patch.dict(os.environ, {watchdog.HEARTBEAT_ENV: SECRET}):
            self.assertTrue(watchdog.notify(self.data, self.state, now=NOW,
                            fetcher=lambda req, timeout: FakeResponse(snapshot(updated=8)), sender=sender))
        self.assertEqual(sent, [SECRET])

    def test_widespread_stale_sends_explicit_fail(self):
        self.write(snapshot((100, 100, 10, 10)))
        self.evaluate(); self.evaluate()
        sent = []
        with patch.dict(os.environ, {watchdog.HEARTBEAT_ENV: SECRET}):
            self.assertTrue(watchdog.notify(self.data, self.state, now=NOW,
                            fetcher=lambda req, timeout: FakeResponse(snapshot(updated=10)),
                            sender=lambda req, timeout: (sent.append(req.full_url) or FakeResponse({}))))
        self.assertEqual(sent, [SECRET + "/fail"])

    def test_publication_lag_requires_both_threshold_and_grace(self):
        def check(repo_age, public_age):
            return watchdog.public_lag(snapshot(updated=repo_age), now=NOW,
                   fetcher=lambda req, timeout: FakeResponse(snapshot(updated=public_age)))
        self.assertFalse(check(10, 25))
        self.assertTrue(check(10, 35))
        self.assertFalse(check(3, 35))
        self.assertFalse(check(100, 100))

    def test_site_read_error_is_verification_gap(self):
        self.assertIsNone(watchdog.public_lag(snapshot(), now=NOW,
                          fetcher=lambda req, timeout: (_ for _ in ()).throw(OSError("offline"))))

    def test_invalid_secret_url_rejected_without_request(self):
        for url in ("http://incidents.betterstack.com/api/v1/heartbeat/x",
                    "https://evil.example/api/v1/heartbeat/x",
                    "https://incidents.betterstack.com/api/v1/heartbeat/x/fail",
                    "https://incidents.betterstack.com/api/v1/heartbeat/x?a=b"):
            with self.assertRaises(ValueError):
                watchdog.validate_heartbeat_url(url)

    def test_secret_is_not_logged_if_delivery_fails(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), patch("sys.stderr", err):
            success = watchdog.send_heartbeat(SECRET, fail=True,
                sender=lambda req, timeout: (_ for _ in ()).throw(OSError("network")))
        self.assertFalse(success)
        self.assertNotIn("synthetic-test-token", err.getvalue())


if __name__ == "__main__":
    unittest.main()
