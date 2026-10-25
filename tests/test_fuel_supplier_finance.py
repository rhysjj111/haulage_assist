"""Fuel review/save rules use the selected supplier without mixing providers."""

from copy import deepcopy
from datetime import date
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.dml import Insert

from owner_test_support import OwnerTestCase, db
from haulage_app.fuel.import_checks import check_fuel_for_preview
from haulage_app.fuel.import_profiles import FuelDocumentError, get_supplier, supplier_choices
from haulage_app.fuel.import_save import ImportSaveError, save_reviewed_fuel
from haulage_app.models import Fuel
from haulage_app.verification.models import Anomaly, MissingEntryAnomaly, TableName, UserFeedback


def proposal(source_row=1, **changes):
    row = dict(source_row=source_row, truck_id=1, date="2026-10-05",
               quantity="143.27", cost="186.25", product="DERV",
               source_issues=[], review_confirmed=False)
    row.update(changes)
    return row


def check_rows(rows):
    fields = ("source_row", "truck_id", "date", "quantity", "cost")
    return {"rows": [{field: row[field] for field in fields} for row in rows]}


class FuelSupplierFinanceTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.add_truck()

    def checked(self, rows=None, supplier_id="silvey"):
        with self.app.test_request_context():
            return check_fuel_for_preview(check_rows(rows or [proposal()]), supplier_id)

    def saved(self, rows=None, supplier_id="silvey"):
        with self.app.test_request_context():
            return save_reviewed_fuel({"rows": deepcopy(rows or [proposal()])}, supplier_id)

    def fuel_snapshot(self):
        with db.session.no_autoflush:
            return [dict(row) for row in db.session.execute(
                select(Fuel.__table__).order_by(Fuel.id)).mappings()]

    def test_profiles_offer_supplier_specific_products_and_no_adblue(self):
        profiles = {profile["id"]: profile for profile in supplier_choices()}
        self.assertEqual(set(profiles), {"the-fuel-store", "silvey"})
        self.assertEqual(get_supplier().label, "The Fuel Store")
        self.assertEqual(profiles["silvey"]["formats"], ["pdf"])
        self.assertEqual(profiles["silvey"]["source_formats"], ["silvey-fuel-invoice-pdf-v1"])
        self.assertIn("DERV", profiles["silvey"]["diesel_products"])
        self.assertNotIn("DERV", profiles["the-fuel-store"]["diesel_products"])
        self.assertTrue(all("ADBLUE" not in profile["diesel_products"] for profile in profiles.values()))

    def test_silvey_check_returns_its_label_and_does_not_require_a_day(self):
        checked = self.checked()
        self.assertEqual(checked["fuel_card_name"], "Silvey")
        self.assertEqual(checked["rows"][0]["issues"], [])
        self.assertEqual(checked["existing_fuel"], [
            {"truck_id": 1, "date": "2026-10-05", "entries": []},
        ])

    def test_same_details_from_another_supplier_are_context_not_a_duplicate(self):
        first = self.add_fuel(fuel_card_name="The Fuel Store", fuel_volume=14327, fuel_cost=18625)
        checked = self.checked()
        self.assertEqual(checked["rows"][0]["issues"], [])
        self.assertEqual(checked["existing_fuel"][0]["entries"][0]["id"], first)
        self.assertFalse(checked["existing_fuel"][0]["entries"][0]["same_supplier"])

    def test_silvey_whitespace_case_normalizes_for_duplicate_comparison(self):
        self.add_fuel(fuel_card_name="  SILVEY  ", fuel_volume=14327, fuel_cost=18625)
        checked = self.checked()
        self.assertEqual(checked["rows"][0]["issues"], ["possible_duplicate_fuel"])
        self.assertTrue(checked["existing_fuel"][0]["entries"][0]["same_supplier"])

    def test_network_labels_do_not_become_silvey_supplier_aliases(self):
        for index, provider in enumerate(("UK Fuels", "Esso", "Shell CRT"), start=1):
            self.add_fuel(id=index, fuel_card_name=provider, fuel_volume=14327, fuel_cost=18625)
        checked = self.checked()
        self.assertEqual(checked["rows"][0]["issues"], [])
        self.assertTrue(all(not row["same_supplier"]
                            for row in checked["existing_fuel"][0]["entries"]))

    def test_duplicate_upload_groups_are_still_detected_for_silvey(self):
        checked = self.checked([proposal(1), proposal(2)])
        self.assertEqual(checked["duplicate_groups"], [{"source_rows": [1, 2]}])
        self.assertTrue(all(row["issues"] == ["possible_duplicate_upload"] for row in checked["rows"]))

    def test_save_uses_exact_amounts_and_selected_supplier_label(self):
        result = self.saved()
        self.assertEqual(result["saved_count"], 1)
        stored = self.fuel_snapshot()[0]
        self.assertEqual((stored["date"], stored["day_id"], stored["fuel_card_name"],
                          stored["fuel_volume"], stored["fuel_cost"]),
                         (date(2026, 10, 5), None, "Silvey", 14327, 18625))

    def test_save_preserves_other_supplier_and_a_silvey_retry_is_blocked(self):
        other = self.add_fuel(fuel_card_name="The Fuel Store", fuel_volume=14327, fuel_cost=18625)
        before = self.fuel_snapshot()[0]
        result = self.saved()
        self.assertEqual(result["saved_count"], 1)
        with self.assertRaises(ImportSaveError) as raised:
            self.saved([proposal(review_confirmed=True)])
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.row_errors[0]["code"], "possible_duplicate_fuel")
        stored = self.fuel_snapshot()
        self.assertEqual(len(stored), 2)
        self.assertEqual(next(row for row in stored if row["id"] == other), before)
        self.assertEqual({row["fuel_card_name"] for row in stored}, {"The Fuel Store", "Silvey"})

    def test_fuel_store_default_is_preserved_after_a_silvey_save(self):
        self.saved()
        row = proposal(product="KEYFUELS DIESEL")
        checked = self.checked([row], None)
        self.assertEqual(checked["fuel_card_name"], "The Fuel Store")
        self.assertEqual(checked["rows"][0]["issues"], [])
        self.assertFalse(checked["existing_fuel"][0]["entries"][0]["same_supplier"])
        self.saved([row], None)
        self.assertEqual([entry["fuel_card_name"] for entry in self.fuel_snapshot()],
                         ["Silvey", "The Fuel Store"])

    def test_derv_is_not_accepted_under_the_other_supplier_profile(self):
        with self.assertRaises(ImportSaveError) as raised:
            self.saved(supplier_id="the-fuel-store")
        self.assertEqual(raised.exception.status, 422)
        self.assertEqual(raised.exception.row_errors[0]["code"], "unsupported_product")
        self.assertEqual(self.fuel_snapshot(), [])

    def test_adblue_cannot_be_saved_even_after_confirmation(self):
        for changes in (
            dict(product="AdBlue", source_issues=["unsupported_product"]),
            dict(product="ADBLUE", source_issues=[]),
            dict(product="DERV", source_issues=["unsupported_product"]),
        ):
            with self.subTest(changes=changes), self.assertRaises(ImportSaveError) as raised:
                self.saved([proposal(review_confirmed=True, **changes)])
            self.assertEqual(raised.exception.status, 422)
            self.assertTrue(any(error["code"] == "unsupported_product"
                                for error in raised.exception.row_errors))
        self.assertEqual(self.fuel_snapshot(), [])

    def test_unusual_price_and_source_warnings_require_current_confirmation(self):
        row = proposal(quantity="100.00", cost="10.00")
        with self.assertRaises(ImportSaveError) as raised:
            self.saved([row])
        self.assertEqual(raised.exception.status, 422)
        self.assertEqual(raised.exception.row_errors[0]["field"], "review")
        self.assertEqual(self.fuel_snapshot(), [])
        row["review_confirmed"] = True
        self.saved([row])
        next_row = proposal(2, date="2026-10-06", source_issues=["cost_price_mismatch"])
        with self.assertRaises(ImportSaveError):
            self.saved([next_row])
        self.assertEqual(len(self.fuel_snapshot()), 1)

    def test_confirmation_cannot_bypass_invalid_amounts_or_batch_duplicates(self):
        for rows in ([proposal(cost="1500.00", review_confirmed=True)],
                     [proposal(1, review_confirmed=True), proposal(2, review_confirmed=True)]):
            with self.subTest(count=len(rows)), self.assertRaises(ImportSaveError):
                self.saved(rows)
        self.assertEqual(self.fuel_snapshot(), [])

    def test_supplier_validation_happens_before_database_access(self):
        with patch.object(db.session, "query", side_effect=AssertionError("unexpected lookup")), \
                patch.object(db.session, "execute", side_effect=AssertionError("unexpected SQL")), \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")):
            for supplier in ("", "unknown-provider", "SILVEY"):
                with self.subTest(supplier=supplier):
                    with self.assertRaises(FuelDocumentError):
                        self.checked(supplier_id=supplier)
                    with self.assertRaises(FuelDocumentError):
                        self.saved(supplier_id=supplier)

    def test_silvey_anomaly_and_feedback_cleanup_is_atomic_with_receipt(self):
        missing = MissingEntryAnomaly(date=date(2026, 10, 5), truck_id=1,
                                      table_name=TableName.FUEL, description="Fictional receipt")
        db.session.add(missing)
        db.session.flush()
        anomaly_id = missing.id
        db.session.add(UserFeedback(anomaly_id=anomaly_id, user_comment="Fictional review"))
        db.session.commit()
        self.saved()
        self.assertEqual(Anomaly.query.count(), 0)
        self.assertEqual(MissingEntryAnomaly.query.count(), 0)
        self.assertEqual(UserFeedback.query.count(), 0)
        self.assertEqual(self.fuel_snapshot()[0]["fuel_card_name"], "Silvey")

    def test_later_insert_failure_rolls_back_entire_silvey_batch(self):
        real_execute = db.session.execute
        inserts = 0

        def execute(statement, *args, **kwargs):
            nonlocal inserts
            if isinstance(statement, Insert) and statement.table.name == "fuel":
                inserts += 1
                if inserts == 2:
                    raise IntegrityError("fictional failing insert", {}, Exception("fictional constraint"))
            return real_execute(statement, *args, **kwargs)

        with patch.object(db.session, "execute", side_effect=execute):
            with self.assertRaises(IntegrityError):
                self.saved([proposal(1), proposal(2, date="2026-10-06")])
        self.assertEqual(inserts, 2)
        self.assertEqual(self.fuel_snapshot(), [])
