import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "notam"))
from nms_publication import PublicationError, build_candidate, publish_atomic


class PublicationTests(unittest.TestCase):
    def registry(self):
        return json.loads((ROOT / "docs/reference/c070-airport-registry.json").read_text())

    def candidate(self):
        current = {
            "notam": {
                "id": "N-1",
                "text": "RWY 18L\r\nEXACT",
                "classification": "DOMESTIC",
                "type": "N",
            },
            "representations": [
                {"type": ["LOCAL_FORMAT"], "simpleText": ["LINE 1\r\nLINE 2"]},
                {"type": "ICAO", "formattedText": "ICAO TEXT"},
            ],
            "classifications": ["DOMESTIC"],
            "airport_associations": ["KMEM", "KORD"],
            "original_feature": {"private": True},
            "received_utc": "private",
        }
        return {
            "baseline_established": True,
            "watermark": "2026-11-27T12:00:00Z",
            "capture_started_utc": "2026-11-27T11:58:00Z",
            "catalog": {"N-1": {"current": current}},
        }

    def test_projection_has_all_airports_exact_text_and_no_private_fields(self):
        snapshot, manifest, body = build_candidate(
            self.candidate(), self.registry(), generated_utc="2026-11-27T12:01:00Z"
        )
        self.assertEqual(len(snapshot["airports"]), 130)
        self.assertEqual(
            snapshot["airports"]["KMEM"]["notices"][0]["formatted_texts"][0]["text"],
            "LINE 1\r\nLINE 2",
        )
        self.assertEqual(len(snapshot["airports"]["KORD"]["notices"]), 1)
        self.assertEqual(snapshot["airports"]["KATL"]["completeness"], "UNKNOWN")
        self.assertEqual(snapshot["retrieved_utc"], "2026-11-27T11:58:00Z")
        self.assertEqual(snapshot["publication"]["generated_utc"], "2026-11-27T12:01:00Z")
        self.assertFalse(snapshot["publication"]["automatic_updates"])
        self.assertEqual(snapshot["publication"]["source"], "NMS-API snapshot")
        self.assertEqual(snapshot["publication"]["coverage"], "UNKNOWN")
        self.assertEqual(snapshot["publication"]["freshness_policy"], "NOT_ESTABLISHED")
        self.assertNotIn("original_feature", body.decode())
        self.assertEqual(manifest["bytes"], len(body))

    def test_projection_unwraps_initial_load_singletons_and_rejects_ambiguity(self):
        candidate = self.candidate()
        current = candidate["catalog"]["N-1"]["current"]
        current["format"] = "AIXM_5_1_INITIAL_LOAD"
        current["notam"] = {
            "number": ["11/222"],
            "text": ["RWY 18L\r\nEXACT"],
            "type": ["N"],
        }
        snapshot, _manifest, _body = build_candidate(
            candidate, self.registry(), generated_utc="2026-11-27T12:01:00Z"
        )
        notice = snapshot["airports"]["KMEM"]["notices"][0]
        self.assertEqual(notice["number"], "11/222")
        self.assertEqual(notice["text"], "RWY 18L\r\nEXACT")
        self.assertEqual(notice["provider_lifecycle"], {"type": "N"})

        current["notam"]["text"].append("CONFLICTING VALUE")
        with self.assertRaisesRegex(PublicationError, "AMBIGUOUS_DISPLAY_FIELD"):
            build_candidate(candidate, self.registry(), generated_utc="2026-11-27T12:01:00Z")

    def test_atomic_publication_rejects_old_and_retains_on_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            target, state = Path(directory) / "notams.json", Path(directory) / "state.json"
            _, manifest, body = build_candidate(
                self.candidate(), self.registry(), generated_utc="2026-11-27T12:01:00Z"
            )
            publish_atomic(body, manifest, target, state)
            retained = target.read_bytes()
            old = copy.deepcopy(manifest)
            old["retrieved_utc"] = "2026-11-27T11:00:00Z"
            with self.assertRaisesRegex(PublicationError, "OLDER"):
                publish_atomic(body, old, target, state)
            with self.assertRaises(RuntimeError):
                publish_atomic(
                    body,
                    manifest,
                    target,
                    state,
                    before_replace=lambda: (_ for _ in ()).throw(RuntimeError("stop")),
                )
            self.assertEqual(target.read_bytes(), retained)

    def test_interruption_between_snapshot_and_manifest_is_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            target, state = Path(directory) / "notams.json", Path(directory) / "state.json"
            candidate = self.candidate()
            _, first_manifest, first_body = build_candidate(
                candidate, self.registry(), generated_utc="2026-11-27T12:01:00Z"
            )
            publish_atomic(first_body, first_manifest, target, state)
            candidate["delta_candidate"] = {"received_utc": "2026-11-27T12:02:00Z"}
            _, next_manifest, next_body = build_candidate(
                candidate, self.registry(), generated_utc="2026-11-27T12:03:00Z"
            )
            with self.assertRaises(RuntimeError):
                publish_atomic(
                    next_body,
                    next_manifest,
                    target,
                    state,
                    after_snapshot_replace=lambda: (_ for _ in ()).throw(RuntimeError("stop")),
                )
            self.assertEqual(target.read_bytes(), next_body)
            self.assertEqual(json.loads(state.read_text()), first_manifest)
            publish_atomic(next_body, next_manifest, target, state)
            self.assertEqual(json.loads(state.read_text()), next_manifest)

    def test_retrieval_evidence_is_required(self):
        candidate = self.candidate()
        del candidate["capture_started_utc"]
        with self.assertRaisesRegex(PublicationError, "RETRIEVAL_EVIDENCE_REQUIRED"):
            build_candidate(candidate, self.registry(), generated_utc="2026-11-27T12:01:00Z")


if __name__ == "__main__":
    unittest.main()
