"""Reviewed fuel imports validate and save one complete batch atomically."""

from copy import deepcopy
from datetime import date, timedelta
import json
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.sql.dml import Insert

from owner_test_support import OwnerTestCase, db
from haulage_app.models import Day, Fuel, Job, Truck
from haulage_app.verification.models import Anomaly, MissingEntryAnomaly, TableName, UserFeedback


PREVIEW = "/fuel/import"
CHECK = "/fuel/import/check"
SAVE = "/fuel/import/save"
MAX_SAVE_BYTES = 524288
FIRST_DATE = date(2026, 10, 5)
SECOND_DATE = date(2027, 1, 1)
_DEFAULT = object()


def proposed(source_row=3, **changes):
    row = dict(source_row=source_row, truck_id=1, date=FIRST_DATE.isoformat(),
               quantity="143.27", cost="186.25", product="KEYFUELS DIESEL",
               source_issues=[], review_confirmed=False)
    row.update(changes)
    return row


class FuelImportSaveTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.add_truck(1)
        self.add_truck(2)

    def payload(self, rows=None):
        return {"rows": deepcopy(rows if rows is not None else [
            proposed(), proposed(9, truck_id=2, date=SECOND_DATE.isoformat(),
                                  quantity="211.08", cost="274.40"),
        ])}

    def csrf_token(self):
        _, context = self.get_page(PREVIEW)
        return context["csrf_token"]

    def save(self, payload=_DEFAULT, *, token=None):
        if token is None:
            token = self.csrf_token()
        return self.client.post(SAVE, data=json.dumps(self.payload() if payload is _DEFAULT else payload),
                                content_type="application/json", headers={"X-CSRFToken": token})

    def stored_fuel(self):
        with db.session.no_autoflush:
            return [dict(row) for row in db.session.execute(
                select(Fuel.__table__).order_by(Fuel.id)).mappings()]

    def snapshot(self):
        with db.session.no_autoflush:
            return {name: [tuple(row) for row in db.session.execute(
                select(table).order_by(*table.primary_key.columns))]
                for name, table in db.metadata.tables.items()}

    def assert_private(self, response):
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")

    def assert_row_error(self, response, source_row, *, field=None, code=None):
        errors = response.get_json().get("row_errors", [])
        self.assertTrue(any(error.get("source_row") == source_row
                            and (field is None or error.get("field") == field)
                            and (code is None or error.get("code") == code)
                            for error in errors), response.text)

    def anomaly(self, *, truck_id=1, on_date=FIRST_DATE, table_name=TableName.FUEL,
                feedback=False):
        entry = MissingEntryAnomaly(
            date=on_date, truck_id=truck_id, table_name=table_name,
            description="Fictional missing receipt", is_read=False, is_recurring=False,
        )
        db.session.add(entry)
        db.session.flush()
        entry_id = entry.id
        if feedback:
            db.session.add(UserFeedback(anomaly_id=entry_id,
                                        user_comment="Fictional receipt review"))
        db.session.commit()
        return entry_id

    def test_page_exposes_an_explicit_separate_save_action_without_saving_on_get(self):
        response, context = self.get_page(PREVIEW)
        self.assertEqual(context["save_url"], SAVE)
        self.assertIn('data-save-url="' + SAVE + '"', response.text)
        self.assertIn("Save fuel", response.text)
        self.assertEqual(self.stored_fuel(), [])
        self.assert_private(response)

    def test_selected_batch_commits_exact_pence_and_litres_once_without_requiring_days(self):
        self.assertEqual(Day.query.count(), 0)
        token = self.csrf_token()
        before = self.snapshot()
        with patch.object(db.session, "commit", wraps=db.session.commit) as commit:
            response = self.save(token=token)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(commit.call_count, 1)
        result = response.get_json()
        self.assertEqual(result["saved_count"], 2)
        entries = self.stored_fuel()
        self.assertEqual([(entry["truck_id"], entry["date"], entry["day_id"],
                           entry["fuel_volume"], entry["fuel_cost"], entry["fuel_card_name"])
                          for entry in entries], [
            (1, FIRST_DATE, None, 14327, 18625, "The Fuel Store"),
            (2, SECOND_DATE, None, 21108, 27440, "The Fuel Store"),
        ])
        self.assertTrue(all(type(entry["fuel_cost"]) is int
                            and type(entry["fuel_volume"]) is int for entry in entries))
        self.assertEqual([entry["source_row"] for entry in result["fuel_entries"]], [3, 9])
        self.assertEqual([entry["id"] for entry in result["fuel_entries"]],
                         [entry["id"] for entry in entries])
        for entry in result["fuel_entries"]:
            self.assertEqual(entry["review_url"], f"/fuel/add_fuel/{entry['id']}/edit")
            stored = next(row for row in entries if row["id"] == entry["id"])
            self.assertEqual((entry["truck_id"], entry["date"]),
                             (stored["truck_id"], stored["date"].isoformat()))
        self.assertEqual(result["history_url"], "/fuel/add_fuel/0/history")
        after = self.snapshot()
        self.assertEqual({key: value for key, value in before.items() if key != "fuel"},
                         {key: value for key, value in after.items() if key != "fuel"})
        self.assert_private(response)

    def test_only_submitted_rows_are_saved_and_existing_other_receipts_are_untouched(self):
        existing = self.add_fuel(truck_id=2, on_date=SECOND_DATE,
                                 fuel_card_name="The Fuel Store", fuel_volume=21108, fuel_cost=27440)
        before = self.stored_fuel()[0]
        response = self.save(self.payload([proposed()]))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.get_json()["saved_count"], 1)
        self.assertEqual(next(row for row in self.stored_fuel() if row["id"] == existing), before)

    def test_only_a_unique_matching_truck_and_purchase_date_day_is_linked(self):
        self.add_driver(1)
        self.add_driver(2)
        unique = self.add_day(driver_id=1, on_date=FIRST_DATE, truck_id=1)
        self.add_day(driver_id=1, on_date=SECOND_DATE, truck_id=2)
        self.add_day(driver_id=2, on_date=SECOND_DATE, truck_id=2)
        self.add_day(driver_id=2, on_date=FIRST_DATE - timedelta(days=1), truck_id=1)
        response = self.save()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual([entry["day_id"] for entry in self.stored_fuel()], [unique, None])

    def test_days_for_other_trucks_or_dates_are_not_silently_linked(self):
        self.add_driver()
        self.add_day(on_date=FIRST_DATE, truck_id=2)
        self.add_day(on_date=FIRST_DATE + timedelta(days=1), truck_id=1)
        response = self.save(self.payload([proposed()]))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIsNone(self.stored_fuel()[0]["day_id"])

    def test_purchase_dates_remain_individual_across_years_without_week_end_inference(self):
        dates = (date(2026, 12, 31), date(2027, 1, 1), date(1, 1, 1), date(9999, 12, 31))
        response = self.save(self.payload([proposed(index, date=value.isoformat())
                                           for index, value in enumerate(dates, start=1)]))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual([entry["date"] for entry in self.stored_fuel()], list(dates))

    def test_exact_duplicates_in_selection_block_the_whole_batch_even_when_confirmed(self):
        payload = self.payload([proposed(review_confirmed=True), proposed(9, review_confirmed=True)])
        response = self.save(payload)
        self.assertEqual(response.status_code, 409, response.text)
        for source_row in (3, 9):
            self.assert_row_error(response, source_row, code="possible_duplicate_upload")
        self.assertEqual(self.stored_fuel(), [])

    def test_existing_exact_normalized_supplier_match_blocks_without_overwriting_any_row(self):
        existing = self.add_fuel(truck_id=2, on_date=SECOND_DATE,
                                 fuel_card_name="  THE   FUEL store  ", fuel_volume=21108, fuel_cost=27440)
        before = self.snapshot()
        payload = self.payload()
        payload["rows"][1]["review_confirmed"] = True
        response = self.save(payload)
        self.assertEqual(response.status_code, 409, response.text)
        self.assert_row_error(response, 9, code="possible_duplicate_fuel")
        match = next(error for error in response.get_json()["row_errors"]
                     if error["source_row"] == 9 and error["code"] == "possible_duplicate_fuel")
        self.assertEqual(match["action_url"], f"/fuel/add_fuel/{existing}/edit")
        self.assertEqual(self.snapshot(), before)

    def test_different_partial_fills_and_other_provider_same_day_receipts_allow_saving(self):
        self.add_fuel(fuel_card_name="The Fuel Store", fuel_volume=5000, fuel_cost=6500)
        self.add_fuel(fuel_card_name="UK Fuels", fuel_volume=14327, fuel_cost=18625)
        payload = self.payload([proposed(), proposed(9, quantity="50.00", cost="65.01")])
        response = self.save(payload)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(len(self.stored_fuel()), 4)

    def test_repeating_a_successful_save_is_a_conflict_and_creates_no_more_receipts(self):
        token = self.csrf_token()
        self.assertEqual(self.save(token=token).status_code, 201)
        before = self.snapshot()
        retry = self.save(token=token)
        self.assertEqual(retry.status_code, 409, retry.text)
        self.assertEqual(self.snapshot(), before)

    def test_save_rechecks_a_receipt_created_after_a_successful_preview_check(self):
        token = self.csrf_token()
        fields = ("source_row", "truck_id", "date", "quantity", "cost")
        check_rows = [{key: row[key] for key in fields} for row in self.payload()["rows"]]
        checked = self.client.post(CHECK, json={"rows": check_rows}, headers={"X-CSRFToken": token})
        self.assertEqual(checked.status_code, 200, checked.text)
        self.assertTrue(all(not row["issues"] for row in checked.get_json()["rows"]))
        self.add_fuel(truck_id=2, on_date=SECOND_DATE, fuel_card_name="The Fuel Store",
                      fuel_volume=21108, fuel_cost=27440)
        before = self.snapshot()
        response = self.save(token=token)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.snapshot(), before)

    def test_missing_or_deleted_truck_blocks_all_rows_without_creating_a_truck(self):
        db.session.execute(Truck.__table__.delete().where(Truck.id == 2))
        db.session.commit()
        before = self.snapshot()
        response = self.save()
        self.assertEqual(response.status_code, 422, response.text)
        self.assert_row_error(response, 9, code="truck_unavailable")
        self.assertEqual(self.snapshot(), before)

    def test_unusual_price_requires_per_row_confirmation_using_current_values(self):
        row = proposed(quantity="100.00", cost="1.01")
        token = self.csrf_token()
        response = self.save(self.payload([row]), token=token)
        self.assertEqual(response.status_code, 422, response.text)
        self.assert_row_error(response, 3, field="review")
        self.assertEqual(self.stored_fuel(), [])
        row["review_confirmed"] = True
        response = self.save(self.payload([row]), token=token)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual((self.stored_fuel()[0]["fuel_volume"], self.stored_fuel()[0]["fuel_cost"]),
                         (10000, 101))

    def test_source_warnings_require_explicit_review_even_after_values_are_corrected(self):
        issues = ("missing_transaction_registration", "registration_mismatch",
                  "non_positive_quantity", "non_positive_cost", "cost_price_mismatch")
        token = self.csrf_token()
        for index, issue in enumerate(issues):
            with self.subTest(issue=issue):
                row = proposed(source_issues=[issue], date=(FIRST_DATE + timedelta(days=index)).isoformat())
                response = self.save(self.payload([row]), token=token)
                self.assertEqual(response.status_code, 422, response.text)
                self.assert_row_error(response, 3, field="review")
                row["review_confirmed"] = True
                response = self.save(self.payload([row]), token=token)
                self.assertEqual(response.status_code, 201, response.text)

    def test_confirmation_is_required_for_each_flagged_entry_not_for_the_batch_once(self):
        first = proposed(source_issues=["cost_price_mismatch"], review_confirmed=True)
        second = proposed(9, truck_id=2, quantity="100.00", cost="400.00")
        token = self.csrf_token()
        response = self.save(self.payload([first, second]), token=token)
        self.assertEqual(response.status_code, 422, response.text)
        self.assert_row_error(response, 9, field="review")
        self.assertFalse(any(error["source_row"] == 3 for error in response.get_json()["row_errors"]))
        self.assertEqual(self.stored_fuel(), [])
        second["review_confirmed"] = True
        response = self.save(self.payload([first, second]), token=token)
        self.assertEqual(response.status_code, 201, response.text)

    def test_unsupported_products_cannot_be_confirmed_into_the_fuel_import(self):
        token = self.csrf_token()
        for product in ("ADBLUE", "CARD FEE", "FICTIONAL CREDIT", "DIESEL EXTRA"):
            with self.subTest(product=product):
                row = proposed(product=product, source_issues=[], review_confirmed=True)
                response = self.save(self.payload([row]), token=token)
                self.assertEqual(response.status_code, 422, response.text)
                self.assert_row_error(response, 3, field="product", code="unsupported_product")
                self.assertEqual(self.stored_fuel(), [])

    def test_original_unsupported_product_flag_cannot_be_overridden_with_a_diesel_label(self):
        row = proposed(product="DIESEL", source_issues=["unsupported_product"], review_confirmed=True)
        response = self.save(self.payload([row]))
        self.assertEqual(response.status_code, 422, response.text)
        self.assert_row_error(response, 3, field="product", code="unsupported_product")
        self.assertEqual(self.stored_fuel(), [])

    def test_known_diesel_product_labels_are_accepted_without_changing_the_supplier(self):
        products = ("KEYFUELS DIESEL", "UK FUELS DIESEL", "UK FUELS DIESEL (TP)",
                    "ESSO DIESEL", "DIESEL (SHELL)", "  diesel  ")
        response = self.save(self.payload([
            proposed(index + 1, date=(FIRST_DATE + timedelta(days=index)).isoformat(), product=product)
            for index, product in enumerate(products)
        ]))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(all(entry["fuel_card_name"] == "The Fuel Store" for entry in self.stored_fuel()))

    def test_out_of_range_amounts_block_the_batch_even_if_review_is_confirmed(self):
        token = self.csrf_token()
        values = (("quantity", "1.00"), ("quantity", "1000.00"), ("quantity", "0"),
                  ("quantity", "-2.00"), ("cost", "1.00"), ("cost", "1500.00"),
                  ("cost", "0"), ("cost", "-5.00"))
        for field, value in values:
            with self.subTest(field=field, value=value):
                payload = self.payload()
                payload["rows"][1].update({field: value, "review_confirmed": True})
                response = self.save(payload, token=token)
                self.assertEqual(response.status_code, 422, response.text)
                self.assert_row_error(response, 9, field=field, code="fuel_amount_out_of_range")
                self.assertEqual(self.stored_fuel(), [])

    def test_amounts_are_not_rounded_or_coerced_from_unsupported_types(self):
        token = self.csrf_token()
        invalid = (None, True, 143.27, 14327, "", "143.271", "1e2", "NaN", "Infinity",
                   "143,27", " 143.27 ", "１２.３４", "9" * 33)
        for field in ("quantity", "cost"):
            for value in invalid:
                with self.subTest(field=field, value=repr(value)[:25]):
                    row = proposed(**{field: value})
                    response = self.save(self.payload([row]), token=token)
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertEqual(self.stored_fuel(), [])
                    self.assert_private(response)

    def test_malformed_shapes_ids_products_and_review_flags_fail_without_echoing_source(self):
        token = self.csrf_token()
        invalid = [None, [], {}, {"rows": None}, {"rows": []},
                   {"rows": [proposed()] * 501},
                   {**self.payload(), "private_source": "fictional private workbook"}]
        for field in ("source_row", "truck_id"):
            for value in (None, True, 1.0, "1", 0, -1, 2 ** 31):
                invalid.append(self.payload([proposed(**{field: value})]))
        invalid.append(self.payload([proposed(source_row=10051)]))
        invalid.append(self.payload([proposed(), proposed()]))
        for field in proposed():
            row = proposed()
            del row[field]
            invalid.append(self.payload([row]))
        for field, values in (("product", (None, True, "", "x" * 201)),
                               ("source_issues", (None, "cost_price_mismatch", [True],
                                                  ["private-source-value"],
                                                  ["cost_price_mismatch"] * 2)),
                               ("review_confirmed", (None, 0, 1, "true"))):
            invalid.extend(self.payload([proposed(**{field: value})]) for value in values)
        invalid.append(self.payload([{**proposed(), "private_source": "fictional private workbook"}]))
        for payload in invalid:
            with self.subTest(shape=repr(payload)[:90]):
                response = self.save(payload, token=token)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertNotIn("fictional private workbook", response.text)
                self.assertNotIn("private-source-value", response.text)
                self.assertEqual(self.stored_fuel(), [])
                self.assert_private(response)

    def test_invalid_purchase_dates_are_not_coerced_to_a_payroll_date(self):
        token = self.csrf_token()
        for value in ("2026-02-30", "20261005", "05/10/2026", "", None, True,
                      "0000-01-01", "10000-01-01", "2026-10-05T12:00:00", "private-date"):
            with self.subTest(date=value):
                response = self.save(self.payload([proposed(date=value)]), token=token)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(self.stored_fuel(), [])

    def test_save_accepts_the_bounded_500_row_batch_and_preserves_every_source_mapping(self):
        rows = [proposed(index + 1, date=(FIRST_DATE + timedelta(days=index)).isoformat())
                for index in range(500)]
        response = self.save(self.payload(rows))
        self.assertEqual(response.status_code, 201, response.text)
        result = response.get_json()
        self.assertEqual(result["saved_count"], 500)
        self.assertEqual([row["source_row"] for row in result["fuel_entries"]], list(range(1, 501)))
        self.assertEqual(len({row["id"] for row in result["fuel_entries"]}), 500)
        self.assertEqual(len(self.stored_fuel()), 500)

    def test_csrf_is_required_before_decoding_or_saving_private_body(self):
        self.csrf_token()
        before = self.snapshot()
        for headers in ({}, {"X-CSRFToken": "not-valid"}):
            response = self.client.post(SAVE, data=b"private malformed body",
                                        content_type="application/json", headers=headers)
            self.assertEqual(response.status_code, 403, response.text)
            self.assertEqual(response.get_json()["error"]["code"], "csrf_failed")
            self.assertNotIn("private malformed", response.text)
            self.assert_private(response)
        self.assertEqual(self.snapshot(), before)

    def test_content_type_size_and_malformed_json_are_rejected_before_saving(self):
        token = self.csrf_token()
        before = self.snapshot()
        for content_type in ("text/plain", "application/pdf", "multipart/form-data"):
            response = self.client.post(SAVE, data=b"private source", content_type=content_type,
                                        headers={"X-CSRFToken": token})
            self.assertEqual(response.status_code, 415, response.text)
            self.assert_private(response)
        for overrides in ({}, {"CONTENT_LENGTH": "", "wsgi.input_terminated": True}):
            response = self.client.post(SAVE, data=b" " * (MAX_SAVE_BYTES + 1),
                                        content_type="application/json", headers={"X-CSRFToken": token},
                                        environ_overrides=overrides)
            self.assertEqual(response.status_code, 413, response.text)
            self.assert_private(response)
        for content in (b'{"private workbook', b"\xff", b"[]", b"null"):
            response = self.client.post(SAVE, data=content, content_type="application/json",
                                        headers={"X-CSRFToken": token})
            self.assertEqual(response.status_code, 400, response.text)
            self.assertNotIn("private workbook", response.text)
            self.assert_private(response)
        self.assertEqual(self.snapshot(), before)

    def test_integrity_failure_on_a_later_insert_rolls_back_the_complete_batch(self):
        token = self.csrf_token()
        before = self.snapshot()
        real_execute = db.session.execute
        insert_count = 0

        def fail_second(statement, *args, **kwargs):
            nonlocal insert_count
            if isinstance(statement, Insert) and statement.table.name == "fuel":
                insert_count += 1
                if insert_count == 2:
                    raise IntegrityError("private insert", {}, Exception("private constraint"))
            return real_execute(statement, *args, **kwargs)

        with patch.object(db.session, "execute", side_effect=fail_second):
            response = self.save(token=token)
        self.assertEqual(insert_count, 2)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotIn("private", response.text)
        self.assertEqual(self.snapshot(), before)
        self.assert_private(response)

    def test_success_removes_all_matching_missing_fuel_anomalies_and_inherited_feedback_only(self):
        resolved = [self.anomaly(feedback=True), self.anomaly(feedback=True),
                    self.anomaly(truck_id=2, on_date=SECOND_DATE, feedback=True)]
        retained = [self.anomaly(on_date=SECOND_DATE, feedback=True),
                    self.anomaly(truck_id=2, on_date=FIRST_DATE),
                    self.anomaly(on_date=FIRST_DATE - timedelta(days=1)),
                    self.anomaly(table_name=TableName.PAYSLIP, feedback=True)]
        response = self.save()
        self.assertEqual(response.status_code, 201, response.text)
        for entry_id in resolved:
            self.assertIsNone(db.session.get(MissingEntryAnomaly, entry_id))
            self.assertIsNone(db.session.get(Anomaly, entry_id))
            self.assertEqual(db.session.query(UserFeedback).filter_by(anomaly_id=entry_id).count(), 0)
        self.assertEqual({row.id for row in MissingEntryAnomaly.query.all()}, set(retained))

    def test_commit_failure_restores_inserted_rows_and_anomaly_parent_child_feedback_deletions(self):
        self.anomaly(feedback=True)
        token = self.csrf_token()
        before = self.snapshot()
        real_flush = db.session.flush

        def fail_after_flush():
            real_flush()
            raise SQLAlchemyError("private receipt storage failure")

        with patch.object(db.session, "commit", side_effect=fail_after_flush):
            response = self.save(token=token)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("private receipt", response.text)
        self.assertEqual(self.snapshot(), before)
        self.assert_private(response)

    def test_lost_commit_acknowledgement_is_uncertain_and_retry_cannot_duplicate_the_saved_batch(self):
        token = self.csrf_token()
        real_commit = db.session.commit

        def commit_then_lose_ack():
            real_commit()
            raise SQLAlchemyError("Synthetic lost commit acknowledgement")

        with patch.object(db.session, "commit", side_effect=commit_then_lose_ack):
            response = self.save(token=token)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("nothing was saved", response.text.lower())
        self.assertNotIn("Synthetic lost", response.text)
        self.assertEqual(len(self.stored_fuel()), 2)
        committed = self.snapshot()
        retry = self.save(token=token)
        self.assertEqual(retry.status_code, 409, retry.text)
        self.assertEqual(self.snapshot(), committed)
        self.assert_private(response)

    def test_save_does_not_commit_flush_or_discard_unrelated_pending_work(self):
        self.add_driver()
        self.add_job(self.add_day())
        token = self.csrf_token()
        for state in ("dirty", "new", "deleted"):
            with self.subTest(state=state):
                job = db.session.get(Job, 1)
                if state == "dirty":
                    job.notes = "Pending unrelated edit"
                elif state == "new":
                    job = Job(day_id=1, earned="10.00", collection="Depot", delivery="Port")
                    db.session.add(job)
                else:
                    db.session.delete(job)
                with patch.object(db.session, "flush", side_effect=AssertionError("unexpected flush")), \
                        patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")), \
                        patch.object(db.session, "rollback", side_effect=AssertionError("unexpected rollback")):
                    response = self.save(token=token)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "save_unavailable")
                self.assertIn(job, getattr(db.session, state))
                self.assertEqual(self.stored_fuel(), [])
                db.session.rollback()

    def test_unexpected_save_failure_is_sanitized_and_has_an_unconfirmed_outcome(self):
        with patch("haulage_app.fuel.import_save.save_reviewed_fuel",
                   side_effect=RuntimeError("private row source amount")):
            response = self.save()
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("private row", response.text)
        self.assertNotIn("nothing was saved", response.text.lower())
        self.assert_private(response)

    def test_save_does_not_archive_documents_or_store_values_in_cookies_or_links(self):
        with patch("werkzeug.datastructures.FileStorage.save", side_effect=AssertionError("archive")), \
                patch("tempfile.TemporaryFile", side_effect=AssertionError("temporary file")), \
                patch("tempfile.NamedTemporaryFile", side_effect=AssertionError("temporary file")):
            response = self.save()
        self.assertEqual(response.status_code, 201, response.text)
        with self.client.session_transaction() as session:
            session_text = json.dumps(dict(session))
        for value in ("143.27", "186.25", "211.08", "274.40", "KEYFUELS", "2026-10-05"):
            self.assertNotIn(value, session_text)
        for entry in response.get_json()["fuel_entries"]:
            self.assertNotIn("?", entry["review_url"])
            self.assertNotIn("143.27", entry["review_url"])
