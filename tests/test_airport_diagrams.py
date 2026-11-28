"""Synthetic fixtures only; no FAA requests."""
import unittest
from datetime import datetime, timezone
from scripts.index_airport_diagrams import build_manifest, edition_state

STATIONS = {"MEM": "KMEM", "ORD": "KORD", "LAX": "KLAX"}


def chart(name="00253AD.PDF", action="", code="APD"):
    return (f"<record><chart_code>{code}</chart_code>"
            f"<useraction>{action}</useraction><pdf_name>{name}</pdf_name></record>")


def airport(icao, records, faa="MEM"):
    return f'<airport_name icao_ident="{icao}" apt_ident="{faa}">{records}</airport_name>'


def catalog(body):
    return (f'<digital_tpp cycle="2612" from_edate="0901Z 11/26/26" '
            f'to_edate="0901Z 12/24/26"><state_code><city_name>{body}'
            '</city_name></state_code></digital_tpp>').encode()


class DiagramIndexTests(unittest.TestCase):
    def build(self, body):
        return build_manifest(catalog(body), STATIONS, "2612")

    def test_scope_and_exact_icao(self):
        result = self.build(airport("KMEM", chart(action="C"))
                            + airport("KORD", chart(code="IAP"))
                            + airport("KXXX", chart(), faa="LAX"))
        self.assertEqual(result["indexed_count"], 1)
        self.assertEqual(result["airport_count"], 3)
        self.assertEqual(result["airports"]["MEM"]["records"][0]["source_url"],
                         "https://aeronav.faa.gov/d-tpp/2612/00253AD.PDF")
        self.assertEqual(result["airports"]["ORD"]["status"], "no_apd_in_index")
        self.assertEqual(result["airports"]["LAX"]["status"], "airport_not_in_index")
        self.assertEqual(result["state"], "candidate_unvalidated")

    def test_deleted_and_ambiguous(self):
        result = self.build(airport("KMEM", chart(action="D"))
                            + airport("KORD", chart() + chart("OTHER.PDF", "A")))
        self.assertIsNone(result["airports"]["MEM"]["records"][0]["source_url"])
        self.assertEqual(result["airports"]["MEM"]["status"], "deleted")
        self.assertEqual(result["airports"]["ORD"]["status"], "ambiguous")
        self.assertEqual(result["indexed_count"], 0)

    def test_bad_filename(self):
        with self.assertRaises(ValueError):
            self.build(airport("KMEM", chart("../bad.PDF")))

    def test_bad_action(self):
        with self.assertRaises(ValueError):
            self.build(airport("KMEM", chart(action="X")))

    def test_wrong_cycle(self):
        with self.assertRaises(ValueError):
            build_manifest(catalog(airport("KMEM", chart())), STATIONS, "2611")

    def test_empty(self):
        with self.assertRaises(ValueError):
            self.build("")

    def test_dtd(self):
        with self.assertRaises(ValueError):
            build_manifest(b'<!DOCTYPE digital_tpp>' + catalog(airport("KMEM", chart())),
                           STATIONS, "2612")

    def test_effective_boundary(self):
        result = self.build(airport("KMEM", chart()))
        def at(day, minute):
            return datetime(2026, 11, day, 9, minute, tzinfo=timezone.utc)
        self.assertEqual(edition_state(result, at(26, 0)), "future")
        self.assertEqual(edition_state(result, at(26, 1)), "effective")
        self.assertEqual(edition_state(result, datetime(2026, 12, 24, 9, 1,
                                                       tzinfo=timezone.utc)), "expired")


if __name__ == "__main__":
    unittest.main()
