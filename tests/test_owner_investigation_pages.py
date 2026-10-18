"""Bounded, read-only weekly evidence for Data Checks and correction forms."""

from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from sqlalchemy import event, func, select, text

from owner_test_support import OwnerTestCase, app, db
from haulage_app.models import Day, Job
from haulage_app.owner_analysis.navigation import review_context_for


class _ActionForms(HTMLParser):
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
        elif tag == "input" and self.current is not None and "name" in attrs:
            self.current["values"][attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


class OwnerInvestigationPageTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        clock = patch("haulage_app.owner_analysis.routes.today_london",
                      return_value=date(2026, 10, 18))
        clock.start()
        self.addCleanup(clock.stop)
        self.add_truck()
        self.add_truck(2)
        self.add_driver(first_name="Alice", employment_start=date(2026, 10, 5),
                        employment_end=date(2026, 10, 9))
        self.add_driver(2, first_name="Bob", employment_start=date(2026, 10, 5),
                        employment_end=date(2026, 10, 9), truck_id=2)
        self.monday = self.add_day(on_date=date(2026, 10, 5), additional_earned=1250)
        self.job = self.add_job(self.monday, earned=45000, collection="North depot", delivery="West port")
        self.add_day(on_date=date(2026, 10, 7), status="holiday", truck_id=None)
        self.add_day(on_date=date(2026, 10, 8), status="absent", truck_id=None)
        self.bob_day = self.add_day(driver_id=2, on_date=date(2026, 10, 5), truck_id=2)
        self.add_job(self.bob_day, earned=53000)
        self.bob_payslip = self.add_payslip(driver_id=2, total_wage=51000,
                                          total_cost_to_employer=57500)
        self.configure_overheads()

    def checks(self, suffix=""):
        return self.get_page("/owner-analysis/checks?week_start=2026-10-03" + suffix)[1]

    def issue(self, code, *, page=None, **fields):
        context = self.get_page(page)[1] if page else self.checks()
        reports = context.get("weeks", [context["report"]])
        return next(issue for report in reports if report["week_start"] == self.start
                    for issue in report["issues"] if issue["code"] == code
                    and all(issue.get(key) == value for key, value in fields.items()))

    def investigate(self, code="missing_payslip", **fields):
        selectors = {"driver_id": 1} if code == "missing_payslip" else {}
        selectors.update(fields)
        return self.issue(code, **selectors)["investigation_url"]

    def assert_destination(self, url, path, **expected):
        parsed = urlsplit(url)
        self.assertEqual(parsed.path, path)
        query = parse_qs(parsed.query)
        for key, value in expected.items():
            self.assertEqual(query.get(key), [str(value)])
        return parsed

    def test_each_check_links_to_the_exact_week_and_issue(self):
        response, context = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        for issue in context["report"]["outstanding_issues"]:
            with self.subTest(code=issue["code"], key=issue["key"]):
                target = self.assert_destination(issue["investigation_url"],
                    "/owner-analysis/checks/investigate", week_start="2026-10-03", issue_key=issue["key"])
                self.assertNotIn("driver_id", parse_qs(target.query))
                self.assertNotIn("truck_id", parse_qs(target.query))
                self.assertIn(unescape(issue["investigation_url"]), unescape(response.text))

    def test_missing_payslip_opens_driver_week_with_bound_review_action_and_no_record_editor(self):
        response, context = self.get_page(self.investigate())
        evidence = context["week_context"]
        self.assertEqual(evidence["scope"], "driver")
        self.assertEqual(evidence["driver_id"], 1)
        self.assertEqual([row["date"] for row in evidence["days"]],
                         [self.start + timedelta(days=offset) for offset in range(7)])
        self.assertEqual([row["id"] for row in evidence["payslips"]], [self.bob_payslip])
        self.assertTrue(evidence["driver_payslip_missing"])
        self.assertIn("Alice", response.text)
        self.assertIn("Bob", response.text)
        self.assertIn("Week at a glance", response.text)
        self.assertIn("Payslips for this week", response.text)
        forms = [form for form in _ActionForms(response.text).forms
                 if form.get("method", "").lower() == "post"]
        self.assertEqual([urlsplit(form["action"]).path for form in forms], ["/owner-analysis/verify"])
        action = forms[0]["values"]
        self.assertEqual(action["week_start"], "2026-10-03")
        self.assertEqual(action["issue_key"], context["issue"]["key"])
        self.assertEqual(action["fingerprint"], context["issue"]["fingerprint"])
        self.assertEqual(action["decision"], "confirmed_zero",
                         'The payroll action must explicitly confirm zero employer cost')
        self.assertNotIn('name="total_wage"', response.text)
        self.assertNotIn('name="total_cost_to_employer"', response.text)
        self.assertEqual(self.client.post(self.investigate()).status_code, 405)

    def test_investigation_missing_day_actions_bind_date_and_preserve_monthly_driver_return(self):
        page = "/owner-analysis/checks/monthly?month=2026-10&week_start=2026-10-10&view=drivers&driver_id=2"
        issue = self.issue("missing_day", page=page, driver_id=1, date=date(2026, 10, 6))
        response, context = self.get_page(issue["investigation_url"])
        forms = {urlsplit(form["action"]).path: form for form in _ActionForms(response.text).forms
                 if form.get("method", "").lower() == "post"}
        self.assertEqual(set(forms), {"/owner-analysis/absence"},
                         'A missing source day must be recorded, rather than explained away')
        absence = forms["/owner-analysis/absence"]
        payload = dict(absence["values"], status="holiday", note="Holiday checked with dispatch.")
        self.assertEqual(payload["driver_id"], "1")
        self.assertEqual(payload["absent_date"], "2026-10-06")
        self.assertEqual(payload["fingerprint"], issue["fingerprint"])
        self.assertTrue(payload["review_context"])
        self.assertNotIn('name="start_mileage"', response.text)
        saved = self.client.post(absence["action"], data=payload)
        self.assertEqual(saved.status_code, 303, saved.text)
        target = self.assert_destination(saved.location, "/owner-analysis/checks/monthly", month="2026-10",
            week_start="2026-10-10", view="drivers", driver_id=2)
        self.assertEqual(target.fragment, "week-2026-10-03")
        self.assertEqual(Day.query.filter_by(driver_id=1, date=date(2026, 10, 6)).one().status, "holiday")
        self.assertEqual(self.client.get(issue["investigation_url"]).status_code, 404)

    def test_rendered_payroll_verification_checks_stale_source_and_hides_completed_action(self):
        path = self.investigate()
        response, context = self.get_page(path)
        form = next(form for form in _ActionForms(response.text).forms
                    if urlsplit(form.get("action", "")).path == "/owner-analysis/verify")
        self.assertEqual(form["values"]["decision"], "confirmed_zero")
        payload = dict(form["values"], decision="confirmed_zero", note="Checked: no payroll cost due.")
        rejected = self.client.post(form["action"], data=dict(payload, fingerprint="0" * 64))
        self.assertEqual(rejected.status_code, 303)
        self.assertFalse(self.issue("missing_payslip", driver_id=1)["resolved"])
        saved = self.client.post(form["action"], data=payload)
        self.assertEqual(saved.status_code, 303, saved.text)
        response, context = self.get_page(path)
        self.assertTrue(context["issue"]["resolved"])
        self.assertIn("Checked: no payroll cost due.", response.text)
        self.assertFalse(any(form.get("method", "").lower() == "post"
                             for form in _ActionForms(response.text).forms))

    def test_missing_day_is_explicit_unknown_and_highlights_the_investigated_date(self):
        path = self.investigate("missing_day", driver_id=1, date=date(2026, 10, 6))
        response, context = self.get_page(path)
        days = {day["date"]: day for day in context["week_context"]["days"]}
        missing = days[date(2026, 10, 6)]
        self.assertEqual(missing["entries"], [])
        self.assertIsNone(missing["earnings"])
        self.assertTrue(missing["highlighted"])
        self.assertIn("No entry", response.text)
        self.assertRegex(response.text, r'class="[^"]*owner-context-day-highlighted[^"]*"[^>]*data-date="2026-10-06"|data-date="2026-10-06"[^>]*class="[^"]*owner-context-day-highlighted')
        self.assertEqual(days[date(2026, 10, 7)]["entries"][0]["status"], "holiday")
        self.assertEqual(days[date(2026, 10, 8)]["entries"][0]["status"], "absent")

    def test_recorded_jobs_and_additional_earnings_are_separate_and_escape_source_text(self):
        db.session.execute(text("UPDATE job SET notes = :note WHERE id = :id"),
                           {"note": "<script>unsafe()</script>", "id": self.job})
        db.session.commit()
        response, context = self.get_page(self.investigate())
        monday = next(day for day in context["week_context"]["days"] if day["date"] == date(2026, 10, 5))
        self.assertEqual(monday["job_earnings"], 45000)
        self.assertEqual(monday["additional_earned"], 1250)
        self.assertEqual(monday["earnings"], 46250)
        self.assertEqual(monday["entries"][0]["jobs"][0]["id"], self.job)
        self.assertIn("North depot", response.text)
        self.assertIn("West port", response.text)
        self.assertNotIn("<script>unsafe()</script>", response.text)
        self.assertNotIn("£530.00", response.text, "Another driver's earnings must not enter Alice's daily context")

    def test_all_week_payslips_include_duplicates_without_silently_dropping_rows(self):
        self.add_payslip(driver_id=1, id=20, total_wage=49000, total_cost_to_employer=54000)
        self.add_payslip(driver_id=1, id=21, total_wage=49500, total_cost_to_employer=54500)
        response, context = self.get_page(self.investigate("multiple_payslips", driver_id=1))
        slips = context["week_context"]["payslips"]
        self.assertEqual({row["id"] for row in slips}, {self.bob_payslip, 20, 21})
        self.assertEqual({row["id"] for row in slips if row["highlighted"]}, {20, 21})
        self.assertFalse(context["week_context"]["driver_payslip_missing"])
        self.assertIn("£540.00", response.text)
        self.assertIn("£545.00", response.text)

    def test_nearby_payslips_are_opt_in_and_bounded_to_selected_driver_adjacent_weeks(self):
        prior = self.add_payslip(driver_id=1, on_date=date(2026, 10, 2))
        following = self.add_payslip(driver_id=1, on_date=date(2026, 10, 16))
        self.add_payslip(driver_id=1, on_date=date(2026, 9, 25))
        self.add_payslip(driver_id=1, on_date=date(2026, 10, 23))
        self.add_payslip(driver_id=2, on_date=date(2026, 10, 2))
        path = self.investigate()
        response, context = self.get_page(path)
        self.assertFalse(context["week_context"]["nearby_payslips"])
        self.assertIn("Show this driver", response.text)
        response, context = self.get_page(path + "&nearby=1")
        self.assertEqual({row["id"] for row in context["week_context"]["nearby_payslips"]},
                         {prior, following})
        self.assertIn("Nearby payslips", response.text)

    def test_default_page_does_not_issue_adjacent_week_payslip_queries(self):
        path = self.investigate()
        statements = []

        def capture(connection, cursor, statement, parameters, *unused):
            if statement.lstrip().lower().startswith("select") and "payslip" in statement.lower():
                statements.append((statement.lower(), parameters))

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            self.get_page(path)
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)
        self.assertTrue(statements)
        for statement, parameters in statements:
            serialized = str(parameters)
            self.assertNotIn("2026-09-26", serialized, statement)
            self.assertNotIn("2026-10-16", serialized, statement)

    def test_fuel_check_uses_truck_records_without_attributing_driver_earnings(self):
        db.session.execute(Day.__table__.update().where(Day.id == self.monday).values(fuel=True))
        db.session.commit()
        response, context = self.get_page(self.investigate("missing_fuel_receipt", truck_id=1))
        evidence = context["week_context"]
        self.assertEqual((evidence["scope"], evidence["truck_id"]), ("truck", 1))
        self.assertIsNone(evidence["driver_id"])
        self.assertIsNone(evidence["summary"]["earnings"])
        self.assertTrue(all(day["earnings"] is None for day in evidence["days"]))
        recorded = [entry for day in evidence["days"] for entry in day["entries"]]
        self.assertTrue(recorded)
        self.assertTrue(all(entry["truck_id"] == 1 for entry in recorded))
        self.assertNotIn("£450.00", response.text)

    def test_missing_overheads_still_has_generic_week_context_and_settings_link(self):
        db.session.execute(text("DELETE FROM owner_overhead_setting"))
        db.session.commit()
        response, context = self.get_page(self.investigate("missing_overhead_settings"))
        self.assertEqual(context["week_context"]["scope"], "week")
        self.assertEqual(len(context["week_context"]["days"]), 7)
        self.assertIn("/owner-analysis/overheads?", unescape(response.text))

    def test_monthly_driver_return_context_is_preserved_by_investigation_and_correction(self):
        page = "/owner-analysis/checks/monthly?month=2026-10&week_start=2026-10-10&view=drivers&driver_id=2"
        issue = self.issue("missing_payslip", page=page, driver_id=1)
        response, context = self.get_page(issue["investigation_url"])
        target = self.assert_destination(context["back_url"], "/owner-analysis/checks/monthly",
            month="2026-10", week_start="2026-10-10", view="drivers", driver_id=2)
        self.assertEqual(target.fragment, "week-2026-10-03")
        # Investigation belongs to Alice even when reached from Bob's analysis filter.
        self.assertEqual(context["week_context"]["driver_id"], 1)
        _, correction = self.get_page(issue["correction_url"])
        self.assertEqual(correction["week_context"]["driver_id"], 1)
        self.assertEqual(correction["back_url"], context["back_url"])
        self.assertIn("Back to Data Checks", response.text)

    def test_weekday_input_normalizes_to_the_issue_payroll_week(self):
        parsed = urlsplit(self.investigate())
        values = parse_qs(parsed.query)
        values["week_start"] = ["2026-10-05"]
        _, context = self.get_page(parsed.path + "?" + urlencode(values, doseq=True))
        self.assertEqual(context["week_context"]["week_start"], self.start)

    def test_invalid_date_missing_key_and_no_longer_existing_issue_are_rejected(self):
        path = "/owner-analysis/checks/investigate"
        issue = self.issue("missing_payslip", driver_id=1)
        for value in ("bad", "2026-1-03", "2026-02-30", "0000-01-01"):
            with self.subTest(value=value):
                self.assertEqual(self.client.get(path, query_string={"week_start": value,
                    "issue_key": issue["key"]}).status_code, 400)
        self.assertEqual(self.client.get(path, query_string={"week_start": "2026-10-03"}).status_code, 400)
        for key in ("not-an-issue", issue["key"].replace("driver_id=1", "driver_id=999")):
            self.assertEqual(self.client.get(path, query_string={"week_start": "2026-10-03", "issue_key": key}).status_code, 404)
        old_link = issue["investigation_url"]
        self.add_payslip(driver_id=1)
        self.assertEqual(self.client.get(old_link).status_code, 404)

    def test_query_scope_cannot_be_substituted_or_duplicated(self):
        path = self.investigate()
        key = self.issue("missing_payslip", driver_id=1)["key"]
        for suffix in ("driver_id=2", "truck_id=2", "nearby=yes", "nearby=-1", "nearby=01",
                       "nearby=1&nearby=0", "week_start=2026-10-03", "issue_key=" + key,
                       "review_context=bad&review_context=bad"):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.client.get(path + "&" + suffix).status_code, 400)

    def test_invalid_or_out_of_scope_signed_navigation_is_rejected(self):
        issue = self.issue("missing_payslip", driver_id=1)
        base = "/owner-analysis/checks/investigate?" + urlencode({
            "week_start": "2026-10-03", "issue_key": issue["key"]})
        with app.test_request_context():
            other_week = review_context_for("weekly", date(2026, 10, 10))
            other_month = review_context_for("monthly", date(2026, 9, 26), month="2026-09")
        for token in ("tampered", other_week, other_month):
            with self.subTest(token=token[:10]):
                self.assertEqual(self.client.get(base + "&" + urlencode({"review_context": token})).status_code, 400)

    def test_investigation_and_correction_context_get_never_flush_pending_source_edits(self):
        issue = self.issue("missing_payslip", driver_id=1)
        pending = db.session.get(Job, self.job)
        for path in (issue["investigation_url"], issue["correction_url"]):
            pending.notes = "Pending source note " + path
            with db.session.no_autoflush:
                before = {table.name: db.session.execute(select(func.count()).select_from(table)).scalar()
                          for table in db.metadata.sorted_tables}
            self.get_page(path)
            self.assertIn(pending, db.session.dirty)
            with db.session.no_autoflush:
                self.assertEqual(db.session.execute(text("SELECT notes FROM job WHERE id=:id"),
                    {"id": self.job}).scalar(), "")
                self.assertEqual({table.name: db.session.execute(select(func.count()).select_from(table)).scalar()
                                  for table in db.metadata.sorted_tables}, before)

    def test_correction_form_context_does_not_expand_stale_record_scope_to_other_drivers(self):
        # Bob is contextual evidence only; changing his payslip must not stale Alice's add form.
        issue = self.issue("missing_payslip", driver_id=1)
        path = issue["correction_url"]
        _, context = self.get_page(path)
        self.assertEqual({row["id"] for row in context["week_context"]["payslips"]}, {self.bob_payslip})
        db.session.execute(text("UPDATE payslip SET total_wage = total_wage + 100 WHERE id=:id"),
                           {"id": self.bob_payslip})
        db.session.commit()
        response = self.client.post(path, data={"date": context["values"]["date"], "driver_id": "1",
            "total_wage": "550.00", "total_cost_to_employer": "625.00"})
        self.assertEqual(response.status_code, 303, response.text)
        self.assert_destination(response.location, "/owner-analysis/checks", week_start="2026-10-03")
        issue_after = self.checks()["report"]["issues"]
        self.assertFalse(any(item["code"] == "missing_payslip" and item.get("driver_id") == 1 for item in issue_after))

    def test_exact_day_job_and_fuel_corrections_get_the_appropriate_week_context(self):
        self.add_job(self.monday, earned=0)
        db.session.execute(Day.__table__.update().where(Day.id == self.monday).values(fuel=True))
        db.session.commit()
        checks = self.checks()["report"]["issues"]
        for code, scope, subject in (("missing_day", "driver", 1),
                                     ("job_amount_out_of_range", "driver", 1),
                                     ("missing_fuel_receipt", "truck", 1)):
            with self.subTest(code=code):
                issue = next(item for item in checks if item["code"] == code
                             and item.get("driver_id", 1) == 1)
                _, context = self.get_page(issue["correction_url"])
                evidence = context["week_context"]
                self.assertEqual(evidence["scope"], scope)
                self.assertEqual(evidence["driver_id" if scope == "driver" else "truck_id"], subject)
                self.assertEqual(evidence["on_date"], issue["date"])
                self.assertEqual(len(evidence["days"]), 7)
                self.assertEqual({row["id"] for row in evidence["payslips"]}, {self.bob_payslip})

    def test_correction_nearby_switch_preserves_signed_target_and_invalid_switch_cannot_write(self):
        prior = self.add_payslip(driver_id=1, on_date=date(2026, 10, 2))
        issue = self.issue("missing_payslip", driver_id=1)
        _, normal = self.get_page(issue["correction_url"])
        _, expanded = self.get_page(normal["nearby_url"])
        self.assertFalse(normal["week_context"]["nearby_loaded"])
        self.assertTrue(expanded["week_context"]["nearby_loaded"])
        self.assertEqual([row["id"] for row in expanded["week_context"]["nearby_payslips"]], [prior])
        self.assertEqual(parse_qs(urlsplit(normal["action"]).query)["owner_context"],
                         parse_qs(urlsplit(expanded["action"]).query)["owner_context"])
        self.assertEqual(parse_qs(urlsplit(expanded["action"]).query)["nearby"], ["1"])
        before = db.session.execute(text("SELECT count(*) FROM payslip")).scalar()
        response = self.client.post(issue["correction_url"] + "&nearby=yes", data={
            "date": normal["values"]["date"], "driver_id": "1", "total_wage": "550.00",
            "total_cost_to_employer": "625.00"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(db.session.execute(text("SELECT count(*) FROM payslip")).scalar(), before)

