"""A Silvey PDF reaches the shared review and supplier-bound atomic saver."""

from datetime import date
from decimal import Decimal
from io import BytesIO
import json
from unittest.mock import patch

from pypdf import PdfWriter
from sqlalchemy import select

from owner_test_support import OwnerTestCase, db
from fuel_xlsx_fixtures import transactions_xlsx
from payroll_pdf_fixtures import report_pdf
from silvey_pdf_fixtures import invoice_pdf
from haulage_app.models import Fuel


PREVIEW = "/fuel/import"
READ = "/fuel/import/read"
CHECK = "/fuel/import/check"
SAVE = "/fuel/import/save"
PDF_WORKER = "haulage_app.fuel.silvey_processing.read_silvey_pdf_isolated"
REGISTRATIONS = ("ZZ26 ABC", "ZX26 DEF", "ZY26 GHI")


class SilveyImportTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["WTF_CSRF_ENABLED"] = True
        for identity, registration in enumerate(REGISTRATIONS, start=1):
            self.add_truck(identity, registration=registration)

    def token(self):
        return self.get_page(PREVIEW)[1]["csrf_token"]

    def headers(self, *, supplier="silvey", token=None):
        return {"X-CSRFToken": token or self.token(), "X-Fuel-Supplier": supplier}

    def read(self, content=None, *, supplier="silvey", mimetype="application/octet-stream", token=None):
        return self.client.post(READ, data=invoice_pdf() if content is None else content,
                                content_type=mimetype, headers=self.headers(supplier=supplier, token=token))

    def preview(self):
        response = self.read()
        self.assertEqual(response.status_code, 200, response.text)
        self.assert_private(response)
        return response.get_json()

    def selection(self, payload, *, diesel_only=True):
        return [{key: row[key] for key in ("source_row", "truck_id", "quantity", "cost")}
                | {"date": row["transaction_date"]}
                for row in payload["rows"]
                if not diesel_only or row["product"].upper() == "DERV"]

    def reviewed(self, payload, *, diesel_only=True):
        return [{"source_row": row["source_row"], "truck_id": row["truck_id"],
                 "date": row["transaction_date"], "quantity": row["quantity"], "cost": row["cost"],
                 "product": row["product"], "source_issues": list(row["issues"]),
                 "review_confirmed": False}
                for row in payload["rows"]
                if not diesel_only or row["product"].upper() == "DERV"]

    def post_rows(self, endpoint, rows, *, supplier="silvey", token=None):
        return self.client.post(endpoint, json={"rows": rows},
                                headers=self.headers(supplier=supplier, token=token))

    def assert_private(self, response):
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")

    def snapshot(self):
        with db.session.no_autoflush:
            return {name: [tuple(row) for row in db.session.execute(
                select(table).order_by(*table.primary_key.columns))]
                for name, table in db.metadata.tables.items()}

    def test_real_pdf_returns_reconciled_source_pages_and_exact_net_transaction_prices(self):
        payload = self.preview()
        report = payload["report"]
        self.assertEqual(report["supplier_id"], "silvey")
        self.assertEqual(report["fuel_card_name"], "Silvey")
        self.assertEqual(report["source_format"], "silvey-fuel-invoice-pdf-v1")
        self.assertEqual(report["document_kind"], "pdf")
        self.assertEqual(report["page_count"], 2)
        self.assertEqual(report["transaction_count"], 6)
        self.assertEqual(report["totals"], {"quantity": "155.35", "cost": "206.44"})
        self.assertEqual(report["printed_totals"], report["totals"])
        rows = payload["rows"]
        self.assertEqual([row["source_row"] for row in rows], list(range(1, 7)))
        self.assertEqual([row["source_page"] for row in rows], [1, 1, 1, 1, 2, 2])
        self.assertEqual([(row["quantity"], row["cost"]) for row in rows], [
            ("10.00", "12.00"), ("20.25", "24.30"), ("5.00", "10.00"),
            ("30.10", "42.14"), ("40.00", "48.00"), ("50.00", "70.00"),
        ])
        self.assertEqual([row["transaction_registration"] for row in rows],
                         [REGISTRATIONS[0]] * 3 + [REGISTRATIONS[1]] * 2 + [REGISTRATIONS[2]])
        self.assertTrue(all(row["card_registration"] is None for row in rows))
        self.assertEqual([row["truck_id"] for row in rows], [1, 1, 1, 2, 2, 3])
        self.assertTrue(all(row["match_status"] == "matched" for row in rows))
        self.assertTrue(all(row["transaction_time"] is not None for row in rows))
        self.assertEqual(rows[0]["transaction_date"], "2026-10-01")
        self.assertEqual(Decimal(rows[0]["unit_price"]), Decimal("1.2"))
        self.assertEqual(rows[2]["product"].upper(), "ADBLUE")
        self.assertIn("unsupported_product", rows[2]["issues"])
        self.assertTrue(all(not row["issues"] for row in rows if row["product"].upper() == "DERV"))

    def test_real_pdf_read_check_save_keeps_diesel_exact_and_does_not_require_a_day(self):
        before = self.snapshot()
        payload = self.preview()
        check = self.post_rows(CHECK, self.selection(payload))
        self.assertEqual(check.status_code, 200, check.text)
        self.assert_private(check)
        self.assertEqual(check.get_json()["fuel_card_name"], "Silvey")
        self.assertTrue(all(not row["issues"] for row in check.get_json()["rows"]))
        self.assertEqual(self.snapshot(), before)
        save = self.post_rows(SAVE, self.reviewed(payload))
        self.assertEqual(save.status_code, 201, save.text)
        self.assert_private(save)
        self.assertEqual(save.get_json()["saved_count"], 5)
        stored = db.session.execute(select(Fuel.__table__).order_by(Fuel.id)).mappings().all()
        self.assertEqual(len(stored), 5)
        self.assertEqual({row["fuel_card_name"] for row in stored}, {"Silvey"})
        self.assertTrue(all(row["day_id"] is None for row in stored))
        self.assertEqual(sum(row["fuel_volume"] for row in stored), 15035)
        self.assertEqual(sum(row["fuel_cost"] for row in stored), 19644)
        expected = self.reviewed(payload)
        self.assertEqual([(row["date"].isoformat(), row["truck_id"], row["fuel_volume"], row["fuel_cost"])
                          for row in stored],
                         [(row["date"], row["truck_id"], int(Decimal(row["quantity"]) * 100),
                           int(Decimal(row["cost"]) * 100)) for row in expected])

    def test_adblue_stays_visible_and_cannot_be_confirmed_into_diesel_saving(self):
        payload = self.preview()
        rows = self.reviewed(payload, diesel_only=False)
        self.assertEqual(len(rows), 6)
        for row in rows:
            row["review_confirmed"] = True
        before = self.snapshot()
        response = self.post_rows(SAVE, rows)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertTrue(any(error["source_row"] == 3 and error["code"] == "unsupported_product"
                            for error in response.get_json()["row_errors"]))
        self.assertEqual(self.snapshot(), before)

    def test_provider_specific_duplicates_allow_other_supplier_but_reject_silvey_retry(self):
        payload = self.preview()
        first = self.reviewed(payload)[0]
        self.add_fuel(truck_id=first["truck_id"], on_date=date.fromisoformat(first["date"]),
                      fuel_card_name="The Fuel Store", fuel_volume=1000, fuel_cost=1200)
        check = self.post_rows(CHECK, self.selection(payload)[:1])
        self.assertEqual(check.status_code, 200, check.text)
        self.assertEqual(check.get_json()["rows"][0]["issues"], [])
        self.assertFalse(check.get_json()["existing_fuel"][0]["entries"][0]["same_supplier"])
        self.assertEqual(self.post_rows(SAVE, [first]).status_code, 201)
        before = self.snapshot()
        retry = self.post_rows(SAVE, [first])
        self.assertEqual(retry.status_code, 409, retry.text)
        self.assertEqual(retry.get_json()["row_errors"][0]["code"], "possible_duplicate_fuel")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({row[0] for row in db.session.execute(select(Fuel.fuel_card_name))},
                         {"The Fuel Store", "Silvey"})

    def test_bytes_choose_pdf_reader_independently_of_transport_mime(self):
        response = self.read(mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.get_json()["report"]["document_kind"], "pdf")
        self.assertEqual(response.get_json()["report"]["supplier_id"], "silvey")

    def test_wrong_supplier_document_combinations_do_not_create_or_relabel_rows(self):
        before = self.snapshot()
        for supplier, content in (("the-fuel-store", invoice_pdf()), ("silvey", transactions_xlsx())):
            with self.subTest(supplier=supplier):
                response = self.read(content, supplier=supplier)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "format_unavailable")
                self.assertNotIn("rows", response.get_json())
                self.assert_private(response)
        self.assertEqual(self.snapshot(), before)

    def test_unrelated_layout_blank_scan_and_encrypted_pdf_fail_without_partial_source_data(self):
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        stream = BytesIO()
        writer.write(stream)
        cases = ((report_pdf(), "unsupported_layout"), (stream.getvalue(), "no_text"),
                 (invoice_pdf(password="fictional-password"), "encrypted_pdf"))
        before = self.snapshot()
        for content, code in cases:
            with self.subTest(code=code):
                response = self.read(content)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.get_json()["error"]["code"], code)
                self.assertNotIn("rows", response.get_json())
                self.assertNotIn("Alice Example", response.text)
                self.assertNotIn("fictional-password", response.text)
                self.assertNotIn("Traceback", response.text)
                self.assert_private(response)
        self.assertEqual(self.snapshot(), before)

    def test_read_and_checks_never_flush_write_or_archive_source_documents(self):
        token = self.token()
        before = self.snapshot()
        with patch.object(db.session, "add", side_effect=AssertionError("unexpected add")), \
                patch.object(db.session, "add_all", side_effect=AssertionError("unexpected add_all")), \
                patch.object(db.session, "flush", side_effect=AssertionError("unexpected flush")), \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")), \
                patch("werkzeug.datastructures.FileStorage.save", side_effect=AssertionError("unexpected archive")):
            response = self.read(token=token)
            self.assertEqual(response.status_code, 200, response.text)
            for value in ("900001", "800001", "9123456", "Fictional Customer",
                          "FICTIONAL NORTH SERVICES", "10101"):
                self.assertNotIn(value, response.text)
            check = self.post_rows(CHECK, self.selection(response.get_json()), token=token)
            self.assertEqual(check.status_code, 200, check.text)
        self.assertEqual(self.snapshot(), before)
        with self.client.session_transaction() as session:
            saved = json.dumps(dict(session))
        for value in (*REGISTRATIONS, "Silvey", "DERV", "206.44", "196.44"):
            self.assertNotIn(value, saved)

    def test_csrf_and_unknown_supplier_fail_before_the_pdf_reader(self):
        token = self.token()
        with patch(PDF_WORKER) as worker:
            response = self.client.post(READ, data=invoice_pdf(), content_type="application/pdf",
                                        headers={"X-Fuel-Supplier": "silvey", "X-CSRFToken": "invalid"})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.get_json()["error"]["code"], "csrf_failed")
            response = self.read(supplier="unknown-supplier", token=token)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["error"]["code"], "supplier_unavailable")
            worker.assert_not_called()

    def test_unexpected_pdf_failure_is_sanitized_and_does_not_change_data(self):
        token = self.token()
        before = self.snapshot()
        with patch(PDF_WORKER, side_effect=RuntimeError("private-source ZZ26 ABC 206.44")):
            response = self.read(token=token)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("rows", response.get_json())
        for value in ("private-source", "ZZ26 ABC", "206.44", "RuntimeError", "Traceback"):
            self.assertNotIn(value, response.text)
        self.assert_private(response)
        self.assertEqual(self.snapshot(), before)
