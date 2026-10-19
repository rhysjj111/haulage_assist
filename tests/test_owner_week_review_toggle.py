"""A one-button weekly sign-off can be undone without changing business data."""

from datetime import date, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select, text
from werkzeug.datastructures import MultiDict

from owner_test_support import OwnerTestCase, app, db
from test_owner_unified_review import _ReviewHTML
from haulage_app.models import Day, Job
from haulage_app.owner_analysis.models import OwnerIssueVerification, OwnerWeekReview
from haulage_app.owner_analysis.monthly import get_monthly_report
from haulage_app.owner_analysis.reviews import (
    get_reviewed_week, save_issue_verification, save_week_note, save_week_review,
    undo_week_review,
)


class OwnerWeekReviewToggleTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.as_of = date(2026, 10, 18)
        clock = patch("haulage_app.owner_analysis.routes.today_london", return_value=self.as_of)
        clock.start()
        self.addCleanup(clock.stop)
        self.add_truck()
        self.add_driver(first_name="Alice", employment_start=date(2026, 10, 5),
                        employment_end=date(2026, 10, 9))
        for offset in range(5):
            self.add_job(self.add_day(on_date=date(2026, 10, 5) + timedelta(days=offset)))
        self.add_fuel()
        self.add_payslip()
        self.configure_overheads()
        self.page = "/owner-analysis/checks?week_start=2026-10-03"

    def report(self):
        return get_reviewed_week(self.start, as_of=self.as_of)

    def check(self):
        report = self.report()
        return save_week_review(self.start, report["week_fingerprint"],
                                expected_review_id=report["last_review_id"], as_of=self.as_of)

    def undo(self):
        report = self.report()
        return undo_week_review(self.start, report["week_fingerprint"],
                                expected_review_id=report["last_review_id"], as_of=self.as_of)

    def source_snapshot(self):
        with db.session.no_autoflush:
            return {name: [tuple(row) for row in db.session.execute(select(table).order_by(table.c.id))]
                    for name, table in db.metadata.tables.items()
                    if name in {"day", "job", "fuel", "payslip", "owner_overhead_setting", "owner_weekly_overhead"}}

    def review_form(self, page=None, week_start=None):
        response, context = self.get_page(page or self.page)
        parsed = _ReviewHTML(response.text)
        forms = [form for form in parsed.forms
                 if urlsplit(form.get("action", "")).path == "/owner-analysis/review"
                 and form["fields"]["week_start"]["value"] == (week_start or self.start).isoformat()]
        self.assertEqual(len(forms), 1)
        return response, context, parsed, forms[0]

    def post_form(self, parsed, form, **overrides):
        return self.client.post(form["action"], data=dict(parsed.hidden_values(form), **overrides))

    def test_button_changes_to_undo_and_back_without_checkboxes_or_review_note(self):
        response, _, parsed, form = self.review_form()
        self.assertIn("Mark as checked", response.text)
        self.assertEqual(form["fields"]["action"]["value"], "check")
        self.assertEqual(form["fields"]["review_id"]["value"], "0")
        self.assertNotIn("note", form["fields"])
        self.assertFalse(any(field.get("type") == "checkbox" for field in form["fields"].values()))
        self.assertEqual(self.post_form(parsed, form).status_code, 303)
        response, _, parsed, form = self.review_form()
        self.assertEqual(form["fields"]["action"]["value"], "undo")
        self.assertGreater(int(form["fields"]["review_id"]["value"]), 0)
        self.assertRegex(response.text, r">\s*Undo\s*</button>")
        self.assertNotIn("Mark as checked", response.text)
        self.assertNotIn("note", form["fields"])
        self.assertEqual(self.post_form(parsed, form).status_code, 303)
        response, _, _, form = self.review_form()
        self.assertEqual(form["fields"]["action"]["value"], "check")
        self.assertIn("Mark as checked", response.text)

    def test_undo_preserves_source_totals_individual_decisions_and_signoff_history(self):
        db.session.execute(text("UPDATE fuel SET fuel_cost = 1000 WHERE id = 1"))
        issue = next(row for row in self.report()["issues"] if row["code"] == "fuel_price_unusual")
        decision = save_issue_verification(self.start, issue["key"], "Original invoice checked",
                                            issue["fingerprint"], decision="dismissed", as_of=self.as_of)
        decision_values = (decision.id, decision.decision, decision.note, decision.source_fingerprint)
        before = self.source_snapshot()
        checked = self.check()
        original_review = (checked.id, checked.note, checked.source_fingerprint, checked.created_at)
        totals = {key: self.report()[key] for key in
                  ("earnings", "fuel_spending", "employer_cost", "overheads", "estimated_operating_result")}
        self.undo()
        report = self.report()
        self.assertEqual(report["review_status"], "not_reviewed")
        self.assertTrue(report["week_review_undone"])
        self.assertFalse(report["week_review_outdated"])
        self.assertIsNone(report["reviewed_at"])
        self.assertEqual({key: report[key] for key in totals}, totals)
        self.assertEqual(self.source_snapshot(), before)
        self.assertEqual((decision.id, decision.decision, decision.note, decision.source_fingerprint), decision_values)
        self.assertTrue(next(row for row in report["issues"] if row["key"] == issue["key"])["resolved"])
        saved = OwnerWeekReview.query.one()
        self.assertEqual((saved.id, saved.note, saved.source_fingerprint, saved.created_at), original_review)
        self.assertEqual(report["week_review_history"][0]["status"], "undone")
        event = next(row for row in report["verification_history"] if row.get("event") == "week_review_undo")
        self.assertEqual(event["target_review_id"], saved.id)

    def test_undo_is_permanent_for_that_signoff_even_if_original_source_values_return(self):
        self.check()
        self.undo()
        for amount in (60000, 50000):
            db.session.execute(text("UPDATE job SET earned = :amount WHERE id = 1"), {"amount": amount})
            report = self.report()
            self.assertEqual(report["review_status"], "not_reviewed")
            self.assertTrue(report["week_review_undone"])
        self.assertEqual(OwnerWeekReview.query.count(), 1)

    def test_stale_clicks_cannot_create_duplicate_reviews_or_undo_a_later_signoff(self):
        _, _, parsed, first_form = self.review_form()
        initial = parsed.hidden_values(first_form)
        self.assertEqual(self.post_form(parsed, first_form).status_code, 303)
        self.assertEqual(self.client.post(first_form["action"], data=initial).status_code, 303)
        self.assertEqual(OwnerWeekReview.query.count(), 1)
        _, _, parsed, undo_form = self.review_form()
        old_undo = parsed.hidden_values(undo_form)
        self.assertEqual(self.post_form(parsed, undo_form).status_code, 303)
        self.assertEqual(self.client.post(undo_form["action"], data=old_undo).status_code, 303)
        self.assertEqual(OwnerIssueVerification.query.count(), 1, "An undo event is appended only once")
        _, _, parsed, recheck_form = self.review_form()
        self.assertEqual(self.post_form(parsed, recheck_form).status_code, 303)
        newer_id = self.report()["last_review_id"]
        self.assertNotEqual(newer_id, int(old_undo["review_id"]))
        # Even substituting the current source fingerprint must not make an
        # old sign-off ID able to revoke this newer explicit decision.
        old_undo["fingerprint"] = self.report()["week_fingerprint"]
        self.assertEqual(self.client.post(undo_form["action"], data=old_undo).status_code, 303)
        self.assertEqual(self.report()["review_status"], "checked")
        self.assertEqual(self.report()["last_review_id"], newer_id)
        self.assertEqual(OwnerWeekReview.query.count(), 2)
        self.assertEqual(OwnerIssueVerification.query.count(), 1)

    def test_check_action_cannot_replace_undo_while_already_checked(self):
        self.check()
        db.session.commit()
        _, _, parsed, form = self.review_form()
        self.assertEqual(self.post_form(parsed, form, action="check").status_code, 303)
        self.assertEqual(OwnerWeekReview.query.count(), 1)
        self.assertEqual(OwnerIssueVerification.query.count(), 0)
        self.assertEqual(self.report()["review_status"], "checked")

    def test_undo_requires_exact_current_signoff_and_current_source_values(self):
        with self.assertRaises(ValueError):
            self.undo()
        checked = self.check()
        report = self.report()
        for invalid_id in (0, checked.id + 1, -1, True, str(checked.id)):
            with self.subTest(review_id=invalid_id), self.assertRaises(ValueError):
                undo_week_review(self.start, report["week_fingerprint"],
                                 expected_review_id=invalid_id, as_of=self.as_of)
        db.session.execute(text("UPDATE job SET earned = earned + 100 WHERE id = 1"))
        with self.assertRaises(ValueError):
            undo_week_review(self.start, report["week_fingerprint"],
                             expected_review_id=checked.id, as_of=self.as_of)
        changed = self.report()
        with self.assertRaises(ValueError):
            undo_week_review(self.start, changed["week_fingerprint"],
                             expected_review_id=checked.id, as_of=self.as_of)
        self.assertEqual(OwnerIssueVerification.query.count(), 0)
        self.assertEqual(self.report()["review_status"], "outdated")

    def test_current_future_and_incomplete_weeks_cannot_be_checked_by_forging_action(self):
        for week in ("2026-10-17", "2099-01-03"):
            _, context = self.get_page("/owner-analysis/checks?week_start=" + week)
            response = self.client.post("/owner-analysis/review", data={
                "week_start": week, "fingerprint": context["report"]["week_fingerprint"],
                "review_id": "0", "action": "check"})
            self.assertEqual(response.status_code, 303)
        db.session.execute(text("DELETE FROM payslip"))
        db.session.commit()
        _, _, parsed, form = self.review_form()
        self.assertEqual(self.post_form(parsed, form).status_code, 303)
        self.assertEqual(OwnerWeekReview.query.count(), 0)
        self.assertTrue(self.report()["outstanding_issues"])

    def test_check_and_undo_require_csrf_and_each_hidden_guard_exactly_once(self):
        app.config["WTF_CSRF_ENABLED"] = True
        self.addCleanup(lambda: app.config.update(WTF_CSRF_ENABLED=False))
        for expected_action in ("check", "undo"):
            _, _, parsed, form = self.review_form()
            payload = parsed.hidden_values(form)
            self.assertEqual(payload["action"], expected_action)
            before = (OwnerWeekReview.query.count(), OwnerIssueVerification.query.count())
            no_csrf = {key: value for key, value in payload.items() if key != "csrf_token"}
            self.assertEqual(self.client.post(form["action"], data=no_csrf).status_code, 303)
            for name in ("week_start", "fingerprint", "review_id", "action"):
                with self.subTest(action=expected_action, field=name):
                    missing = {key: value for key, value in payload.items() if key != name}
                    self.assertEqual(self.client.post(form["action"], data=missing).status_code, 400)
                    repeated = MultiDict(payload)
                    repeated.add(name, payload[name])
                    self.assertEqual(self.client.post(form["action"], data=repeated).status_code, 400)
                    self.assertEqual((OwnerWeekReview.query.count(), OwnerIssueVerification.query.count()), before)
            self.assertEqual(self.client.post(form["action"], data=payload).status_code, 303)
        self.assertEqual(self.report()["review_status"], "not_reviewed")

    def test_public_note_endpoint_cannot_forge_an_undo_audit_event(self):
        checked = self.check()
        db.session.commit()
        report = self.report()
        scope = f"week_review_undo:{self.start}:review_id={checked.id}"
        with self.assertRaises(ValueError):
            save_week_note(self.start, "Invented undo", report["week_fingerprint"],
                           scope_key=scope, as_of=self.as_of)
        response = self.client.post("/owner-analysis/note", data={
            "week_start": self.start.isoformat(), "fingerprint": report["week_fingerprint"],
            "scope_key": scope, "note": "Invented undo"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(OwnerIssueVerification.query.count(), 0)
        self.assertEqual(self.report()["review_status"], "checked")

    def test_undo_propagates_to_month_and_preserves_monthly_return_context(self):
        as_of = date(2026, 10, 10)
        with patch("haulage_app.owner_analysis.routes.today_london", return_value=as_of):
            page = "/owner-analysis/checks/monthly?month=2026-10&week_start=2026-10-03&view=drivers&driver_id=1"
            for expected_action in ("check", "undo", "check"):
                _, _, parsed, form = self.review_form(page)
                self.assertEqual(form["fields"]["action"]["value"], expected_action)
                response = self.post_form(parsed, form)
                target = urlsplit(response.location)
                self.assertEqual(target.path, "/owner-analysis/checks/monthly")
                self.assertEqual(parse_qs(target.query), {"month": ["2026-10"], "week_start": ["2026-10-03"],
                                                         "view": ["drivers"], "driver_id": ["1"]})
                self.assertEqual(target.fragment, "week-2026-10-03")
                month = get_monthly_report(2026, 10, as_of=as_of)
                self.assertEqual(month["review_status"], "not_reviewed" if expected_action == "undo" else "checked")
                self.assertEqual(month["reviewed_through"], None if expected_action == "undo" else date(2026, 10, 9))

    def test_checked_and_undone_gets_preserve_pending_edits_and_never_write(self):
        for action in (self.check, self.undo):
            action()
            db.session.commit()
            before = self.source_snapshot()
            counts = (OwnerWeekReview.query.count(), OwnerIssueVerification.query.count())
            job = db.session.get(Job, 1)
            job.notes = "Unsaved local change"
            with patch.object(db.session, "commit", side_effect=AssertionError("GET must not commit")):
                for path in (self.page, "/owner-analysis?week_start=2026-10-03",
                             "/owner-analysis/checks/monthly?month=2026-10"):
                    self.get_page(path)
                    self.assertIn(job, db.session.dirty)
                    self.assertEqual(self.source_snapshot(), before)
            with db.session.no_autoflush:
                self.assertEqual((OwnerWeekReview.query.count(), OwnerIssueVerification.query.count()), counts)
            db.session.expire(job, ["notes"])
