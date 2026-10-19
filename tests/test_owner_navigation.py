"""Only signed, canonical report choices may control a correction's return."""

from datetime import date
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from owner_test_support import app
from haulage_app.owner_analysis.navigation import (
    _serializer, analysis_url, checks_url, read_review_context, review_context_for,
)


class OwnerNavigationTests(TestCase):
    def setUp(self):
        self.context = app.test_request_context()
        self.context.push()
        self.week = date(2026, 10, 3)

    def tearDown(self):
        self.context.pop()

    def test_weekly_checks_and_analysis_preserve_driver_filter(self):
        token = review_context_for('weekly', self.week, view='drivers', selected_id=12)
        self.assertEqual(read_review_context(token, week=self.week), {
            'period': 'weekly', 'week_start': '2026-10-03', 'view': 'drivers', 'selected_id': 12})
        for factory, path in ((checks_url, '/owner-analysis/checks'), (analysis_url, '/owner-analysis')):
            parsed = urlsplit(factory(self.week, token))
            self.assertEqual(parsed.path, path)
            self.assertFalse(parsed.netloc)
            self.assertEqual(parse_qs(parsed.query), {'week_start': ['2026-10-03'],
                                                    'view': ['drivers'], 'driver_id': ['12']})
        self.assertEqual(urlsplit(checks_url(self.week, token)).fragment, 'week-2026-10-03')

    def test_monthly_checks_preserve_remembered_week_and_truck_filter(self):
        remembered = date(2026, 10, 17)
        token = review_context_for('monthly', remembered, month='2026-10', view='trucks', selected_id=4)
        for factory, path in ((checks_url, '/owner-analysis/checks/monthly'),
                              (analysis_url, '/owner-analysis/monthly')):
            parsed = urlsplit(factory(self.week, token))
            self.assertEqual(parsed.path, path)
            self.assertEqual(parse_qs(parsed.query), {'month': ['2026-10'], 'week_start': ['2026-10-17'],
                                                    'view': ['trucks'], 'truck_id': ['4']})
        self.assertEqual(urlsplit(checks_url(self.week, token)).fragment, 'week-2026-10-03')

    def test_fallback_without_context_opens_weekly_checks(self):
        parsed = urlsplit(checks_url(self.week))
        self.assertEqual(parsed.path, '/owner-analysis/checks')
        self.assertEqual(parse_qs(parsed.query)['week_start'], ['2026-10-03'])

    def test_changed_or_expired_context_is_rejected(self):
        token = review_context_for('weekly', self.week)
        for invalid in ('bad' + token, '', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                read_review_context(invalid)
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp', return_value=1000):
            expired = review_context_for('weekly', self.week)
        with self.assertRaises(ValueError):
            read_review_context(expired)

    def test_context_is_bound_to_week_or_payroll_month(self):
        weekly = review_context_for('weekly', self.week)
        monthly = review_context_for('monthly', self.week, month='2026-10')
        for token, outside in ((weekly, date(2026, 10, 10)), (monthly, date(2026, 9, 26))):
            with self.subTest(outside=outside), self.assertRaises(ValueError):
                read_review_context(token, week=outside)
        self.assertEqual(read_review_context(monthly, week=date(2026, 10, 24))['month'], '2026-10')

    def test_even_signed_invalid_payloads_are_rejected(self):
        valid = dict(period='weekly', week_start='2026-10-03', view='overview', selected_id=None)
        invalid = [dict(valid, period='arbitrary'), dict(valid, week_start='2026-10-04'),
                   dict(valid, week_start='20261003'), dict(valid, week_start='9999-12-31'),
                   dict(valid, view='https://example.org'), dict(valid, selected_id=1),
                   dict(valid, return_url='https://example.org'), dict(valid, month='2026-10'),
                   dict(valid, period='monthly'), dict(valid, period='monthly', month='2026-1'),
                   dict(valid, period='monthly', month='2026-09'), dict(valid, view=[]),
                   dict(valid, period=[])]
        invalid.extend(dict(valid, view='drivers', selected_id=value)
                       for value in (True, 0, -1, '1', 2147483648))
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                read_review_context(_serializer().dumps(payload))

    def test_generation_rejects_mixed_or_invalid_selection(self):
        for fields in (dict(month='2026-10'), dict(view='overview', selected_id=1),
                       dict(view='drivers', selected_id=True), dict(view='bad'),
                       dict(view='trucks', selected_id=2147483648)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                review_context_for('weekly', self.week, **fields)
        with self.assertRaises(ValueError):
            review_context_for('monthly', date(2026, 9, 26), month='2026-10')
