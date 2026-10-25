"""One fuel upload flow chooses supported readers from the selected supplier."""

from dataclasses import replace
from html.parser import HTMLParser
from unittest.mock import patch

from sqlalchemy import select

from owner_test_support import OwnerTestCase, db
from fuel_xlsx_fixtures import transactions_xlsx
from haulage_app.fuel.xlsx_reader import read_fuel_store_transactions_xlsx
from haulage_app.models import Fuel


PREVIEW = "/fuel/import"
READ = "/fuel/import/read"
CHECK = "/fuel/import/check"
SAVE = "/fuel/import/save"
SUPPLIER = "the-fuel-store"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
WORKER = "haulage_app.fuel.xlsx_processing.read_fuel_store_xlsx_isolated"
CHECKER = "haulage_app.fuel.import_checks.check_fuel_for_preview"
SAVER = "haulage_app.fuel.import_save.save_reviewed_fuel"


class _UploadControls(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = []
        self.selects = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input":
            self.inputs.append(attributes)
        elif tag == "select":
            self.selects.append(attributes)


def selected():
    return {"source_row": 8, "truck_id": 1, "date": "2027-02-09",
            "quantity": "143.27", "cost": "186.25"}


def reviewed():
    return {**selected(), "product": "KEYFUELS DIESEL", "source_issues": [],
            "review_confirmed": False}


class FuelSupplierUploadTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.add_truck(registration="ZZ26 ABC")

    def token(self):
        _, context = self.get_page(PREVIEW)
        return context["csrf_token"]

    def headers(self, *, supplier=SUPPLIER, token=None):
        return {"X-CSRFToken": self.token() if token is None else token,
                "X-Fuel-Supplier": supplier}

    def assert_private(self, response):
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")

    def snapshot(self):
        with db.session.no_autoflush:
            return {name: [tuple(row) for row in db.session.execute(
                select(table).order_by(*table.primary_key.columns))]
                for name, table in db.metadata.tables.items()}

    def test_page_exposes_available_supplier_and_one_picker_without_format_selector(self):
        response, context = self.get_page(PREVIEW)
        controls = _UploadControls(response.text)
        files = [field for field in controls.inputs if field.get("type") == "file"]
        self.assertEqual(len(files), 1)
        self.assertIn(".xlsx", files[0].get("accept", ""))
        self.assertIn(".pdf", files[0].get("accept", ""))
        self.assertEqual([field.get("id") for field in controls.selects],
                         ["fuel-import-supplier"])
        self.assertEqual(context["default_supplier_id"], "auto")
        profiles = context["supplier_profiles"]
        self.assertEqual({profile["id"] for profile in profiles}, {"the-fuel-store", "silvey"})
        self.assertEqual(profiles[0]["id"], SUPPLIER)
        self.assertEqual(profiles[0]["label"], "The Fuel Store")
        self.assertEqual(list(profiles[0]["formats"]), ["xlsx"])
        self.assertEqual(list(profiles[0]["source_formats"]),
                         ["fuel-store-transactions-xlsx-v1"])
        self.assertTrue(profiles[0]["help_text"])
        silvey = next(profile for profile in profiles if profile["id"] == "silvey")
        self.assertEqual(silvey["label"], "Silvey")
        self.assertEqual(list(silvey["formats"]), ["pdf"])
        self.assertIn("DERV", silvey["diesel_products"])
        self.assertEqual(context["read_url"], READ)
        self.assert_private(response)

    def test_unified_binary_upload_runs_the_existing_isolated_xlsx_reader(self):
        response = self.client.post(READ, data=transactions_xlsx(),
                                    content_type="application/octet-stream", headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.get_json()["report"]["supplier_id"], SUPPLIER)
        self.assertEqual(response.get_json()["report"]["fuel_card_name"], "The Fuel Store")
        self.assertEqual(response.get_json()["report"]["source_format"],
                         "fuel-store-transactions-xlsx-v1")
        self.assertEqual(response.get_json()["report"]["transaction_count"], 2)
        self.assert_private(response)

    def test_actual_bytes_select_the_reader_even_when_mime_claims_pdf(self):
        response = self.client.post(READ, data=transactions_xlsx(),
                                    content_type="application/pdf", headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.get_json()["report"]["supplier_id"], SUPPLIER)
        self.assertEqual(response.get_json()["report"]["source_format"],
                         "fuel-store-transactions-xlsx-v1")
        self.assert_private(response)

    def test_pdf_is_a_supported_upload_type_but_not_an_available_fuel_store_layout(self):
        token = self.token()
        with patch(WORKER) as worker:
            for mimetype in ("application/octet-stream", "application/pdf", XLSX_MIME):
                with self.subTest(mimetype=mimetype):
                    response = self.client.post(
                        READ, data=b"%PDF-1.7\nprivate-card-value 143.27 186.25",
                        content_type=mimetype, headers=self.headers(token=token),
                    )
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertEqual(response.get_json()["error"]["code"], "format_unavailable")
                    self.assertNotIn("rows", response.get_json())
                    for value in ("private-card-value", "143.27", "186.25", "Traceback"):
                        self.assertNotIn(value, response.text)
                    self.assert_private(response)
            worker.assert_not_called()

    def test_unknown_bytes_fail_without_running_a_workbook_or_pdf_parser(self):
        token = self.token()
        with patch(WORKER) as worker:
            for content in (b"", b"private-worksheet-value", b"\x89PNG\r\nprivate-photo-value"):
                with self.subTest(content_type=content[:8]):
                    response = self.client.post(READ, data=content,
                                                content_type="application/octet-stream",
                                                headers=self.headers(token=token))
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertEqual(response.get_json()["error"]["code"], "invalid_document")
                    self.assertNotIn("private-", response.text)
                    self.assertNotIn("rows", response.get_json())
                    self.assert_private(response)
            worker.assert_not_called()

    def test_reader_report_must_match_selected_supplier_and_registered_layout(self):
        content = transactions_xlsx()
        report = read_fuel_store_transactions_xlsx(content)
        token = self.token()
        for altered in (replace(report, fuel_card_name="Fictional other supplier"),
                        replace(report, source_format="private-unregistered-layout")):
            with self.subTest(label=altered.fuel_card_name), \
                    patch(WORKER, return_value=altered), \
                    patch.object(db.session, "query", side_effect=AssertionError("unexpected lookup")):
                response = self.client.post(READ, data=content,
                                            content_type="application/octet-stream",
                                            headers=self.headers(token=token))
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "invalid_document")
                self.assertNotIn("rows", response.get_json())
                self.assertNotIn("Fictional other supplier", response.text)
                self.assertNotIn("private-unregistered-layout", response.text)
                self.assert_private(response)

    def test_unknown_or_blank_supplier_is_rejected_before_read_check_or_save_helpers(self):
        token = self.token()
        before = self.snapshot()
        with patch(WORKER) as worker, patch(CHECKER) as checker, patch(SAVER) as saver, \
                patch.object(db.session, "query", side_effect=AssertionError("unexpected lookup")), \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")):
            for supplier in ("", " ", "unknown-supplier", "THE-FUEL-STORE", "private-supplier-value", "../supplier"):
                for endpoint, content, mimetype in (
                    (READ, transactions_xlsx(), "application/octet-stream"),
                    (CHECK, '{"rows":[]}', "application/json"),
                    (SAVE, '{"rows":[]}', "application/json"),
                ):
                    with self.subTest(supplier=supplier, endpoint=endpoint):
                        response = self.client.post(endpoint, data=content, content_type=mimetype,
                                                    headers=self.headers(supplier=supplier, token=token))
                        self.assertEqual(response.status_code, 400, response.text)
                        self.assertEqual(response.get_json()["error"]["code"], "supplier_unavailable")
                        self.assertNotIn("private-supplier-value", response.text)
                        self.assertNotIn("rows", response.get_json())
                        self.assert_private(response)
            worker.assert_not_called()
            checker.assert_not_called()
            saver.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_explicit_supplier_checks_and_saves_the_same_confirmed_provider(self):
        token = self.token()
        check = self.client.post(CHECK, json={"rows": [selected()]},
                                 headers=self.headers(token=token))
        self.assertEqual(check.status_code, 200, check.text)
        self.assertEqual(check.get_json()["fuel_card_name"], "The Fuel Store")
        self.assertEqual(check.get_json()["rows"][0]["issues"], [])
        self.assert_private(check)
        save = self.client.post(SAVE, json={"rows": [reviewed()]},
                                headers=self.headers(token=token))
        self.assertEqual(save.status_code, 201, save.text)
        self.assertEqual(save.get_json()["saved_count"], 1)
        stored = db.session.execute(select(Fuel.__table__)).mappings().one()
        self.assertEqual((stored["fuel_card_name"], stored["fuel_volume"], stored["fuel_cost"]),
                         ("The Fuel Store", 14327, 18625))
        self.assert_private(save)

    def test_registered_supplier_is_forwarded_to_its_financial_services(self):
        token = self.token()
        before = self.snapshot()
        with patch(CHECKER, return_value={"fuel_card_name": "Silvey", "rows": []}) as checker, \
                patch(SAVER, return_value={"saved_count": 1, "fuel_entries": []}) as saver, \
                patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")):
            for endpoint, row in ((CHECK, selected()), (SAVE, reviewed())):
                with self.subTest(endpoint=endpoint):
                    response = self.client.post(
                        endpoint, json={"rows": [row]},
                        headers=self.headers(supplier="silvey", token=token),
                    )
                    self.assertEqual(response.status_code, 200 if endpoint == CHECK else 201, response.text)
                    self.assert_private(response)
            for service, row in ((checker, selected()), (saver, reviewed())):
                self.assertEqual(service.call_count, 1)
                self.assertEqual(service.call_args.args[0], {"rows": [row]})
                self.assertEqual(service.call_args.kwargs.get("supplier_id"), "silvey")
        self.assertEqual(self.snapshot(), before)

    def test_missing_supplier_header_keeps_the_existing_upload_contract(self):
        response = self.client.post(READ, data=transactions_xlsx(), content_type=XLSX_MIME,
                                    headers={"X-CSRFToken": self.token()})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.get_json()["report"]["fuel_card_name"], "The Fuel Store")
        self.assert_private(response)

    def test_invalid_csrf_precedes_supplier_resolution_and_never_exposes_private_input(self):
        self.token()
        with patch(WORKER) as worker, patch(CHECKER) as checker, patch(SAVER) as saver:
            for endpoint in (READ, CHECK, SAVE):
                response = self.client.post(
                    endpoint, data=b"private-source-value", content_type="application/octet-stream",
                    headers={"X-CSRFToken": "invalid", "X-Fuel-Supplier": "private-supplier-value"},
                )
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(response.get_json()["error"]["code"], "csrf_failed")
                self.assertNotIn("private-", response.text)
                self.assert_private(response)
            worker.assert_not_called()
            checker.assert_not_called()
            saver.assert_not_called()
