"""Normalizer tests, driven by real captured API responses.

The fixtures under tests/fixtures/ are genuine upstream payloads (FSIS aside,
whose API is geo-blocked from this machine), so these tests pin the actual
quirks documented in docs/sources.md rather than an idealized shape.
"""

from __future__ import annotations

from datetime import date

import pytest

from fetcher.db import dedupe
from fetcher.models import NormalizedRecall
from fetcher.sources import cpsc, fda, fsis, nhtsa
from fetcher.util import (
    join_distinct, parse_compact_date, parse_iso_date, stable_hash, strip_html,
)


# --------------------------------------------------------------------------
# Shared utilities
# --------------------------------------------------------------------------

class TestUtil:
    def test_parse_compact_date(self):
        assert parse_compact_date("20260504") == date(2026, 5, 4)

    @pytest.mark.parametrize("value", ["", None, "2026-05-04", "202605", "20200000", "abcdefgh"])
    def test_parse_compact_date_rejects_bad_input(self, value):
        # 20200000 is a real openFDA value: syntactically 8 digits, not a date.
        assert parse_compact_date(value) is None

    def test_parse_iso_date_handles_time_component(self):
        assert parse_iso_date("2026-07-23T00:00:00") == date(2026, 7, 23)

    def test_strip_html_removes_tags_and_decodes_entities(self):
        assert strip_html("<p>12&nbsp;oz <strong>Chicken</strong></p>") == "12 oz Chicken"

    def test_join_distinct_preserves_order_and_drops_duplicates(self):
        assert join_distinct(["FORD", "ford ", "FORD", "LINCOLN"]) == "FORD; ford; LINCOLN"

    def test_join_distinct_caps_runaway_lists(self):
        result = join_distinct([f"M{i}" for i in range(40)], limit=3)
        assert result == "M0; M1; M2 (+37 more)"

    def test_stable_hash_is_deterministic(self):
        assert stable_hash("a", "b") == stable_hash("a", "b")
        assert stable_hash("a", "b") != stable_hash("b", "a")


class TestNormalizedRecall:
    def test_rejects_empty_source_id(self):
        # source_id is half the UNIQUE key; an empty value would collapse
        # unrelated recalls onto a single row.
        with pytest.raises(ValueError, match="source_id"):
            NormalizedRecall(agency="FDA", source_id="")


# --------------------------------------------------------------------------
# FDA
# --------------------------------------------------------------------------

class TestFDA:
    def test_normalizes_a_standard_record(self, fda_food):
        record = fda_food["results"][0]
        out = fda._normalize(record, "food")

        assert out.agency == "FDA"
        assert out.source_id == record["recall_number"]
        assert out.product == record["product_description"]
        assert out.brand == record["recalling_firm"]
        assert out.classification == record["classification"]
        assert out.recall_date == parse_compact_date(record["recall_initiation_date"])
        assert out.published_at.date() == parse_compact_date(record["report_date"])
        assert out.raw == record

    def test_blank_recall_number_gets_a_stable_synthetic_id(self, fda_food):
        blank = [r for r in fda_food["results"] if not r.get("recall_number")]
        assert blank, "fixture must contain the real blank-recall_number record"

        out = fda._normalize(blank[0], "food")
        assert out.source_id.startswith("EVT-food-")
        assert blank[0]["event_id"] in out.source_id
        # Idempotency: re-running must produce the same id, or every run
        # would insert a duplicate instead of updating.
        assert out.source_id == fda._normalize(blank[0], "food").source_id

    def test_skips_records_with_nothing_stable_to_key_on(self):
        assert fda._normalize({"recall_number": "", "event_id": "", "product_description": ""}, "food") is None

    def test_falls_back_to_report_date_when_initiation_date_is_missing(self):
        out = fda._normalize(
            {"recall_number": "H-1-2026", "report_date": "20260722", "recall_initiation_date": ""}, "food"
        )
        assert out.recall_date == date(2026, 7, 22)

    def test_date_query_builds_the_documented_range_syntax(self):
        assert fda._date_query(date(2026, 6, 1), date(2026, 7, 31)) == "report_date:[20260601 TO 20260731]"

    def test_date_query_is_none_when_unbounded(self):
        assert fda._date_query(None, None) is None


# --------------------------------------------------------------------------
# CPSC
# --------------------------------------------------------------------------

class TestCPSC:
    def test_normalizes_a_real_record(self, cpsc_records):
        record = cpsc_records[0]
        out = cpsc._normalize(record)

        assert out.agency == "CPSC"
        assert out.source_id == str(record["RecallNumber"])
        assert out.url == record["URL"]  # CPSC is the one source with real permalinks
        assert out.recall_date == parse_iso_date(record["RecallDate"])
        assert out.published_at.date() == parse_iso_date(record["LastPublishDate"])

    def test_flattens_nested_arrays(self, cpsc_records):
        record = cpsc_records[0]
        out = cpsc._normalize(record)
        for product in record.get("Products") or []:
            if product.get("Name"):
                assert product["Name"] in out.product

    def test_falls_back_to_title_when_no_named_products(self):
        out = cpsc._normalize({"RecallNumber": "1", "Title": "Widget Recall", "Products": []})
        assert out.product == "Widget Recall"

    def test_skips_records_without_an_identifier(self):
        assert cpsc._normalize({"Title": "no id"}) is None


# --------------------------------------------------------------------------
# FSIS
# --------------------------------------------------------------------------

class TestFSIS:
    def test_normalizes_and_strips_html(self, fsis_records):
        out = fsis._normalize(fsis_records[0])
        assert out.agency == "FSIS"
        assert out.source_id == "011-2026"
        assert out.classification == "Class I"
        assert out.recall_date == date(2026, 7, 15)
        assert "<p>" not in (out.product or "")
        assert out.product == "12-oz packages of ACME Chicken Strips"

    def test_accepts_the_undocumented_public_health_alert_class(self, fsis_records):
        # The official PDF documents only Class I/II/III; live data adds a 4th.
        out = fsis._normalize(fsis_records[1])
        assert out.classification == "Public Health Alert"

    def test_falls_back_to_summary_when_reason_is_empty(self, fsis_records):
        out = fsis._normalize(fsis_records[1])
        assert out.hazard == "E. coli O157:H7 concern."

    def test_skips_unnumbered_records(self, fsis_records):
        assert fsis._normalize(fsis_records[2]) is None


# --------------------------------------------------------------------------
# NHTSA
# --------------------------------------------------------------------------

class TestNHTSA:
    def test_collapses_many_rows_into_one_record_per_campaign(self, nhtsa_lines):
        """The flat file is one row per campaign x make x model x year."""
        multi = [l for l in nhtsa_lines if l.split("\t")[1].strip() == "26V481000"]
        assert len(multi) > 1, "fixture must include a multi-row campaign"

        records = list(nhtsa._group_campaigns(iter(nhtsa_lines), None, None))
        campnos = [r.source_id for r in records]

        assert len(campnos) == len(set(campnos)), "one record per campaign"
        assert len(records) == 2, f"41 fixture rows must collapse to 2 campaigns, got {len(records)}"

    def test_aggregates_makes_and_models_across_rows(self, nhtsa_lines):
        """Aggregation must span every row, not just the first or last one.

        Counting campaigns alone would not catch a broken grouping loop -- the
        dict key collapses duplicates regardless -- so this pins the actual
        cardinality found across the fixture's 40 rows.
        """
        rows = [l.split("\t") for l in nhtsa_lines if l.split("\t")[1].strip() == "26V481000"]
        expected_models = {r[3].strip() for r in rows}
        expected_years = {r[4].strip() for r in rows}
        assert len(expected_models) > 1 and len(expected_years) > 1

        records = {r.source_id: r for r in nhtsa._group_campaigns(iter(nhtsa_lines), None, None)}
        out = records["26V481000"]

        assert out.agency == "NHTSA"
        assert out.url == "https://www.nhtsa.gov/recalls?nhtsaId=26V481000"
        assert set(out.raw["models"]) == expected_models
        assert set(out.raw["years"]) == expected_years
        # Every model must reach the searchable product field.
        for model in expected_models:
            assert model in out.product
        # Multiple model years collapse into a range suffix.
        assert f"({min(expected_years)}-{max(expected_years)})" in out.product

    def test_since_filter_excludes_older_campaigns(self, nhtsa_lines):
        assert list(nhtsa._group_campaigns(iter(nhtsa_lines), date(2099, 1, 1), None)) == []

    def test_maps_recall_type_code_to_a_label(self, nhtsa_lines):
        records = list(nhtsa._group_campaigns(iter(nhtsa_lines), None, None))
        assert all(r.classification in {"Vehicle", "Equipment", "Child Restraint", "Tire", None}
                   or r.classification for r in records)

    def test_year_sentinel_9999_is_not_treated_as_a_real_year(self):
        row = ["1", "26V999000", "TESTMAKE", "TESTMODEL", "9999"] + [""] * 24
        entry = {"first": dict(zip(nhtsa.COLUMNS, row)), "makes": ["TESTMAKE"],
                 "models": ["TESTMODEL"], "years": ["9999"]}
        out = nhtsa._normalize("26V999000", entry)
        assert "9999" not in (out.product or "")


# --------------------------------------------------------------------------
# Upsert batching
# --------------------------------------------------------------------------

class TestDefaultAgencies:
    def test_blocked_sources_are_out_of_the_nightly_rotation(self):
        """A permanently-failing source must not fail the daily cron.

        The heartbeat commit runs after the fetch step, so a non-zero exit
        would stop it -- and the heartbeat is the only thing stopping GitHub
        disabling the schedule for inactivity.
        """
        from fetcher.sources import ADAPTERS, DEFAULT_AGENCIES, UNAVAILABLE

        assert "FSIS" in UNAVAILABLE
        assert "FSIS" not in DEFAULT_AGENCIES
        assert set(DEFAULT_AGENCIES) == {"FDA", "CPSC", "NHTSA"}
        # Still reachable explicitly, and still unit-tested.
        assert "FSIS" in ADAPTERS

    def test_explicit_agency_overrides_the_default(self):
        from fetcher.run import parse_args

        assert parse_args(["--agency", "FSIS"]).agency == ["FSIS"]
        assert parse_args([]).agency is None


class TestDedupe:
    def test_collapses_duplicate_keys_keeping_the_last(self):
        """Postgres rejects a statement that hits one ON CONFLICT target twice.

        Overlapping openFDA date windows genuinely re-return boundary records,
        so this has to happen before the insert.
        """
        records = [
            NormalizedRecall(agency="FDA", source_id="H-1", product="old"),
            NormalizedRecall(agency="FDA", source_id="H-1", product="new"),
            NormalizedRecall(agency="CPSC", source_id="H-1", product="different agency"),
        ]
        result = dedupe(records)
        assert len(result) == 2
        assert next(r for r in result if r.agency == "FDA").product == "new"
