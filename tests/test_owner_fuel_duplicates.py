"""Duplicate fuel edits require a current candidate and exact signed membership."""

from datetime import date
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from owner_test_support import OwnerTestCase, app, db
from haulage_app.models import Fuel, Job
from haulage_app.owner_analysis.corrections import correction_url
from haulage_app.owner_analysis.reviews import get_reviewed_week, save_issue_verification


class OwnerFuelDuplicateTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        clock = patch("haulage_app.owner_analysis.routes.today_london", return_value=date(2026, 10, 20))
        clock.start()
        self.addCleanup(clock.stop)
        self.add_truck()
        self.add_truck(2)
        self.add_driver(employment_start=None)
        self.day = self.add_day()
        self.job = self.add_job(self.day)
        self.add_payslip()
        self.configure_overheads()
        self.first = self.add_fuel(fuel_card_name="Fleet")
        self.second = self.add_fuel(fuel_card_name="fleet")

    def review(self):
        _, checks = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        issue = next(item for item in checks["report"]["issues"]
                     if item["code"] == "possible_duplicate_fuel")
        response, context = self.get_page(issue["investigation_url"])
        return issue, response, context["correction_editor"]

    @staticmethod
    def delete_path(editor, record_id):
        return "/fuel/delete_fuel/" + str(record_id) + "?owner_context=" + editor["token"]

    @staticmethod
    def data(**changes):
        data = dict(date="2026-10-05", truck_id="1", fuel_card_name="Fleet",
                    fuel_volume="100.00", fuel_cost="125.00")
        data.update(changes)
        return data

    def test_group_is_reviewed_once_and_deletion_requires_explicit_confirmation(self):
        issue, response, editor = self.review()
        self.assertEqual(editor["group_kind"], "fuel")
        self.assertEqual([row["id"] for row in editor["group_rows"]], [self.first, self.second])
        self.assertIn("fuel", response.text.lower())
        path = self.delete_path(editor, self.second)
        for payload in ({}, {"confirm_delete": "on"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(path, data=payload).status_code, 400)
                self.assertEqual(Fuel.query.count(), 2)
        result = self.client.post(path, data={"confirm_delete": "yes"})
        self.assertEqual(result.status_code, 303, result.text)
        self.assertEqual(Fuel.query.count(), 1)
        self.assertEqual(db.session.get(Fuel, self.first).fuel_cost, 12000)
        report = get_reviewed_week(self.start, as_of=date(2026, 10, 20))
        self.assertEqual(report["fuel_spending"], 12000)
        self.assertFalse(any(item["code"] == "possible_duplicate_fuel" for item in report["issues"]))
        self.assertEqual(self.client.post(path, data={"confirm_delete": "yes"}).status_code, 409)

    def test_edit_cannot_change_candidate_truck_or_purchase_date(self):
        _, _, editor = self.review()
        path = editor["group_rows"][0]["edit_url"]
        page, context = self.get_page(path)
        self.assertTrue(context["correction_editor"]["group_member"])
        for changes in ({"truck_id": "2"}, {"date": "2026-10-06"}):
            with self.subTest(changes=changes):
                response = self.client.post(path, data=self.data(**changes))
                self.assertEqual(response.status_code, 400, response.text)
                stored = db.session.get(Fuel, self.first)
                self.assertEqual((stored.truck_id, stored.date, stored.fuel_cost),
                                 (1, date(2026, 10, 5), 12000))
        response = self.client.post(path, data=self.data())
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(db.session.get(Fuel, self.first).fuel_cost, 12500)
        self.assertEqual(Fuel.query.count(), 2)

    def test_unrelated_purchase_does_not_stale_candidate_but_new_matching_member_does(self):
        _, _, editor = self.review()
        path = editor["group_rows"][0]["edit_url"]
        self.add_fuel(fuel_card_name="Different company")
        self.assertEqual(self.client.get(path).status_code, 200)
        self.add_fuel()
        self.assertEqual(self.client.post(path, data=self.data()).status_code, 409)
        self.assertEqual(self.client.post(self.delete_path(editor, self.first),
                         data={"confirm_delete": "yes"}).status_code, 409)
        self.assertEqual(Fuel.query.count(), 4)
        self.assertEqual(db.session.get(Fuel, self.first).fuel_cost, 12000)

    def test_changed_sibling_prevents_stale_edit_and_delete(self):
        _, _, editor = self.review()
        path = editor["group_rows"][0]["edit_url"]
        db.session.execute(Fuel.__table__.update().where(Fuel.id == self.second).values(fuel_cost=13000))
        db.session.commit()
        self.assertEqual(self.client.post(path, data=self.data()).status_code, 409)
        self.assertEqual(self.client.post(self.delete_path(editor, self.first),
                         data={"confirm_delete": "yes"}).status_code, 409)
        self.assertEqual(Fuel.query.count(), 2)

    def test_resolved_check_prevents_previously_open_edit_or_delete(self):
        issue, _, editor = self.review()
        save_issue_verification(self.start, issue["key"], "Two genuine invoice lines",
                                issue["fingerprint"], decision="verified", as_of=date(2026, 10, 20))
        db.session.commit()
        self.assertEqual(self.client.post(editor["group_rows"][0]["edit_url"],
                         data=self.data()).status_code, 409)
        self.assertEqual(self.client.post(self.delete_path(editor, self.second),
                         data={"confirm_delete": "yes"}).status_code, 409)
        self.assertEqual(Fuel.query.count(), 2)

    def test_wrong_record_and_non_group_context_cannot_delete_receipt(self):
        _, _, editor = self.review()
        other = self.add_fuel(fuel_card_name="Other company")
        self.assertEqual(self.client.post(self.delete_path(editor, other),
                         data={"confirm_delete": "yes"}).status_code, 400)
        with app.test_request_context():
            singular = correction_url(self.start, dict(code="fuel_price_unusual",
                record_type="fuel", record_id=self.first))
        token = parse_qs(urlsplit(singular).query)["owner_context"][0]
        path = "/fuel/delete_fuel/" + str(self.first) + "?owner_context=" + token
        self.assertEqual(self.client.post(path, data={"confirm_delete": "yes"}).status_code, 400)
        self.assertEqual(Fuel.query.count(), 3)

    def test_fuel_candidate_deletion_requires_csrf_when_enabled(self):
        app.config["WTF_CSRF_ENABLED"] = True
        self.addCleanup(lambda: app.config.update(WTF_CSRF_ENABLED=False))
        _, _, editor = self.review()
        path = self.delete_path(editor, self.second)
        self.assertEqual(self.client.post(path, data={"confirm_delete": "yes"}).status_code, 400)
        response = self.client.post(path, data={"confirm_delete": "yes",
                                               "csrf_token": editor["form"].csrf_token.current_token})
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(Fuel.query.count(), 1)

    def test_group_review_does_not_flush_unrelated_unsaved_edits(self):
        pending = db.session.get(Job, self.job)
        pending.notes = "Unsaved other form"
        with patch.object(db.session, "flush", side_effect=AssertionError("GET attempted flush")):
            _, _, editor = self.review()
            self.assertEqual(len(editor["group_rows"]), 2)
        self.assertIn(pending, db.session.dirty)
