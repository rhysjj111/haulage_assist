"""Selected fuel checks are exact, bounded and read-only."""

from datetime import date, timedelta
import json
import re
from unittest.mock import patch

from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from owner_test_support import OwnerTestCase, db
from haulage_app.models import Day, Fuel, Job
from haulage_app.fuel import import_checks


PREVIEW = "/fuel/import"
CHECK = "/fuel/import/check"
CHECKER = "haulage_app.fuel.import_checks.check_fuel_for_preview"


def selected(source_row=8, **changes):
    row = dict(source_row=source_row, truck_id=1, date="2026-10-05",
               quantity="143.27", cost="186.25")
    row.update(changes)
    return row


class FuelImportChecksTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.add_truck()

    def csrf_token(self):
        _, context = self.get_page(PREVIEW)
        return context["csrf_token"]

    def check(self, rows=None, *, token=None):
        if token is None:
            token = self.csrf_token()
        return self.client.post(CHECK, json={"rows": [selected()] if rows is None else rows},
                                headers={"X-CSRFToken": token})

    def checked(self, rows=None, *, token=None):
        response = self.check(rows, token=token)
        self.assertEqual(response.status_code, 200, response.text)
        self.assert_private(response)
        return response.get_json()

    def assert_private(self, response):
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")

    def snapshot(self):
        with db.session.no_autoflush:
            return {
                name: [tuple(row) for row in db.session.execute(
                    select(table).order_by(*table.primary_key.columns))]
                for name, table in db.metadata.tables.items()
            }

    def test_review_exposes_separate_check_and_save_endpoints_without_writing_on_get(self):
        response, context = self.get_page(PREVIEW)
        self.assertEqual(context["check_url"], CHECK)
        self.assertIn('data-check-url="' + CHECK + '"', response.text)
        self.assertEqual(context["save_url"], "/fuel/import/save")
        self.assertEqual(Fuel.query.count(), 0)
        self.assert_private(response)

    def test_no_day_entry_is_required_and_empty_receipt_context_is_explicit(self):
        self.assertEqual(Day.query.count(), 0)
        payload = self.checked()
        self.assertEqual(payload, {
            "fuel_card_name": "The Fuel Store",
            "rows": [{**selected(), "issues": []}],
            "duplicate_groups": [],
            "existing_fuel": [{"truck_id": 1, "date": "2026-10-05", "entries": []}],
        })

    def test_empty_selection_returns_no_checks_or_source_records(self):
        self.add_fuel()
        with patch.object(db.session, "query", side_effect=AssertionError("empty selection queried history")):
            payload = self.checked([], token=self.csrf_token())
        self.assertEqual(payload, {"fuel_card_name": "The Fuel Store", "rows": [],
                                   "duplicate_groups": [], "existing_fuel": []})

    def test_stored_receipt_exact_amounts_and_provider_are_returned_with_local_review_link(self):
        self.add_fuel(id=3, fuel_card_name="  THE   FUEL store  ",
                      fuel_volume=14327, fuel_cost=18625)
        payload = self.checked()
        self.assertEqual(payload["rows"][0]["issues"], ["possible_duplicate_fuel"])
        self.assertEqual(payload["existing_fuel"][0]["entries"], [{
            "id": 3, "fuel_card_name": "  THE   FUEL store  ",
            "quantity": "143.27", "cost": "186.25", "same_supplier": True,
            "review_url": "/fuel/add_fuel/3/edit",
        }])

    def test_network_names_and_other_suppliers_are_context_not_matching_fuel_store_receipts(self):
        labels = ("ESSO", "UK Fuels", "Shell CRT", "The Fuel Card Company", "TheFuelStore")
        for record_id, label in enumerate(labels, start=1):
            self.add_fuel(id=record_id, fuel_card_name=label, fuel_volume=14327, fuel_cost=18625)
        payload = self.checked()
        self.assertEqual(payload["rows"][0]["issues"], [])
        entries = payload["existing_fuel"][0]["entries"]
        self.assertEqual([entry["fuel_card_name"] for entry in entries], list(labels))
        self.assertTrue(all(entry["same_supplier"] is False for entry in entries))

    def test_shared_unicode_provider_normalization_is_authoritative_for_matching(self):
        self.add_fuel(fuel_card_name="The Fuel ſtore", fuel_volume=14327, fuel_cost=18625)
        payload = self.checked()
        self.assertEqual(payload["rows"][0]["issues"], ["possible_duplicate_fuel"])
        self.assertIs(payload["existing_fuel"][0]["entries"][0]["same_supplier"], True)

    def test_multiple_partial_fills_on_same_truck_and_date_are_not_automatically_duplicates(self):
        self.add_fuel(fuel_card_name="The Fuel Store", fuel_volume=5000, fuel_cost=6500)
        self.add_fuel(fuel_card_name="The Fuel Store", fuel_volume=10000, fuel_cost=13001)
        payload = self.checked([selected(), selected(9, quantity="50.00", cost="65.01")])
        self.assertEqual(payload["duplicate_groups"], [])
        self.assertTrue(all(row["issues"] == [] for row in payload["rows"]))
        self.assertEqual(len(payload["existing_fuel"]), 1)
        self.assertEqual(len(payload["existing_fuel"][0]["entries"]), 2)

    def test_duplicate_upload_uses_exact_truck_date_litres_and_cost(self):
        self.add_truck(2)
        rows = [selected(8), selected(9), selected(10, quantity="143.28"),
                selected(11, cost="186.26"), selected(12, date="2026-10-06"),
                selected(13, truck_id=2)]
        payload = self.checked(rows)
        self.assertEqual(payload["duplicate_groups"], [{"source_rows": [8, 9]}])
        self.assertEqual([row["source_row"] for row in payload["rows"]
                          if "possible_duplicate_upload" in row["issues"]], [8, 9])
        self.assertEqual(len(payload["existing_fuel"]), 3)

    def test_duplicate_groups_and_recorded_candidates_can_coexist_without_excluding_rows(self):
        self.add_fuel(id=1, fuel_card_name="The Fuel Store", fuel_volume=14327, fuel_cost=18625)
        self.add_fuel(id=2, fuel_card_name="the fuel store", fuel_volume=14327, fuel_cost=18625)
        payload = self.checked([selected(9), selected(8)])
        self.assertEqual(payload["duplicate_groups"], [{"source_rows": [8, 9]}])
        self.assertEqual(len(payload["rows"]), 2)
        for row in payload["rows"]:
            self.assertCountEqual(row["issues"], ["possible_duplicate_upload", "possible_duplicate_fuel"])
        self.assertEqual([entry["id"] for entry in payload["existing_fuel"][0]["entries"]], [1, 2])

    def test_excluding_or_editing_a_candidate_removes_obsolete_duplicate_warnings(self):
        initial = self.checked([selected(8), selected(9)])
        self.assertEqual(len(initial["duplicate_groups"]), 1)
        excluded = self.checked([selected(8)])
        edited = self.checked([selected(8), selected(9, cost="186.26")])
        for result in (excluded, edited):
            self.assertEqual(result["duplicate_groups"], [])
            self.assertTrue(all("possible_duplicate_upload" not in row["issues"] for row in result["rows"]))

    def test_price_band_has_exact_inclusive_boundaries_without_division_rounding(self):
        values = (("100.00", "50.00", False), ("100.00", "300.00", False),
                  ("100.00", "49.99", True), ("100.00", "300.01", True),
                  ("100.01", "50.00", True), ("100.01", "50.01", False),
                  ("100.01", "300.03", False), ("100.01", "300.04", True))
        payload = self.checked([selected(index, quantity=quantity, cost=cost)
                                for index, (quantity, cost, _) in enumerate(values, start=1)])
        for row, (_, _, expected) in zip(payload["rows"], values):
            self.assertEqual("fuel_price_unusual" in row["issues"], expected, row)
            self.assertNotIn("fuel_amount_out_of_range", row["issues"])

    def test_existing_entry_form_amount_limits_are_strict_and_nonpositive_values_are_retained(self):
        values = (("1", "1", True), ("1.01", "1.01", False),
                  ("1000", "1300", True), ("999.99", "1499.99", False),
                  ("100", "1500", True), ("0", "0", True),
                  ("-5.25", "-6.83", True), ("999999999999.99", "2", True))
        payload = self.checked([selected(index, quantity=quantity, cost=cost)
                                for index, (quantity, cost, _) in enumerate(values, start=1)])
        for row, (_, _, expected) in zip(payload["rows"], values):
            self.assertEqual("fuel_amount_out_of_range" in row["issues"], expected, row)
            if expected:
                self.assertNotIn("fuel_price_unusual", row["issues"])
        self.assertEqual(payload["rows"][6]["quantity"], "-5.25")
        self.assertEqual(payload["rows"][6]["cost"], "-6.83")

    def test_decimal_strings_normalize_exactly_and_can_match_recorded_pence(self):
        self.add_fuel(fuel_card_name="The Fuel Store", fuel_volume=1010, fuel_cost=1275)
        payload = self.checked([selected(quantity="00010.1", cost="12.75")])
        row = payload["rows"][0]
        self.assertEqual((row["quantity"], row["cost"]), ("10.10", "12.75"))
        self.assertEqual(row["issues"], ["possible_duplicate_fuel"])

    def test_unavailable_truck_is_an_explicit_row_issue_without_unrelated_receipts(self):
        self.add_fuel()
        payload = self.checked([selected(8, truck_id=999), selected(9, truck_id=999)])
        self.assertEqual(payload["existing_fuel"], [])
        self.assertEqual(payload["duplicate_groups"], [])
        self.assertTrue(all(row["issues"] == ["truck_unavailable"] for row in payload["rows"]))

    def test_purchase_dates_are_independent_and_cross_years_without_payroll_week_inference(self):
        dates = (date(2026, 12, 31), date(2027, 1, 1), date(1, 1, 1), date(9999, 12, 31))
        for record_id, on_date in enumerate(dates, start=1):
            self.add_fuel(id=record_id, on_date=on_date, fuel_card_name="The Fuel Store",
                          fuel_volume=14327, fuel_cost=18625)
        payload = self.checked([selected(index, date=value.isoformat())
                                for index, value in enumerate(dates, start=1)])
        self.assertEqual({row["date"] for row in payload["rows"]}, {value.isoformat() for value in dates})
        self.assertTrue(all(row["issues"] == ["possible_duplicate_fuel"] for row in payload["rows"]))
        self.assertEqual(len(payload["existing_fuel"]), 4)

    def test_lookup_matches_exact_selected_pairs_without_broad_history_or_cross_product(self):
        self.add_truck(2)
        self.add_fuel(id=1, truck_id=1, on_date=date(2026, 10, 5))
        self.add_fuel(id=2, truck_id=2, on_date=date(2026, 10, 6))
        # These are in the same date range/truck set, but not selected pairs.
        self.add_fuel(id=3, truck_id=1, on_date=date(2026, 10, 6))
        self.add_fuel(id=4, truck_id=2, on_date=date(2026, 10, 5))
        with patch.object(import_checks, "MAX_EXISTING_ENTRIES", 2):
            payload = self.checked([selected(8), selected(9, truck_id=2, date="2026-10-06")])
        self.assertEqual([entry["id"] for group in payload["existing_fuel"] for entry in group["entries"]], [1, 2])

    def test_lookup_pairs_use_bounded_queries_and_no_day_table(self):
        captured = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            if re.search(r"\bFROM\s+fuel\b", statement, re.IGNORECASE):
                captured.append((statement, parameters))
            self.assertFalse(re.search(r"\bFROM\s+day\b", statement, re.IGNORECASE), statement)

        token = self.csrf_token()
        rows = [selected(index + 1, date=(date(2026, 1, 1) + timedelta(days=index)).isoformat())
                for index in range(501)]
        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            payload = self.checked(rows, token=token)
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)
        self.assertEqual(len(payload["existing_fuel"]), 501)
        self.assertEqual(len(captured), 3)
        self.assertTrue(all(len(parameters) <= 502 for _, parameters in captured))

    def test_too_many_recorded_matches_returns_a_fixed_error_without_partial_checks(self):
        for record_id in range(1, 4):
            self.add_fuel(id=record_id, fuel_card_name="private-provider-value")
        token = self.csrf_token()
        with patch.object(import_checks, "MAX_EXISTING_ENTRIES", 2):
            response = self.check(token=token)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.get_json()["error"]["code"], "checks_too_large")
        self.assertNotIn("rows", response.get_json())
        self.assertNotIn("private-provider-value", response.text)
        self.assert_private(response)

    def test_recorded_entry_cap_applies_across_all_lookup_chunks(self):
        dates = (date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7))
        for record_id, on_date in enumerate(dates, start=1):
            self.add_fuel(id=record_id, on_date=on_date)
        token = self.csrf_token()
        with patch.object(import_checks, "LOOKUP_PAIR_CHUNK", 1), \
                patch.object(import_checks, "MAX_EXISTING_ENTRIES", 2):
            response = self.check([selected(index, date=on_date.isoformat())
                                   for index, on_date in enumerate(dates, start=1)], token=token)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.get_json()["error"]["code"], "checks_too_large")
        self.assertNotIn("existing_fuel", response.get_json())

    def test_large_identical_selection_returns_group_membership_once_not_quadratic_references(self):
        token = self.csrf_token()
        rows = [selected(index + 1) for index in range(10_000)]
        payload = self.checked(rows, token=token)
        self.assertEqual(len(payload["rows"]), 10_000)
        self.assertEqual(payload["duplicate_groups"], [{"source_rows": list(range(1, 10_001))}])
        self.assertEqual(len(payload["existing_fuel"]), 1)
        self.assertLess(len(json.dumps(payload)), 3_000_000)
        self.assertTrue(all(row["issues"] == ["possible_duplicate_upload"] for row in payload["rows"]))

    def test_rechecks_use_current_recorded_values_and_preserve_legacy_signed_amounts(self):
        self.add_fuel(id=1, fuel_card_name="The Fuel Store", fuel_volume=14327, fuel_cost=18625)
        self.add_fuel(id=2, fuel_card_name="Legacy correction", fuel_volume=-525, fuel_cost=-683)
        before = self.checked()
        self.assertIn("possible_duplicate_fuel", before["rows"][0]["issues"])
        db.session.execute(Fuel.__table__.update().where(Fuel.id == 1).values(fuel_cost=18626))
        db.session.commit()
        after = self.checked()
        self.assertEqual(after["rows"][0]["issues"], [])
        correction = after["existing_fuel"][0]["entries"][1]
        self.assertEqual((correction["quantity"], correction["cost"]), ("-5.25", "-6.83"))

    def test_malformed_or_incomplete_payload_is_rejected_without_echoing_input(self):
        token = self.csrf_token()
        for value in (None, [], 1, True, "private-source-value", {}, {"rows": None},
                      {"rows": {}}, {"rows": [None]}, {"rows": [selected()], "notes": "private-source-value"},
                      {"rows": [selected(), selected()]}, {"rows": [selected()] * 10_001}):
            with self.subTest(payload_type=type(value).__name__):
                response = self.client.post(CHECK, data=json.dumps(value), content_type="application/json",
                                            headers={"X-CSRFToken": token})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertNotIn("rows", response.get_json())
                self.assertNotIn("private-source-value", response.text)
                self.assert_private(response)
        for content in (b'{"rows":private-source-value}', b"\xff", b"null", b'"private-source-value"',
                        b"[" * 1100 + b"]" * 1100):
            response = self.client.post(CHECK, data=content, content_type="application/json",
                                        headers={"X-CSRFToken": token})
            self.assertEqual(response.status_code, 400, response.text)
            self.assertNotIn("private-source-value", response.text)

    def test_row_keys_ids_dates_and_decimal_types_are_strict(self):
        token = self.csrf_token()
        invalid = []
        for field in selected():
            missing = selected()
            missing.pop(field)
            invalid.append(missing)
        invalid.append(selected(notes="private-source-value"))
        for key in ("source_row", "truck_id"):
            for value in (None, True, False, "1", 1.0, 0, -1, 2 ** 100):
                invalid.append(selected(**{key: value}))
        invalid.append(selected(source_row=10051))
        for value in ("2026-02-30", "20261005", "05/10/2026", "2026-10-05T00:00:00",
                      "0000-01-01", "10000-01-01", None, True, 123):
            invalid.append(selected(date=value))
        for key in ("quantity", "cost"):
            for value in (None, True, 100, 100.0, [], {}, "", "1.001", "1e2", "NaN", "Infinity",
                          "+10", "1,000.00", " 10.00", "10.00 ", ".5", "1.",
                          "1000000000000", "9" * 33, "private-source-value"):
                invalid.append(selected(**{key: value}))
        for row in invalid:
            with self.subTest(row_fields=list(row)):
                response = self.check([row], token=token)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "invalid_check")
                self.assertNotIn("rows", response.get_json())
                self.assertNotIn("private-source-value", response.text)

    def test_invalid_row_does_not_return_an_all_clear_for_other_valid_rows(self):
        response = self.check([selected(8), selected(9, cost="private-source-value")])
        self.assertEqual(response.status_code, 400, response.text)
        self.assertNotIn("rows", response.get_json())

    def test_missing_or_bad_csrf_is_rejected_before_checks(self):
        self.csrf_token()
        with patch(CHECKER) as checker:
            for headers in ({}, {"X-CSRFToken": "invalid-token"}):
                response = self.client.post(CHECK, data=b"private-source-value", content_type="application/json",
                                            headers=headers)
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "csrf_failed")
                self.assert_private(response)
            checker.assert_not_called()

    def test_non_json_and_oversize_bodies_are_rejected_before_checks(self):
        token = self.csrf_token()
        with patch(CHECKER) as checker:
            for content_type in ("text/plain", "application/pdf", "multipart/form-data"):
                response = self.client.post(CHECK, data=b"private-source-value", content_type=content_type,
                                            headers={"X-CSRFToken": token})
                self.assertEqual(response.status_code, 415, response.text)
                self.assert_private(response)
            large = b" " * (import_checks.MAX_CHECK_BYTES + 1)
            for overrides in ({}, {"CONTENT_LENGTH": "", "wsgi.input_terminated": True}):
                response = self.client.post(CHECK, data=large, content_type="application/json",
                                            headers={"X-CSRFToken": token}, environ_overrides=overrides)
                self.assertEqual(response.status_code, 413, response.text)
                self.assert_private(response)
            checker.assert_not_called()

    def test_database_and_unexpected_failures_are_sanitized_without_partial_checks(self):
        token = self.csrf_token()
        for error in (SQLAlchemyError("private SQL source-value 143.27"),
                      RuntimeError("private parser source-value 143.27")):
            with self.subTest(error_type=type(error).__name__), patch(CHECKER, side_effect=error):
                response = self.check(token=token)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "checks_unavailable")
                self.assertNotIn("rows", response.get_json())
                self.assertNotIn("source-value", response.text)
                self.assertNotIn("143.27", response.text)
                self.assert_private(response)

    def test_checks_do_not_write_business_data_archive_documents_or_store_drafts(self):
        self.add_driver()
        self.add_job(self.add_day())
        self.add_payslip()
        self.add_fuel(fuel_card_name="The Fuel Store", fuel_volume=14327, fuel_cost=18625)
        token = self.csrf_token()
        before = self.snapshot()
        with patch.object(db.session, "add", side_effect=AssertionError("unexpected add")), \
                patch.object(db.session, "add_all", side_effect=AssertionError("unexpected add_all")), \
                patch.object(db.session, "delete", side_effect=AssertionError("unexpected delete")), \
                patch.object(db.session, "flush", side_effect=AssertionError("unexpected flush")), \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")), \
                patch("tempfile.TemporaryFile", side_effect=AssertionError("unexpected file")), \
                patch("tempfile.NamedTemporaryFile", side_effect=AssertionError("unexpected file")):
            for _ in range(2):
                self.checked(token=token)
        self.assertEqual(self.snapshot(), before)
        with self.client.session_transaction() as session:
            saved = json.dumps(dict(session))
        for value in ("143.27", "186.25", "The Fuel Store", "2026-10-05"):
            self.assertNotIn(value, saved)

    def test_pending_dirty_fuel_and_other_edits_are_not_flushed_or_used_as_stored_values(self):
        self.add_driver()
        self.add_job(self.add_day())
        self.add_fuel(id=1, fuel_card_name="The Fuel Store", fuel_volume=14327, fuel_cost=18625)
        token = self.csrf_token()
        fuel = db.session.get(Fuel, 1)
        job = db.session.get(Job, 1)
        fuel.fuel_card_name = "Pending source edit"
        fuel.fuel_cost = "200.00"
        job.notes = "Pending unrelated edit"
        with patch.object(db.session, "flush", side_effect=AssertionError("unexpected flush")):
            payload = self.checked(token=token)
        self.assertEqual(payload["rows"][0]["issues"], ["possible_duplicate_fuel"])
        stored = payload["existing_fuel"][0]["entries"][0]
        self.assertEqual((stored["fuel_card_name"], stored["cost"]), ("The Fuel Store", "186.25"))
        self.assertIn(fuel, db.session.dirty)
        self.assertIn(job, db.session.dirty)
        with db.session.no_autoflush:
            self.assertEqual(db.session.execute(select(Job.__table__.c.notes)).scalar_one(), "")
