"""Actionable financial checks stay distinct from optional operating details."""

from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import select

from owner_test_support import OwnerTestCase, db
from haulage_app.models import Day, Fuel, Job, Payslip
from haulage_app.owner_analysis.breakdowns import build_breakdown
from haulage_app.owner_analysis.calculations import calculate_weekly_report
from haulage_app.owner_analysis.models import OwnerIssueVerification, OwnerWeekReview
from haulage_app.owner_analysis.monthly import get_monthly_report
from haulage_app.owner_analysis.reviews import (
    fingerprint_for_scope, get_reviewed_week, save_issue_verification, save_week_note, save_week_review,
)


class OwnerCheckPolicyTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.add_truck()
        self.add_driver(employment_start=None)
        self.day = self.add_day(fuel=False)
        self.job = self.add_job(self.day)
        self.payslip = self.add_payslip()
        self.configure_overheads()
        self.as_of = date(2026, 10, 20)

    def report(self, *, as_of=None):
        return get_reviewed_week(self.start, as_of=as_of or self.as_of)

    def issue(self, code):
        return next(row for row in self.report()["issues"] if row["code"] == code)

    def verify(self, issue, decision, note="Invoice checked against the original"):
        return save_issue_verification(self.start, issue["key"], note,
                                       issue["fingerprint"], decision=decision,
                                       as_of=self.as_of)

    def test_fuel_price_checks_exact_hundredths_without_rounding_boundary_errors(self):
        fuel = self.add_fuel(fuel_volume=10000)
        for cost, unusual in [(5000, False), (4999, True), (30000, False),
                              (30001, True), (1000, True), (12000, False)]:
            with self.subTest(cost=cost):
                db.session.execute(Fuel.__table__.update().where(Fuel.id == fuel)
                                   .values(fuel_cost=cost))
                report = self.report()
                issues = [item for item in report["issues"] if item["code"] == "fuel_price_unusual"]
                self.assertEqual(bool(issues), unusual)
                self.assertEqual(report["fuel_spending"], cost,
                                 "A warning must preserve the actual recorded purchase")
                if issues:
                    self.assertEqual(issues[0]["record_id"], fuel)
                    self.assertTrue(issues[0]["blocking"])
                    self.assertIsNone(report["estimated_operating_result"])

    def test_invalid_fuel_amounts_have_one_amount_check_and_no_secondary_price_warning(self):
        fuel = self.add_fuel()
        for cost, volume in [(100, 10000), (12000, 0), (12000, 100000)]:
            with self.subTest(cost=cost, volume=volume):
                db.session.execute(Fuel.__table__.update().where(Fuel.id == fuel)
                                   .values(fuel_cost=cost, fuel_volume=volume))
                codes = [item["code"] for item in self.report()["issues"]]
                self.assertIn("fuel_amount_out_of_range", codes)
                self.assertNotIn("fuel_price_unusual", codes)

    def test_duplicate_fuel_is_one_candidate_group_and_preserves_all_recorded_costs(self):
        first = self.add_fuel(fuel_card_name="  Fleet   Card ")
        second = self.add_fuel(fuel_card_name="fleet card")
        third = self.add_fuel(fuel_card_name="FLEET CARD")
        self.add_fuel(fuel_card_name="Different card")
        self.add_fuel(fuel_card_name="Fleet card", fuel_cost=12001)
        self.add_fuel(fuel_card_name="Fleet card", fuel_volume=10001)
        self.add_fuel(fuel_card_name="Fleet card", on_date=date(2026, 10, 6))
        self.add_truck(2)
        self.add_fuel(fuel_card_name="Fleet card", truck_id=2)
        report = self.report()
        groups = [item for item in report["issues"] if item["code"] == "possible_duplicate_fuel"]
        self.assertEqual(len(groups), 1, "Report one reviewable group, not every receipt pair")
        self.assertEqual(groups[0]["record_ids"], [first, second, third])
        self.assertEqual(report["record_counts"]["fuel_entries"], 8)
        self.assertEqual(report["fuel_spending"], 96001)
        self.assertIsNone(report["estimated_operating_result"])

    def test_payroll_gap_uses_same_payslip_and_both_generous_thresholds(self):
        for net, cost, unusual in [(5000, 25000, False), (5000, 25001, True),
                                    (4000, 20001, False), (4000, 24000, True),
                                    (50000, 85000, False), (85000, 60000, False)]:
            with self.subTest(net=net, cost=cost):
                db.session.execute(Payslip.__table__.update().where(Payslip.id == self.payslip)
                                   .values(total_wage=net, total_cost_to_employer=cost))
                report = self.report()
                gaps = [item for item in report["issues"] if item["code"] == "payroll_gap_unusual"]
                self.assertEqual(bool(gaps), unusual)
                self.assertEqual(report["employer_cost"], cost)
                if gaps:
                    self.assertEqual(gaps[0]["record_id"], self.payslip)
                    self.assertIsNone(report["estimated_operating_result"])
        db.session.execute(Payslip.__table__.update().where(Payslip.id == self.payslip)
                           .values(total_wage=100, total_cost_to_employer=50000))
        codes = {item["code"] for item in self.report()["issues"]}
        self.assertIn("payslip_amount_out_of_range", codes)
        self.assertNotIn("payroll_gap_unusual", codes)

    def test_bonus_variation_and_job_earnings_are_not_a_net_pay_matching_rule(self):
        self.add_payslip(on_date=date(2026, 9, 25), total_wage=20000,
                         total_cost_to_employer=25000)
        db.session.execute(Payslip.__table__.update().where(Payslip.id == self.payslip)
                           .values(total_wage=110000, total_cost_to_employer=135000))
        db.session.execute(Job.__table__.update().where(Job.id == self.job).values(earned=12500))
        report = self.report()
        self.assertEqual(report["outstanding_issues"], [])
        self.assertEqual(report["employer_cost"], 135000)
        self.assertEqual(report["earnings"], 12500)

    def test_optional_mileage_is_visible_but_does_not_block_signoff_or_driver_card(self):
        db.session.execute(Day.__table__.update().where(Day.id == self.day)
                           .values(start_mileage=0, truck_id=None))
        report = self.report()
        self.assertEqual(report["outstanding_issues"], [])
        self.assertEqual({item["code"] for item in report["optional_issues"]},
                         {"missing_mileage", "working_day_without_truck"})
        self.assertIsNotNone(report["estimated_operating_result"])
        row = build_breakdown(report, "driver")["rows"][0]
        self.assertFalse(row["entries_pending"])
        self.assertFalse(row["payroll_pending"])
        save_week_review(self.start, report["week_fingerprint"], as_of=self.as_of)
        self.assertEqual(self.report()["review_status"], "checked")
        month = get_monthly_report(2026, 10, as_of=date(2026, 10, 10))
        self.assertEqual(month["review_status"], "checked")
        self.assertEqual(month["outstanding_issues"], [])
        self.assertEqual(len(month["optional_issues"]), 2)

    def test_all_sources_share_review_window_and_never_auto_signoff(self):
        db.session.execute(Fuel.__table__.delete())
        db.session.execute(Day.__table__.update().where(Day.id == self.day).values(fuel=True))
        db.session.execute(Payslip.__table__.delete())
        for as_of, expected in [(date(2026, 10, 9), "in_progress"),
                                (date(2026, 10, 10), "awaiting_records"),
                                (date(2026, 10, 16), "awaiting_records"),
                                (date(2026, 10, 19), "awaiting_records"),
                                (date(2026, 10, 20), "needs_review")]:
            with self.subTest(as_of=as_of):
                report = self.report(as_of=as_of)
                self.assertEqual(report["review_status"], expected)
                self.assertEqual(report["review_window_start"], date(2026, 10, 16))
                self.assertEqual(report["review_due_date"], date(2026, 10, 19))
                self.assertEqual(report["review_overdue"], as_of > date(2026, 10, 19))
                self.assertIsNone(report["estimated_operating_result"])
        self.assertEqual(OwnerWeekReview.query.count(), 0)

    def test_complete_finished_week_can_be_reviewed_before_normal_review_window(self):
        report = self.report(as_of=date(2026, 10, 10))
        self.assertEqual(report["review_status"], "not_reviewed")
        save_week_review(self.start, report["week_fingerprint"], as_of=date(2026, 10, 10))
        self.assertEqual(self.report(as_of=date(2026, 10, 10))["review_status"], "checked")

    def test_optional_explanation_after_signoff_keeps_financial_review_checked(self):
        db.session.execute(Day.__table__.update().where(Day.id == self.day)
                           .values(start_mileage=0))
        report = self.report()
        save_week_review(self.start, report["week_fingerprint"], as_of=self.as_of)
        fingerprint = self.report()["week_fingerprint"]
        issue = self.issue("missing_mileage")
        self.verify(issue, "dismissed", "Opening reading was unavailable; financial records checked")
        self.assertEqual(self.report()["review_status"], "checked")
        self.assertEqual(self.report()["week_fingerprint"], fingerprint)
        self.assertEqual(self.report()["optional_issues"], [])

    def test_legacy_signoff_with_optional_history_survives_later_optional_explanation(self):
        db.session.execute(Day.__table__.update().where(Day.id == self.day)
                           .values(start_mileage=0))
        issue = self.issue("missing_mileage")
        self.verify(issue, "verified", "Opening reading unavailable; source checked")
        report = self.report()
        # Simulate an already-saved signoff from the previous version, which
        # included optional decision history in its financial fingerprint.
        legacy_basis = [{name: row[name] for name in
                         ("id", "scope_key", "decision", "note", "source_fingerprint")}
                        for row in report["verification_history"]]
        legacy = dict(report, _verification_basis=legacy_basis)
        db.session.add(OwnerWeekReview(week_start=self.start,
            source_fingerprint=fingerprint_for_scope(legacy, "week"), note="Existing reviewed week"))
        db.session.flush()
        self.assertEqual(self.report()["review_status"], "checked")
        self.verify(self.issue("missing_mileage"), "dismissed", "Reading reviewed again; no cost changes")
        self.assertEqual(self.report()["review_status"], "checked")
        db.session.execute(Job.__table__.update().where(Job.id == self.job).values(earned=55000))
        self.assertEqual(self.report()["review_status"], "outdated",
                         "Legacy compatibility must still reopen for real source changes")
        db.session.execute(Job.__table__.update().where(Job.id == self.job).values(earned=50000))
        self.assertEqual(self.report()["review_status"], "checked")
        save_week_note(self.start, "New financial context after review",
                       self.report()["week_fingerprint"], as_of=self.as_of)
        self.assertEqual(self.report()["review_status"], "outdated")
        self.verify(self.issue("missing_mileage"), "verified", "Another optional-only note")
        self.assertEqual(self.report()["review_status"], "outdated",
                         "Optional compatibility cannot strip a newer essential/context action")

    def test_monthly_summary_distinguishes_awaiting_records_from_overdue_essential_checks(self):
        db.session.execute(Day.__table__.update().where(Day.id == self.day).values(fuel=True))
        # The only completed week in this view is within its normal review window.
        waiting = get_monthly_report(2026, 10, as_of=date(2026, 10, 10))
        self.assertEqual(waiting["review_status"], "awaiting_records")
        self.assertEqual(waiting["completed_week_count"], 1)
        self.assertEqual(len(waiting["outstanding_issues"]), 1)
        self.assertIsNone(waiting["estimated_operating_result"])
        overdue = get_monthly_report(2026, 10, as_of=date(2026, 10, 20))
        self.assertEqual(overdue["review_status"], "needs_review")
        self.assertTrue(overdue["outstanding_issues"])

    def test_duplicate_verification_reopens_when_candidate_group_membership_changes(self):
        self.add_fuel()
        self.add_fuel()
        issue = self.issue("possible_duplicate_fuel")
        self.verify(issue, "verified", "Two separate invoice lines checked")
        self.assertTrue(self.issue("possible_duplicate_fuel")["resolved"])
        self.add_fuel(fuel_card_name="Other company")
        self.assertTrue(self.issue("possible_duplicate_fuel")["resolved"])
        self.add_fuel()
        self.assertFalse(self.issue("possible_duplicate_fuel")["resolved"])
        with self.assertRaises(ValueError):
            self.verify(issue, "dismissed", "Old candidate list")

    def test_recorded_anomaly_can_be_dismissed_with_reason_and_reopens_on_relevant_edit(self):
        fuel = self.add_fuel(fuel_cost=1000)
        issue = self.issue("fuel_price_unusual")
        self.assertIn("dismissed", issue["verification_decisions"])
        with self.assertRaises(ValueError):
            self.verify(issue, "dismissed", "  ")
        self.verify(issue, "dismissed", "Invoice confirms discounted purchase")
        current = self.issue("fuel_price_unusual")
        self.assertTrue(current["resolved"])
        self.assertEqual(current["verification"]["decision"], "dismissed")
        db.session.execute(Job.__table__.update().where(Job.id == self.job).values(earned=55000))
        self.assertTrue(self.issue("fuel_price_unusual")["resolved"])
        db.session.execute(Fuel.__table__.update().where(Fuel.id == fuel).values(fuel_volume=9000))
        report = self.report()
        self.assertFalse(self.issue("fuel_price_unusual")["resolved"])
        history = next(row for row in report["verification_history"] if row["scope_key"] == issue["key"])
        self.assertEqual(history["status"], "outdated")
        self.assertEqual(history["note"], "Invoice confirms discounted purchase")

    def test_payroll_gap_verification_follows_the_payslip_not_unrelated_job_bonuses(self):
        db.session.execute(Payslip.__table__.update().where(Payslip.id == self.payslip)
                           .values(total_wage=6000, total_cost_to_employer=85000))
        issue = self.issue("payroll_gap_unusual")
        self.verify(issue, "verified", "Exceptional deduction confirmed with payroll")
        self.assertTrue(self.issue("payroll_gap_unusual")["resolved"])
        db.session.execute(Job.__table__.update().where(Job.id == self.job).values(earned=90000))
        self.assertTrue(self.issue("payroll_gap_unusual")["resolved"])
        db.session.execute(Payslip.__table__.update().where(Payslip.id == self.payslip)
                           .values(total_wage=6500))
        self.assertFalse(self.issue("payroll_gap_unusual")["resolved"])
        with self.assertRaises(ValueError):
            self.verify(issue, "dismissed", "This form refers to the old payroll figures")

    def test_awaiting_invoice_explains_missing_fuel_without_resolving_cost_or_signoff(self):
        db.session.execute(Day.__table__.update().where(Day.id == self.day).values(fuel=True))
        issue = self.issue("missing_fuel_receipt")
        self.assertNotIn("dismissed", issue["verification_decisions"])
        self.assertIn("awaiting_invoice", issue["verification_decisions"])
        with self.assertRaises(ValueError):
            self.verify(issue, "dismissed")
        with self.assertRaises(ValueError):
            self.verify(issue, "awaiting_invoice", "")
        self.verify(issue, "awaiting_invoice", "Company invoice is due next Monday")
        report = self.report()
        current = self.issue("missing_fuel_receipt")
        self.assertFalse(current["resolved"])
        self.assertTrue(current["awaiting_invoice"])
        self.assertIsNone(report["estimated_operating_result"])
        with self.assertRaises(ValueError):
            save_week_review(self.start, report["week_fingerprint"], as_of=self.as_of)
        self.add_fuel()
        report = self.report()
        history = next(row for row in report["verification_history"] if row["scope_key"] == issue["key"])
        self.assertEqual(history["status"], "resolved")
        self.assertEqual(history["note"], "Company invoice is due next Monday")
        self.assertIsNotNone(report["estimated_operating_result"])

    def test_missing_payroll_and_day_cannot_be_dismissed_as_known_records(self):
        db.session.execute(Payslip.__table__.delete())
        issue = self.issue("missing_payslip")
        self.assertEqual(issue["verification_decisions"], ["confirmed_zero"])
        with self.assertRaises(ValueError):
            self.verify(issue, "dismissed", "It will arrive")
        from haulage_app.models import DriverEmploymentHistory
        db.session.execute(DriverEmploymentHistory.__table__.insert(), dict(
            driver_id=1, start_date=date(2026, 10, 6), end_date=date(2026, 10, 7),
            employment_status="INACTIVE"))
        missing_day = self.issue("missing_day")
        self.assertNotIn("dismissed", missing_day["verification_decisions"])
        with self.assertRaises(ValueError):
            self.verify(missing_day, "dismissed")
        self.assertEqual(OwnerIssueVerification.query.count(), 0)

    def test_new_checks_and_monthly_reads_never_flush_unrelated_pending_source_edit(self):
        self.add_fuel(fuel_cost=1000)
        pending = db.session.get(Job, self.job)
        pending.notes = "An unsaved draft from another form"
        with patch.object(db.session, "flush", side_effect=AssertionError("Read attempted flush")):
            self.assertTrue(self.issue("fuel_price_unusual"))
            get_monthly_report(2026, 10, as_of=self.as_of)
            calculate_weekly_report(self.start, as_of=self.as_of)
        self.assertIn(pending, db.session.dirty)
        with db.session.no_autoflush:
            stored = db.session.execute(select(Job.notes).where(Job.id == self.job)).scalar_one()
        self.assertEqual(stored, "")
        self.assertEqual(pending.notes, "An unsaved draft from another form")
