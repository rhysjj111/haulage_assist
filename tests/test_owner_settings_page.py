"""Settings changes are explicit, dated, and separate from report browsing."""

from datetime import date
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import func, select, text

from owner_test_support import OwnerTestCase, app, db
from haulage_app.models import Job
from haulage_app.owner_analysis.models import OwnerOverheadSetting, OwnerWeeklyOverhead
from haulage_app.owner_analysis.overheads import ensure_weekly_overhead, get_weekly_overhead


class _Inputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.forms = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and "name" in attrs:
            self.values[attrs["name"]] = attrs.get("value", "")
        if tag == "form":
            self.forms.append(attrs)


def _links(html):
    return [urlsplit(unescape(link)) for link in re.findall(r'href="([^"]+)"', html)]


class OwnerSettingsPageTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.today = patch("haulage_app.owner_analysis.routes.today_london",
                           return_value=date(2026, 10, 18))
        self.today.start()
        self.addCleanup(self.today.stop)

    def form_payload(self, *, selected_week="2026-10-03", **overrides):
        _, context = self.get_page("/owner-analysis/overheads?week_start=" + selected_week)
        payload = {
            "selected_week": selected_week,
            "effective_week_start": "2026-10-17",
            "truck_count": "5",
            "allowance_per_truck": "600.00",
            "fingerprint": context["overhead_form"].fingerprint.data,
        }
        payload.update(overrides)
        return payload

    def test_initial_setup_defaults_to_current_week_without_guessing_allowance_or_writing(self):
        response, context = self.get_page("/owner-analysis/overheads?week_start=2026-10-03")
        form = context["overhead_form"]
        self.assertEqual(context["selected_week"], date(2026, 10, 3))
        self.assertEqual(context["current_week"], date(2026, 10, 17))
        self.assertIsNone(context["current_setting"])
        self.assertIsNone(context["selected_setting"])
        self.assertEqual(form.effective_week_start.data, date(2026, 10, 17))
        self.assertEqual(form.truck_count.data, 4)
        self.assertIsNone(form.allowance_per_truck.data)
        self.assertEqual(OwnerOverheadSetting.query.count(), 0)
        self.assertEqual(OwnerWeeklyOverhead.query.count(), 0)
        self.assertIn("Truck &amp; overhead settings", response.text)

    def test_historical_report_context_does_not_default_a_change_to_old_or_scheduled_settings(self):
        self.configure_overheads(date(2026, 9, 26), 3, 40000)
        self.configure_overheads(date(2026, 10, 10), 4, 50000)
        self.configure_overheads(date(2026, 10, 31), 6, 70000)
        _, context = self.get_page("/owner-analysis/overheads?week_start=2026-10-03")
        self.assertEqual(context["selected_setting"]["truck_count"], 3)
        self.assertEqual(context["current_setting"]["truck_count"], 4)
        form = context["overhead_form"]
        self.assertEqual(form.effective_week_start.data, date(2026, 10, 17))
        self.assertEqual(form.truck_count.data, 4)
        self.assertEqual(form.allowance_per_truck.data, Decimal("500.00"))
        self.assertEqual([(row["effective_week_start"], row["status"])
                          for row in context["settings_history"]], [
            (date(2026, 10, 31), "scheduled"),
            (date(2026, 10, 10), "current"),
            (date(2026, 9, 26), "previous"),
        ])
        self.assertEqual(OwnerWeeklyOverhead.query.count(), 0)

    def test_report_picker_normalizes_weekdays_but_rejects_invalid_context(self):
        _, context = self.get_page("/owner-analysis/overheads?week_start=2026-10-05")
        self.assertEqual(context["selected_week"], date(2026, 10, 3))
        for query in ("week_start=bad", "week_start=2026-02-30", "month=2026-1", "month=2026-13"):
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/owner-analysis/overheads?" + query).status_code, 400)

    def test_settings_get_including_shared_notifications_never_flushes_pending_source_edits(self):
        self.add_truck()
        self.add_driver()
        self.add_job(self.add_day())
        self.configure_overheads()
        job = db.session.get(Job, 1)
        job.notes = "Unsaved work must remain unsaved"
        with db.session.no_autoflush:
            before = {table.name: db.session.execute(select(func.count()).select_from(table)).scalar()
                      for table in db.metadata.sorted_tables}
        self.get_page("/owner-analysis/overheads?week_start=2026-10-03")
        self.assertIn(job, db.session.dirty)
        self.assertTrue(db.session.is_modified(job))
        with db.session.no_autoflush:
            self.assertEqual(db.session.execute(text("SELECT notes FROM job WHERE id = 1")).scalar(), "")
            after = {table.name: db.session.execute(select(func.count()).select_from(table)).scalar()
                     for table in db.metadata.sorted_tables}
        self.assertEqual(after, before)

    def test_successful_change_carries_forward_until_next_setting_without_touching_previous_weeks(self):
        self.configure_overheads(date(2026, 10, 3), 4, 50000)
        ensure_weekly_overhead(date(2026, 10, 10))
        self.configure_overheads(date(2026, 10, 31), 6, 70000)
        ensure_weekly_overhead(date(2026, 10, 31))
        db.session.commit()
        response = self.client.post("/owner-analysis/overheads", data=self.form_payload())
        self.assertEqual(response.status_code, 303)
        target = urlsplit(response.headers["Location"])
        self.assertEqual(target.path, "/owner-analysis/overheads")
        self.assertEqual(parse_qs(target.query)["week_start"], ["2026-10-03"])
        expected = [(date(2026, 10, 10), 200000), (date(2026, 10, 17), 300000),
                    (date(2026, 10, 24), 300000), (date(2026, 10, 31), 420000)]
        for week, total in expected:
            with self.subTest(week=week):
                self.assertEqual(get_weekly_overhead(week).total, total)
        self.assertEqual({row.week_start for row in OwnerWeeklyOverhead.query.all()},
                         {date(2026, 10, 10), date(2026, 10, 17), date(2026, 10, 31)})
        self.assertEqual(OwnerOverheadSetting.query.count(), 3)
        # Browsing subsequent weeks requires no repeated configuration or snapshots.
        self.get_page("/owner-analysis?week_start=2026-10-24")
        self.assertEqual(OwnerWeeklyOverhead.query.count(), 3)

    def test_monthly_return_context_survives_settings_form_and_successful_save(self):
        self.configure_overheads()
        response, _ = self.get_page("/owner-analysis/overheads?week_start=2026-10-03&month=2026-10")
        self.assertTrue(any(link.path == "/owner-analysis/monthly"
                            and parse_qs(link.query).get("month") == ["2026-10"]
                            and parse_qs(link.query).get("week_start") == ["2026-10-03"]
                            for link in _links(response.text)))
        action = next(form["action"] for form in _Inputs(response.text).forms
                      if form.get("method", "").lower() == "post")
        self.assertEqual(parse_qs(urlsplit(action).query).get("month"), ["2026-10"])
        response = self.client.post("/owner-analysis/overheads?month=2026-10", data=self.form_payload())
        self.assertEqual(response.status_code, 303)
        query = parse_qs(urlsplit(response.headers["Location"]).query)
        self.assertEqual(query.get("month"), ["2026-10"])
        self.assertEqual(query.get("week_start"), ["2026-10-03"])

    def test_rejected_values_stay_visible_without_changing_settings_or_snapshots(self):
        self.configure_overheads()
        invalid = [
            ("effective_week_start", "2026-10-19"), ("effective_week_start", "not-a-date"),
            ("truck_count", "-1"), ("truck_count", "4.5"), ("truck_count", "2147483648"),
            ("allowance_per_truck", "-0.01"), ("allowance_per_truck", "NaN"),
            ("allowance_per_truck", "Infinity"), ("allowance_per_truck", "600.001"),
            ("allowance_per_truck", "21474836.48"),
        ]
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                response = self.client.post("/owner-analysis/overheads",
                                            data=self.form_payload(**{field: value}))
                self.assertEqual(response.status_code, 400)
                inputs = _Inputs(response.text).values
                self.assertEqual(inputs[field], value)
                self.assertEqual(inputs["selected_week"], "2026-10-03")
                self.assertIn('role="alert"', response.text)
                self.assertRegex(response.text, r"<details\s+open(?:\s|>)")
                self.assertEqual(OwnerOverheadSetting.query.count(), 1)
                self.assertEqual(OwnerWeeklyOverhead.query.count(), 0)
                self.assertEqual(get_weekly_overhead(self.start).total, 200000)

    def test_zero_truck_count_and_zero_allowance_are_valid_explicit_changes(self):
        for count, allowance in (("0", "500.00"), ("4", "0.00")):
            with self.subTest(count=count, allowance=allowance):
                response = self.client.post("/owner-analysis/overheads", data=self.form_payload(
                    truck_count=count, allowance_per_truck=allowance))
                self.assertEqual(response.status_code, 303)
                self.assertEqual(get_weekly_overhead(date(2026, 10, 17)).total, 0)
        self.assertEqual(OwnerOverheadSetting.query.count(), 1)

    def test_future_setting_change_rejects_stale_form_and_keeps_attempted_values(self):
        self.configure_overheads()
        payload = self.form_payload()
        self.configure_overheads(date(2026, 10, 31), 6, 70000)
        response = self.client.post("/owner-analysis/overheads", data=payload)
        self.assertEqual(response.status_code, 409)
        self.assertIn("changed", response.text.lower())
        self.assertRegex(response.text, r"<details\s+open(?:\s|>)")
        self.assertTrue(any(link.path == "/owner-analysis/overheads"
                            and parse_qs(link.query).get("week_start") == ["2026-10-03"]
                            for link in _links(response.text)))
        self.assertEqual(_Inputs(response.text).values["allowance_per_truck"], "600.00")
        self.assertEqual(OwnerOverheadSetting.query.count(), 2)
        self.assertEqual(get_weekly_overhead(date(2026, 10, 17)).total, 200000)
        self.assertEqual(get_weekly_overhead(date(2026, 10, 31)).total, 420000)
        self.assertEqual(OwnerWeeklyOverhead.query.count(), 0)

    def test_settings_csrf_token_is_rendered_and_valid_token_allows_explicit_save(self):
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            response, _ = self.get_page("/owner-analysis/overheads?week_start=2026-10-03")
            token = _Inputs(response.text).values["csrf_token"]
            response = self.client.post("/owner-analysis/overheads", data=self.form_payload(csrf_token=token))
            self.assertEqual(response.status_code, 303)
            self.assertEqual(get_weekly_overhead(date(2026, 10, 17)).total, 300000)
        finally:
            app.config["WTF_CSRF_ENABLED"] = False

    def test_report_has_settings_link_instead_of_editable_controls_or_old_anchor(self):
        response, context = self.get_page("/owner-analysis?week_start=2026-10-03")
        self.assertNotIn("overhead_form", context)
        self.assertNotIn("truck_count", _Inputs(response.text).values)
        self.assertNotIn("allowance_per_truck", _Inputs(response.text).values)
        _, checks_context = self.get_page("/owner-analysis/checks?week_start=2026-10-03")
        issue = next(item for item in checks_context["report"]["outstanding_issues"]
                     if item["code"] == "missing_overhead_settings")
        target = urlsplit(issue["correction_url"])
        self.assertEqual(target.path, "/owner-analysis/overheads")
        self.assertEqual(parse_qs(target.query).get("week_start"), ["2026-10-03"])
        self.assertNotIn("#owner-overheads", response.text)
        self.assertTrue(any(link.path == "/owner-analysis/overheads" for link in _links(response.text)))
