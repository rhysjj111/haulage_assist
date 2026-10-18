"""Explanations and explicit review follow current source values, not alert flags."""

from datetime import date, timedelta
from unittest.mock import patch

from owner_test_support import OwnerDatabaseTestCase, db
from haulage_app.models import Day, DriverEmploymentHistory, Fuel, Job, Payslip
from haulage_app.owner_analysis.models import OwnerIssueVerification, OwnerWeekReview
from haulage_app.owner_analysis.overheads import ensure_weekly_overhead, set_overhead_settings
from haulage_app.owner_analysis.reviews import (
    get_reviewed_week, save_issue_verification, save_week_note, save_week_review,
)


class OwnerReviewTests(OwnerDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.start = date(2026, 1, 3)
        self.as_of = date(2026, 1, 17)
        self.add_truck()
        self.add_driver(employment_start=date(2026, 1, 5), employment_end=date(2026, 1, 9))
        self.days, self.jobs = [], []
        for offset in range(2, 7):
            day = self.add_day(driver_id=1, on_date=self.start + timedelta(days=offset))
            self.days.append(day)
            self.jobs.append(self.add_job(day, earned=50000))
        self.payslip = self.add_payslip(driver_id=1, on_date=self.start + timedelta(days=6))
        set_overhead_settings(self.start, 4, 50000)
        ensure_weekly_overhead(self.start)
        db.session.flush()

    def report(self, *, as_of=None):
        return get_reviewed_week(self.start, as_of=as_of or self.as_of)

    def issue(self, code):
        return next(issue for issue in self.report()["issues"] if issue["code"] == code)

    def mark_checked(self, note="Checked against the source records"):
        return save_week_review(self.start, self.report()["week_fingerprint"], note=note, as_of=self.as_of)

    def create_mileage_issue(self):
        db.session.execute(Day.__table__.update().where(Day.id == self.days[0]).values(start_mileage=0))
        return self.issue("missing_mileage")

    def verify(self, issue, note="Checked the original record", **kwargs):
        return save_issue_verification(self.start, issue["key"], note, issue["fingerprint"],
                                       as_of=self.as_of, **kwargs)

    def absence_scope(self, on_date):
        return f"recorded_absence:{self.start}:driver_id=1:date={on_date}"

    def test_no_automatic_issues_does_not_automatically_mark_week_checked(self):
        report = self.report()
        self.assertEqual(report["outstanding_issues"], [])
        self.assertEqual(report["review_status"], "not_reviewed")
        self.assertIsNone(report["reviewed_at"])
        self.mark_checked()
        self.assertEqual(self.report()["review_status"], "checked")

    def test_signoff_note_stays_visible_without_invalidating_its_own_review(self):
        self.mark_checked("Checked against invoices and payroll")
        for unused in range(2):
            report = self.report()
            self.assertEqual(report["review_status"], "checked")
            self.assertEqual(report["review_note"], "Checked against invoices and payroll")
            self.assertEqual(report["verification_history"][-1]["decision"], "reviewed")

    def test_review_reopens_after_actual_job_amount_changes_with_same_record_id(self):
        self.mark_checked()
        before = self.report()["week_fingerprint"]
        db.session.execute(Job.__table__.update().where(Job.id == self.jobs[0]).values(earned=60000))
        report = self.report()
        self.assertNotEqual(report["week_fingerprint"], before)
        self.assertEqual(report["review_status"], "outdated")
        self.assertTrue(report["week_review_outdated"])
        self.assertIsNone(report["reviewed_at"])

    def test_review_reopens_after_same_setting_is_corrected(self):
        self.mark_checked()
        set_overhead_settings(self.start, 5, 50000)
        report = self.report()
        self.assertEqual(report["overheads"], 250000)
        self.assertEqual(report["review_status"], "outdated")

    def test_review_reopens_after_employer_cost_changes(self):
        self.mark_checked()
        db.session.execute(Payslip.__table__.update().where(Payslip.id == self.payslip)
                           .values(total_cost_to_employer=65000))
        self.assertEqual(self.report()["review_status"], "outdated")

    def test_review_reopens_when_expected_employment_dates_change(self):
        self.mark_checked()
        db.session.execute(DriverEmploymentHistory.__table__.update().values(end_date=date(2026, 1, 8)))
        self.assertEqual(self.report()["review_status"], "outdated")

    def test_issue_verification_requires_an_explanation_and_current_fingerprint(self):
        issue = self.create_mileage_issue()
        for note, fingerprint in [("   ", issue["fingerprint"]), ("Checked", "0" * 64)]:
            with self.subTest(note=note, fingerprint=fingerprint), self.assertRaises(ValueError):
                save_issue_verification(self.start, issue["key"], note, fingerprint, as_of=self.as_of)
        self.assertEqual(OwnerIssueVerification.query.count(), 0)

    def test_changed_mileage_reopens_issue_and_preserves_previous_explanation(self):
        issue = self.create_mileage_issue()
        self.verify(issue, "First reading was unavailable")
        self.assertTrue(self.issue("missing_mileage")["resolved"])
        db.session.execute(Day.__table__.update().where(Day.id == self.days[0]).values(end_mileage=140000))
        report = self.report()
        self.assertFalse(self.issue("missing_mileage")["resolved"])
        history = [row for row in report["verification_history"] if row["scope_key"] == issue["key"]]
        self.assertEqual(history[0]["status"], "outdated")
        self.assertEqual(history[0]["note"], "First reading was unavailable")

    def test_unrelated_earnings_edit_does_not_invalidate_mileage_explanation(self):
        issue = self.create_mileage_issue()
        self.verify(issue)
        db.session.execute(Job.__table__.update().where(Job.id == self.jobs[0]).values(earned=60000))
        self.assertTrue(self.issue("missing_mileage")["resolved"])

    def test_corrected_issue_keeps_explanation_as_resolved_history(self):
        issue = self.create_mileage_issue()
        self.verify(issue, "Original reading checked")
        db.session.execute(Day.__table__.update().where(Day.id == self.days[0]).values(start_mileage=100000))
        report = self.report()
        self.assertFalse(any(row["code"] == "missing_mileage" for row in report["issues"]))
        saved = next(row for row in report["verification_history"] if row["scope_key"] == issue["key"])
        self.assertEqual(saved["status"], "resolved")
        self.assertEqual(saved["note"], "Original reading checked")

    def test_missing_fuel_receipt_cannot_be_waived_to_manufacture_a_result(self):
        db.session.execute(Day.__table__.update().where(Day.id == self.days[0]).values(fuel=True))
        issue = self.issue("missing_fuel_receipt")
        self.assertFalse(issue["can_verify"])
        with self.assertRaises(ValueError):
            self.verify(issue, "Truck was off")
        self.assertIsNone(self.report()["estimated_operating_result"])

    def test_unknown_payroll_requires_explicit_confirmed_zero_decision(self):
        db.session.execute(Payslip.__table__.delete().where(Payslip.id == self.payslip))
        issue = self.issue("missing_payslip")
        self.assertEqual(issue["verification_decisions"], ["confirmed_zero"])
        with self.assertRaises(ValueError):
            self.verify(issue)
        self.verify(issue, "Confirmed no payroll cost for this driver this week", decision="confirmed_zero")
        report = self.report()
        self.assertEqual(report["employer_cost"], 0)
        self.assertEqual(report["outstanding_issues"], [])
        self.assertIsNotNone(report["estimated_operating_result"])

    def test_stale_signoff_is_rejected_instead_of_overwriting_current_state(self):
        fingerprint = self.report()["week_fingerprint"]
        db.session.execute(Job.__table__.update().where(Job.id == self.jobs[0]).values(earned=60000))
        with self.assertRaises(ValueError):
            save_week_review(self.start, fingerprint, as_of=self.as_of)
        self.assertEqual(OwnerWeekReview.query.count(), 0)

    def test_current_week_cannot_receive_final_signoff(self):
        on_friday = self.start + timedelta(days=6)
        report = self.report(as_of=on_friday)
        self.assertEqual(report["period_state"], "in_progress")
        with self.assertRaises(ValueError):
            save_week_review(self.start, report["week_fingerprint"], as_of=on_friday)

    def test_outstanding_financial_issues_prevent_final_review(self):
        # Missing mileage is optional; missing working-day earnings remains
        # essential and must be corrected or explicitly explained first.
        db.session.execute(Job.__table__.delete().where(Job.id == self.jobs[0]))
        self.assertTrue(self.issue("working_day_without_earnings"))
        with self.assertRaises(ValueError):
            self.mark_checked()

    def test_period_note_explains_irregularity_without_resolving_issues(self):
        self.create_mileage_issue()
        before = self.report()
        save_week_note(self.start, "Truck off for repairs Tuesday–Thursday", before["week_fingerprint"], as_of=self.as_of)
        report = self.report()
        self.assertEqual(len(report["outstanding_issues"]), len(before["outstanding_issues"]))
        self.assertEqual(report["verification_history"][0]["decision"], "note")

    def test_absence_note_keeps_driver_and_date_association_and_ignores_unrelated_figures(self):
        on_date = self.start + timedelta(days=3)
        db.session.execute(Day.__table__.update().where(Day.id == self.days[1]).values(status="absent"))
        scope = self.absence_scope(on_date)
        save_week_note(self.start, "Truck unavailable", self.report()["week_fingerprint"],
                       scope_key=scope, as_of=self.as_of)
        db.session.execute(Job.__table__.update().where(Job.id == self.jobs[0]).values(earned=60000))
        row = next(item for item in self.report()["verification_history"] if item["scope_key"] == scope)
        self.assertEqual(row["status"], "note")
        self.assertEqual(row["note"], "Truck unavailable")
        db.session.execute(Day.__table__.update().where(Day.id == self.days[1]).values(status="holiday"))
        row = next(item for item in self.report()["verification_history"] if item["scope_key"] == scope)
        self.assertEqual(row["status"], "outdated")

    def test_absence_scope_requires_a_recorded_absence_in_the_selected_week(self):
        invalid_scopes = ["made_up", self.absence_scope(self.start + timedelta(days=2)),
                          self.absence_scope(self.start + timedelta(days=7)),
                          f"recorded_absence:{self.start}:driver_id=999:date={self.start + timedelta(days=3)}"]
        for scope in invalid_scopes:
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                save_week_note(self.start, "Reason", self.report()["week_fingerprint"],
                               scope_key=scope, as_of=self.as_of)
        self.assertEqual(OwnerIssueVerification.query.count(), 0)

    def test_review_read_has_no_database_writes_and_save_services_do_not_commit(self):
        issue = self.create_mileage_issue()
        with patch.object(db.session, "commit", side_effect=AssertionError("unexpected commit")):
            self.verify(issue)
            self.mark_checked()
            self.report()
        self.assertEqual(list(db.session.new), [])
        self.assertEqual(list(db.session.dirty), [])

    def test_verification_becomes_outdated_when_check_rule_version_changes(self):
        issue = self.create_mileage_issue()
        self.verify(issue)
        with patch("haulage_app.owner_analysis.reviews.RULE_VERSION", 2):
            self.assertFalse(self.issue("missing_mileage")["resolved"])

