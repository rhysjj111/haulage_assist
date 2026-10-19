"""Checks stay separate from owner figures and preserve safe return navigation."""

from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import func, select, text

from owner_test_support import OwnerTestCase, db
from test_owner_unified_review import _ReviewHTML
from haulage_app.models import Job
from haulage_app.owner_analysis.models import OwnerIssueVerification, OwnerWeekReview
from haulage_app.owner_analysis.reviews import save_issue_verification


class _Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = dict(attrs, values={})
            self.forms.append(self.current)
        if tag == "input" and self.current is not None and "name" in attrs:
            self.current["values"][attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


def _links(html):
    return [urlsplit(unescape(link)) for link in re.findall(r'href="([^"]+)"', html)]


class OwnerDataChecksTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        clock = patch("haulage_app.owner_analysis.routes.today_london",
                      return_value=date(2026, 10, 18))
        clock.start()
        self.addCleanup(clock.stop)

    def seed_week(self):
        self.add_truck()
        self.add_driver(first_name="Alice", employment_start=date(2026, 10, 5),
                        employment_end=date(2026, 10, 9))
        for offset in range(5):
            self.add_job(self.add_day(on_date=date(2026, 10, 5) + timedelta(days=offset)))
        self.add_fuel()
        self.add_payslip()
        self.configure_overheads()

    def note_payload(self, page="/owner-analysis/checks?week_start=2026-10-03", *, week="2026-10-03"):
        _, context = self.get_page(page)
        report = next(item for item in context["weeks"] if item["week_start"].isoformat() == week)
        form = report["forms"]["note"]
        return {"week_start": week, "scope_key": "week_note", "note": "Dispatch checked.",
                "fingerprint": form.fingerprint.data, "review_context": form.review_context.data}

    def assert_target(self, response, path, **expected):
        self.assertEqual(response.status_code, 303)
        target = urlsplit(response.headers["Location"])
        self.assertEqual(target.path, path)
        query = parse_qs(target.query)
        for key, value in expected.items():
            self.assertEqual(query.get(key), [str(value)])
        self.assertNotIn("review_context", query)
        return target

    def test_default_checks_opens_latest_finished_week_not_current_week(self):
        response, context = self.get_page("/owner-analysis/checks")
        self.assertEqual(context["report"]["week_start"], date(2026, 10, 10))
        self.assertIn("Data Checks", response.text)
        self.assertEqual(len(context["weeks"]), 1)

    def test_week_picker_normalizes_weekday_and_rejects_invalid_dates(self):
        _, context = self.get_page("/owner-analysis/checks?week_start=2026-10-05")
        self.assertEqual(context["report"]["week_start"], date(2026, 10, 3))
        for value in ("bad", "2026-1-03", "2026-02-30", "0000-01-01"):
            with self.subTest(value=value):
                self.assertEqual(self.client.get("/owner-analysis/checks", query_string={"week_start": value}).status_code, 400)

    def test_completed_month_groups_all_five_payroll_weeks_with_week_specific_forms(self):
        response, context = self.get_page("/owner-analysis/checks/monthly?month=2026-03")
        self.assertEqual([week["week_start"] for week in context["weeks"]], [
            date(2026, 2, 28), date(2026, 3, 7), date(2026, 3, 14),
            date(2026, 3, 21), date(2026, 3, 28)])
        for week in context["weeks"]:
            self.assertEqual(week["forms"]["note"].week_start.data, week["week_start"].isoformat())
            self.assertEqual(week["forms"]["review"].fingerprint.data, week["week_fingerprint"])
        self.assertIn("Mark as checked", response.text)

    def test_partial_month_only_contains_finished_weeks_and_matching_issue_count(self):
        response, checks = self.get_page("/owner-analysis/checks/monthly?month=2026-10")
        _, analysis = self.get_page("/owner-analysis/monthly?month=2026-10")
        self.assertEqual([week["week_start"] for week in checks["weeks"]],
                         [date(2026, 10, 3), date(2026, 10, 10)])
        self.assertEqual(sum(len(week["outstanding_issues"]) for week in checks["weeks"]),
                         sum(len(week["outstanding_issues"]) for week in analysis["report"]["weeks"]))
        for form in _Forms(response.text).forms:
            if form.get("method", "").lower() == "post":
                self.assertNotIn(form["values"].get("week_start"), ("2026-10-17", "2026-10-24"))

    def test_future_month_has_no_check_forms_or_false_reviewed_state(self):
        response, context = self.get_page("/owner-analysis/checks/monthly?month=2099-02")
        self.assertEqual(context["weeks"], [])
        self.assertNotEqual(context["report"]["review_status"], "checked")
        self.assertNotRegex(response.text, r'<form\b[^>]*method=["\']post["\']')
        self.assertIn("No completed payroll weeks", response.text)

    def test_invalid_month_and_invalid_filter_context_are_rejected(self):
        for suffix in ("month=bad", "month=2026-1", "month=2026-13", "month=0000-01"):
            self.assertEqual(self.client.get("/owner-analysis/checks/monthly?" + suffix).status_code, 400)
        for path in ("/owner-analysis/checks?week_start=2026-10-03&",
                     "/owner-analysis/checks/monthly?month=2026-10&"):
            for suffix in ("view=unknown", "view=drivers&driver_id=01", "view=drivers&driver_id=2147483648",
                           "view=trucks&driver_id=1", "view=drivers&driver_id=1&driver_id=2"):
                with self.subTest(path=path, suffix=suffix):
                    self.assertEqual(self.client.get(path + suffix).status_code, 400)

    def test_analysis_all_views_only_link_to_checks_and_expose_no_mutation_forms_or_issue_history(self):
        self.seed_week()
        for base in ("/owner-analysis?week_start=2026-10-03",
                     "/owner-analysis/monthly?month=2026-10&week_start=2026-10-03"):
            for suffix in ("", "&view=drivers&driver_id=1", "&view=trucks&truck_id=1"):
                with self.subTest(base=base, suffix=suffix):
                    response, context = self.get_page(base + suffix)
                    self.assertNotRegex(response.text, r'<form\b[^>]*method=["\']post["\']')
                    for label in ("Explain or verify this check", "Mark as checked",
                                  "Explanations and verification history", "Review check", "Record Holiday or Absent"):
                        self.assertNotIn(label, response.text)
                    self.assertNotIn("owner_context=", response.text)
                    self.assertIn("View checks", response.text)
                    query = parse_qs(urlsplit(context["checks_url"]).query)
                    if suffix:
                        self.assertEqual(query["view"], ["drivers" if "drivers" in suffix else "trucks"])
                        self.assertEqual(query["driver_id" if "drivers" in suffix else "truck_id"], ["1"])

    def test_analysis_overview_uses_estimated_profit_label_and_explains_missing_payroll(self):
        self.seed_week()
        db.session.execute(text("DELETE FROM payslip"))
        db.session.commit()
        for path in ("/owner-analysis?week_start=2026-10-03",
                     "/owner-analysis/monthly?month=2026-10"):
            response, context = self.get_page(path)
            self.assertIn("Estimated profit", response.text)
            self.assertNotIn("Estimated operating result", response.text)
            self.assertIsNone(context["report"]["estimated_operating_result"])
            self.assertRegex(response.text.lower(), r"profit pending[^<]*(?:payroll|financial|incomplete)")

    def test_zero_outstanding_still_requires_explicit_week_review_and_source_edits_reopen_it(self):
        self.seed_week()
        response, context = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        report = context["report"]
        self.assertEqual(report["outstanding_issues"], [])
        self.assertEqual(report["review_status"], "not_reviewed")
        self.assertIn("Mark as checked", response.text)
        form = context["weeks"][0]["forms"]["review"]
        payload = {"week_start": "2026-10-03", "fingerprint": form.fingerprint.data,
                   "review_context": form.review_context.data,
                   "review_id": form.review_id.data, "action": form.action.data}
        response = self.client.post("/owner-analysis/review", data=payload)
        self.assert_target(response, "/owner-analysis/checks", week_start="2026-10-03")
        _, context = self.get_page("/owner-analysis?week_start=2026-10-03")
        self.assertEqual(context["report"]["review_status"], "checked")
        db.session.execute(text("UPDATE job SET earned = earned + 100 WHERE id = 1"))
        db.session.commit()
        _, context = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        self.assertEqual(context["report"]["review_status"], "outdated")
        self.assertEqual(OwnerWeekReview.query.count(), 1)

    def test_analysis_keeps_independent_business_notes_escaped_without_verification_history(self):
        self.seed_week()
        for note in ("Truck service Monday.", "Alice off <script>unsafe()</script>"):
            payload = self.note_payload()
            payload["note"] = note
            self.assertEqual(self.client.post("/owner-analysis/note", data=payload).status_code, 303)
        for path in ("/owner-analysis?week_start=2026-10-03",
                     "/owner-analysis/monthly?month=2026-10"):
            response, _ = self.get_page(path)
            self.assertIn("Alice off &lt;script&gt;", response.text)
            self.assertNotIn("<script>unsafe()</script>", response.text)
            self.assertIn("Truck service Monday.", response.text)
            self.assertNotIn("Explanations and verification history", response.text)
        response, _ = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        self.assertIn("Truck service Monday.", response.text)

    def test_monthly_note_returns_to_selected_month_driver_and_week(self):
        self.seed_week()
        page = "/owner-analysis/checks/monthly?month=2026-10&week_start=2026-10-03&view=drivers&driver_id=1"
        response, _ = self.get_page(page)
        self.assertTrue(any(link.path == "/owner-analysis/monthly"
                            and parse_qs(link.query).get("month") == ["2026-10"]
                            and parse_qs(link.query).get("week_start") == ["2026-10-03"]
                            and parse_qs(link.query).get("driver_id") == ["1"]
                            for link in _links(response.text)))
        response = self.client.post("/owner-analysis/note", data=self.note_payload(page))
        target = self.assert_target(response, "/owner-analysis/checks/monthly", month="2026-10",
                                   week_start="2026-10-03", view="drivers", driver_id="1")
        self.assertTrue(target.fragment, "Return to the selected payroll week after saving")

    def test_weekly_note_preserves_truck_context_and_legacy_post_falls_back_to_weekly_checks(self):
        self.seed_week()
        payload = self.note_payload("/owner-analysis/checks?week_start=2026-10-03&view=trucks&truck_id=1")
        response = self.client.post("/owner-analysis/note", data=payload)
        self.assert_target(response, "/owner-analysis/checks", week_start="2026-10-03", view="trucks", truck_id="1")
        payload = self.note_payload()
        payload.pop("review_context")
        response = self.client.post("/owner-analysis/note", data=payload)
        self.assert_target(response, "/owner-analysis/checks", week_start="2026-10-03")

    def test_monthly_absence_verification_and_review_all_return_to_same_checklist(self):
        self.add_truck()
        self.add_driver(employment_start=date(2026, 10, 5), employment_end=date(2026, 10, 6))
        self.add_day(on_date=date(2026, 10, 6), status="absent", truck_id=None)
        self.configure_overheads()
        page = "/owner-analysis/checks/monthly?month=2026-10&week_start=2026-10-03&view=drivers&driver_id=1"

        def selected_week():
            _, context = self.get_page(page)
            return context["weeks"][0]

        report = selected_week()
        issue = next(issue for issue in report["outstanding_issues"] if issue["code"] == "missing_day")
        response = self.client.post("/owner-analysis/absence", data={
            "week_start": "2026-10-03", "fingerprint": issue["fingerprint"], "driver_id": "1",
            "absent_date": "2026-10-05", "status": "absent", "note": "Unpaid leave confirmed.",
            "review_context": report["forms"]["absence"].review_context.data})
        self.assert_target(response, "/owner-analysis/checks/monthly", month="2026-10",
                           week_start="2026-10-03", view="drivers", driver_id="1")
        report = selected_week()
        issue = next(issue for issue in report["outstanding_issues"] if issue["code"] == "missing_payslip")
        response = self.client.post("/owner-analysis/verify", data={
            "week_start": "2026-10-03", "issue_key": issue["key"], "fingerprint": issue["fingerprint"],
            "decision": "confirmed_zero", "note": "Unpaid leave; no employer wage cost.",
            "review_context": report["forms"]["verification"].review_context.data})
        self.assert_target(response, "/owner-analysis/checks/monthly", month="2026-10",
                           week_start="2026-10-03", view="drivers", driver_id="1")
        report = selected_week()
        self.assertEqual(report["outstanding_issues"], [])
        response = self.client.post("/owner-analysis/review", data={
            "week_start": "2026-10-03", "fingerprint": report["forms"]["review"].fingerprint.data,
            "review_id": report["forms"]["review"].review_id.data,
            "action": report["forms"]["review"].action.data,
            "review_context": report["forms"]["review"].review_context.data})
        self.assert_target(response, "/owner-analysis/checks/monthly", month="2026-10",
                           week_start="2026-10-03", view="drivers", driver_id="1")
        self.assertEqual(selected_week()["review_status"], "checked")

    def test_tampered_navigation_is_rejected_before_any_note_write(self):
        self.seed_week()
        payload = self.note_payload()
        token = payload["review_context"]
        self.assertTrue(token)
        payload["review_context"] = token + "invalid"
        response = self.client.post("/owner-analysis/note", data=payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(OwnerIssueVerification.query.count(), 0)

    def test_monthly_navigation_cannot_be_used_to_mutate_unfinished_or_unrelated_week(self):
        self.seed_week()
        page = "/owner-analysis/checks/monthly?month=2026-10&week_start=2026-10-03"
        for changed_week in ("2026-10-17", "2026-09-26"):
            with self.subTest(week=changed_week):
                payload = self.note_payload(page)
                payload["week_start"] = changed_week
                response = self.client.post("/owner-analysis/note", data=payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(OwnerIssueVerification.query.count(), 0)

    def test_checks_get_and_shared_notification_rendering_never_autoflush_source_edits(self):
        self.seed_week()
        job = db.session.get(Job, 1)
        for path in ("/owner-analysis/checks?week_start=2026-10-03",
                     "/owner-analysis/checks/monthly?month=2026-10"):
            with self.subTest(path=path):
                job.notes = "Pending unsaved change " + path
                with db.session.no_autoflush:
                    before = {table.name: db.session.execute(select(func.count()).select_from(table)).scalar()
                              for table in db.metadata.sorted_tables}
                self.get_page(path)
                self.assertIn(job, db.session.dirty)
                with db.session.no_autoflush:
                    self.assertEqual(db.session.execute(text("SELECT notes FROM job WHERE id=1")).scalar(), "")
                    self.assertEqual({table.name: db.session.execute(select(func.count()).select_from(table)).scalar()
                                      for table in db.metadata.sorted_tables}, before)

    def test_in_progress_and_future_week_do_not_offer_final_review(self):
        for week in ("2026-10-17", "2099-01-03"):
            response, context = self.get_page("/owner-analysis/checks?week_start=" + week)
            self.assertNotEqual(context["report"]["review_status"], "checked")
            self.assertFalse(any(urlsplit(form.get("action", "")).path == "/owner-analysis/review"
                                 for form in _Forms(response.text).forms))

    def test_driver_filter_preserves_whole_week_checks_for_other_drivers(self):
        self.seed_week()
        self.add_driver(2, first_name="Bob", employment_start=date(2026, 10, 5),
                        employment_end=date(2026, 10, 9))
        _, overview = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        response, filtered = self.get_page("/owner-analysis/checks?week_start=2026-10-03&view=drivers&driver_id=1")
        self.assertEqual([issue["key"] for issue in overview["report"]["outstanding_issues"]],
                         [issue["key"] for issue in filtered["report"]["outstanding_issues"]])
        self.assertIn("Bob", response.text)

    def test_check_summary_is_title_only_and_rows_keep_subject_check_and_waiting_status(self):
        self.seed_week()
        db.session.execute(text("DELETE FROM payslip"))
        db.session.execute(text("UPDATE day SET fuel = 1 WHERE date = '2026-10-06'"))
        db.session.commit()
        _, context = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        issue = next(row for row in context["report"]["issues"] if row["code"] == "missing_fuel_receipt")
        save_issue_verification(self.start, issue["key"], "Provider invoice expected Friday",
                                issue["fingerprint"], decision="awaiting_invoice", as_of=date(2026, 10, 18))
        db.session.commit()
        for page in ("/owner-analysis/checks?week_start=2026-10-03",
                     "/owner-analysis/checks/monthly?month=2026-10"):
            with self.subTest(page=page):
                response, context = self.get_page(page)
                summary = re.search(r'<section\b[^>]*aria-label="Checks summary"[^>]*>(.*?)</section>',
                                    response.text, re.S).group(1)
                count = sum(len(week["outstanding_issues"]) for week in context["weeks"])
                self.assertIn(f"{count} checks outstanding", summary)
                self.assertNotRegex(summary, r"<(?:p|form)\b")
                self.assertNotIn("owner-badge", summary)
                parsed = _ReviewHTML(response.text)
                rows = {row["key"]: row for row in parsed.checks}
                report = next(week for week in context["weeks"] if week["week_start"] == self.start)
                for current in report["outstanding_issues"]:
                    row = rows[current["key"]]
                    self.assertEqual(row["tag"], "tr")
                    self.assertIn(current["short_subject"], row["text"])
                    self.assertIn(current["check_label"], row["text"])
                    self.assertNotIn(current["message"], row["text"])
                    self.assertNotIn("Needs attention", row["text"])
                    self.assertNotIn("To review", row["text"])
                    self.assertEqual(len(row["links"]), 1)
                    if current.get("date"):
                        self.assertIn(current["date"].strftime("%A"), row["text"])
                        self.assertNotIn(current["date"].strftime("%d %b"), row["text"])
                waiting = rows[issue["key"]]
                self.assertIn("Awaiting invoice", waiting["text"])
                self.assertNotIn("Provider invoice expected Friday", waiting["text"],
                                 "The review page keeps explanations; the list stays compact")

    def test_separate_receipt_checks_for_same_truck_and_day_have_distinct_references(self):
        self.seed_week()
        ids = [self.add_fuel(fuel_cost=amount) for amount in (1000, 2000)]
        response, context = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        issues = [issue for issue in context["report"]["outstanding_issues"]
                  if issue["code"] == "fuel_price_unusual"]
        self.assertCountEqual([issue["record_id"] for issue in issues], ids)
        rows = {row["key"]: row for row in _ReviewHTML(response.text).checks}
        for issue in issues:
            row = rows[issue["key"]]
            self.assertIn(f"Receipt #{issue['record_id']}", row["text"])
            self.assertIn("Monday", row["text"])
            self.assertEqual(len(row["links"]), 1)
            self.assertEqual(row["links"][0]["href"], issue["review_url"])

    def test_missing_overheads_link_and_settings_form_preserve_monthly_return_to_checks(self):
        self.add_truck()
        self.add_driver(employment_start=date(2026, 10, 5), employment_end=date(2026, 10, 9))
        page = "/owner-analysis/checks/monthly?month=2026-10&week_start=2026-10-03&view=drivers&driver_id=1"
        _, context = self.get_page(page)
        issue = next(issue for issue in context["weeks"][0]["outstanding_issues"]
                     if issue["code"] == "missing_overhead_settings")
        target = urlsplit(issue["correction_url"])
        self.assertEqual(target.path, "/owner-analysis/overheads")
        self.assertTrue(parse_qs(target.query).get("review_context"))
        response, settings = self.get_page(issue["correction_url"])
        back = urlsplit(settings["back_url"])
        self.assertEqual(back.path, "/owner-analysis/checks/monthly")
        self.assertEqual(parse_qs(back.query).get("driver_id"), ["1"])
        self.assertIn("Back to", response.text)
        form = settings["overhead_form"]
        response = self.client.post("/owner-analysis/overheads", data={
            "selected_week": "2026-10-03", "effective_week_start": "2026-10-03",
            "truck_count": "4", "allowance_per_truck": "500.00",
            "fingerprint": form.fingerprint.data, "review_context": form.review_context.data})
        self.assertEqual(response.status_code, 303)
        _, saved = self.get_page(response.headers["Location"])
        self.assertEqual(urlsplit(saved["back_url"]).path, "/owner-analysis/checks/monthly")
        self.assertEqual(parse_qs(urlsplit(saved["back_url"]).query).get("month"), ["2026-10"])

