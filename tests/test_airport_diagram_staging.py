"""Offline staging tests with synthetic XML and injected PDF responses."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from scripts.fetch_airport_diagrams import stage, validate_pdf
from test_airport_diagrams import airport, catalog, chart, STATIONS

PDF = b"%PDF-1.7\nsynthetic test bytes\n%%EOF\n"


class DiagramStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dest = Path(self.temp.name) / "2612"
        self.xml = catalog(airport("KMEM", chart()) +
                           airport("KORD", chart("ORD.PDF")))

    def run_stage(self, fetch, budget=2):
        return stage(self.xml, STATIONS, "2612", self.dest,
                     max_requests=budget, fetch=fetch)

    def test_staging_and_missing(self):
        fetch = Mock(return_value=PDF)
        result = self.run_stage(fetch)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result["downloaded_count"], 2)
        self.assertEqual(result["state"], "staged_unvalidated")
        self.assertEqual(result["airports"]["LAX"]["status"], "airport_not_in_index")
        self.assertEqual((self.dest / "catalog.xml").read_bytes(), self.xml)
        self.assertEqual((self.dest / "MEM.pdf").read_bytes(), PDF)
        self.assertEqual(json.loads((self.dest / "candidate.json").read_text()), result)

    def test_budget_preflight(self):
        fetch = Mock(return_value=PDF)
        with self.assertRaises(ValueError):
            self.run_stage(fetch, budget=1)
        fetch.assert_not_called()
        self.assertFalse(self.dest.exists())

    def test_failure_reservation_and_no_retry(self):
        fetch = Mock(side_effect=OSError("network unavailable"))
        with self.assertRaises(OSError):
            self.run_stage(fetch)
        fetch.assert_called_once()
        self.assertEqual(len((self.dest / "attempts.jsonl").read_text().splitlines()), 1)
        self.assertFalse((self.dest / "candidate.json").exists())
        with self.assertRaises(FileExistsError):
            self.run_stage(fetch)
        fetch.assert_called_once()

    def test_html_rejected(self):
        with self.assertRaises(ValueError):
            validate_pdf(b"<html>Not a PDF</html>")

    def test_incomplete_pdf_rejected(self):
        with self.assertRaises(ValueError):
            validate_pdf(b"%PDF-1.7\ntruncated")


if __name__ == "__main__":
    unittest.main()
