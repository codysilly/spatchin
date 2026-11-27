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
            "notam": {"id": "N-1", "text": "RWY 18L\r\nEXACT", "classification": "DOMESTIC", "type": "N"},
            "representations": [{"type": ["LOCAL_FORMAT"], "simpleText": ["LINE 1\r\nLINE 2"]}, {"type": "ICAO", "formattedText": "ICAO TEXT"}],
            "classifications": ["DOMESTIC"], "airport_associations": ["KMEM", "KORD"],
            "original_feature": {"private": True}, "received_utc": "private",
        }
        return {"baseline_established": True, "watermark": "2026-11-27T12:00:00Z", "catalog": {"N-1": {"current": current}}}

    def test_projection_has_all_airports_exact_text_and_no_private_fields(self):
        snapshot, manifest, body = build_candidate(self.candidate(), self.registry(), generated_utc="2026-11-27T12:01:00Z")
        self.assertEqual(len(snapshot["airports"]), 130)
        self.assertEqual(snapshot["airports"]["KMEM"]["notices"][0]["formatted_texts"][0]["text"], "LINE 1\r\nLINE 2")
        self.assertEqual(len(snapshot["airports"]["KORD"]["notices"]), 1)
        self.assertEqual(snapshot["airports"]["KATL"]["completeness"], "UNKNOWN")
        self.assertNotIn("original_feature", body.decode())
        self.assertEqual(manifest["bytes"], len(body))

    def test_atomic_publication_rejects_old_and_retains_on_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            target, state = Path(directory)/"notams.json", Path(directory)/"state.json"
            _, manifest, body = build_candidate(self.candidate(), self.registry(), generated_utc="2026-11-27T12:01:00Z")
            publish_atomic(body, manifest, target, state)
            retained = target.read_bytes()
            old = copy.deepcopy(manifest); old["retrieved_utc"] = "2026-11-27T11:00:00Z"
            with self.assertRaisesRegex(PublicationError, "OLDER"):
                publish_atomic(body, old, target, state)
            with self.assertRaises(RuntimeError):
                publish_atomic(body, manifest, target, state, before_replace=lambda: (_ for _ in ()).throw(RuntimeError("stop")))
            self.assertEqual(target.read_bytes(), retained)


if __name__ == "__main__": unittest.main()
