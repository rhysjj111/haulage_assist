"""The same check page submits explanations without hiding unknown costs."""

from datetime import date
from unittest.mock import patch
from urllib.parse import urlsplit

from owner_test_support import OwnerTestCase, app, db
from test_owner_unified_review import _ReviewHTML
from haulage_app.models import Day, Fuel
from haulage_app.owner_analysis.models import OwnerIssueVerification


class OwnerCheckActionTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        clock = patch("haulage_app.owner_analysis.routes.today_london", return_value=date(2026, 10, 20))
        clock.start()
        self.addCleanup(clock.stop)
        self.add_truck()
        self.add_driver(employment_start=None)
        self.day = self.add_day()
        self.add_job(self.day)
        self.add_payslip()
        self.configure_overheads()

    def review(self, code):
        _, checks = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        issue = next(item for item in checks["report"]["issues"] if item["code"] == code)
        response, context = self.get_page(issue["investigation_url"])
        parsed = _ReviewHTML(response.text)
        forms = [form for form in parsed.forms if urlsplit(form.get("action", "")).path == "/owner-analysis/verify"]
        self.assertEqual(len(forms), 1, "Review decisions belong on the same check page as its evidence")
        return issue, response, context, parsed, forms[0]

    def test_fuel_typo_review_allows_correction_or_dismissal_without_modifying_record(self):
        fuel = self.add_fuel(fuel_cost=1000)
        issue, response, context, parsed, form = self.review("fuel_price_unusual")
        self.assertTrue(parsed.correction("fuel"))
        self.assertIn('value="dismissed"', response.text)
        result = self.client.post(form["action"], data=dict(parsed.hidden_values(form),
            decision="dismissed", note="Fuel <invoice> checked; unusual purchase is genuine"))
        self.assertEqual(result.status_code, 303, result.text)
        self.assertEqual(db.session.get(Fuel, fuel).fuel_cost, 1000)
        saved = OwnerIssueVerification.query.one()
        self.assertEqual(saved.decision, "dismissed")
        refreshed, _ = self.get_page(issue["investigation_url"])
        self.assertIn("Fuel &lt;invoice&gt; checked", refreshed.text)
        self.assertNotIn("Fuel <invoice> checked", refreshed.text)
        self.assertFalse(_ReviewHTML(refreshed.text).forms,
                         "A resolved check must not retain an editable stale correction")

    def test_missing_invoice_has_awaiting_action_and_retry_retains_reason_and_fuel_form(self):
        db.session.execute(Day.__table__.update().where(Day.id == self.day).values(fuel=True))
        db.session.commit()
        issue, response, context, parsed, form = self.review("missing_fuel_receipt")
        self.assertIn('value="awaiting_invoice"', response.text)
        self.assertNotIn('value="dismissed"', response.text)
        reason = "Provider <invoice> due Friday"
        rejected = self.client.post(form["action"], data=dict(parsed.hidden_values(form),
            decision="dismissed", note=reason))
        self.assertEqual(rejected.status_code, 400)
        retry = _ReviewHTML(rejected.text)
        retry_form = next(item for item in retry.forms if urlsplit(item.get("action", "")).path == "/owner-analysis/verify")
        self.assertEqual(retry_form["fields"]["note"]["value"], reason)
        # Adding fuel and clearing an accidental fuel marker share the fuel
        # endpoint; identify the actual receipt editor by its entry fields.
        receipt_forms = [item for item in retry.forms
                         if {"fuel_volume", "fuel_cost"}.issubset(item["fields"])]
        self.assertEqual(len(receipt_forms), 1)
        self.assertEqual(OwnerIssueVerification.query.count(), 0)
        saved = self.client.post(retry_form["action"], data=dict(retry.hidden_values(retry_form),
            decision="awaiting_invoice", note=reason))
        self.assertEqual(saved.status_code, 303, saved.text)
        refreshed, checks = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        self.assertEqual(len(checks["report"]["outstanding_issues"]), 1)
        self.assertIsNone(checks["report"]["estimated_operating_result"])
        current = next(item for item in checks["report"]["issues"] if item["key"] == issue["key"])
        self.assertTrue(current["awaiting_invoice"])
        self.assertFalse(current["resolved"])
        self.assertTrue(db.session.get(Day, self.day).fuel)
        self.assertEqual(Fuel.query.count(), 0)

    def test_new_decision_requires_csrf_and_rejects_stale_source_fingerprint(self):
        fuel = self.add_fuel(fuel_cost=1000)
        app.config["WTF_CSRF_ENABLED"] = True
        self.addCleanup(lambda: app.config.update(WTF_CSRF_ENABLED=False))
        issue, _, _, parsed, form = self.review("fuel_price_unusual")
        payload = dict(parsed.hidden_values(form), decision="dismissed", note="Original invoice checked")
        without_csrf = {key: value for key, value in payload.items() if key != "csrf_token"}
        self.assertEqual(self.client.post(form["action"], data=without_csrf).status_code, 400)
        self.assertEqual(OwnerIssueVerification.query.count(), 0)
        db.session.execute(Fuel.__table__.update().where(Fuel.id == fuel).values(fuel_volume=9000))
        db.session.commit()
        self.assertEqual(self.client.post(form["action"], data=payload).status_code, 400)
        self.assertEqual(OwnerIssueVerification.query.count(), 0)
        _, _, _, current, current_form = self.review("fuel_price_unusual")
        saved = self.client.post(current_form["action"], data=dict(current.hidden_values(current_form),
            decision="dismissed", note="Updated invoice checked"))
        self.assertEqual(saved.status_code, 303, saved.text)
        self.assertEqual(OwnerIssueVerification.query.count(), 1)
