"""One actionable Data Checks review keeps evidence and exact-target edits together."""

from datetime import date, timedelta
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from sqlalchemy import event, select, text
from werkzeug.datastructures import MultiDict

from owner_test_support import OwnerTestCase, app, db
from haulage_app.models import Day, DriverEmploymentHistory, Fuel, Job, Payslip
from haulage_app.owner_analysis.corrections import _serializer, correction_url
from haulage_app.owner_analysis.models import OwnerIssueVerification


class _ReviewHTML(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.links = []
        self.checks = []
        self.missing_day_groups = []
        self.section_stack = []
        self.current_form = None
        self.current_check = None
        self.current_select = None
        self.current_textarea = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section':
            section = dict(attrs)
            if 'data-owner-missing-days-driver' in attrs:
                week = next((parent['id'][5:] for parent in reversed(self.section_stack)
                             if parent.get('id', '').startswith('week-') and len(parent['id']) == 15), None)
                group = dict(week=week, driver_id=int(attrs['data-owner-missing-days-driver']), checks=[])
                self.missing_day_groups.append(group)
                section['missing_group'] = group
            self.section_stack.append(section)
        if tag == 'article' and 'data-owner-check-key' in attrs:
            self.current_check = dict(key=attrs['data-owner-check-key'], links=[], forms=[])
            self.checks.append(self.current_check)
            group = next((parent['missing_group'] for parent in reversed(self.section_stack)
                          if 'missing_group' in parent), None)
            if group is not None:
                group['checks'].append(self.current_check)
        if tag == 'form':
            self.current_form = dict(attrs, fields={})
            self.forms.append(self.current_form)
            if self.current_check is not None:
                self.current_check['forms'].append(self.current_form)
        if tag in ('input', 'textarea', 'select') and 'name' in attrs and self.current_form is not None:
            field = dict(attrs, tag=tag)
            self.current_form['fields'][attrs['name']] = field
            if tag == 'select':
                self.current_select = field
            if tag == 'textarea':
                field['value'] = ''
                self.current_textarea = field
        if tag == 'option' and self.current_select is not None and 'selected' in attrs:
            self.current_select['value'] = attrs.get('value', '')
        if tag == 'a':
            self.links.append(attrs)
            if self.current_check is not None:
                self.current_check['links'].append(attrs)

    def handle_data(self, data):
        if self.current_textarea is not None:
            self.current_textarea['value'] += data

    def handle_endtag(self, tag):
        if tag == 'section':
            self.section_stack.pop()
        if tag == 'select':
            self.current_select = None
        if tag == 'textarea':
            # HTML ignores the first newline after a textarea start tag;
            # WTForms deliberately prepends one when rendering its value.
            if self.current_textarea is not None:
                value = self.current_textarea['value']
                if value.startswith('\r\n'):
                    value = value[2:]
                elif value.startswith('\n'):
                    value = value[1:]
                self.current_textarea['value'] = value
            self.current_textarea = None
        if tag == 'form':
            self.current_form = None
        if tag == 'article':
            self.current_check = None

    def correction(self, kind):
        matches = [form for form in self.forms if 'owner_context' in form['fields']
                   and f'/{kind}/add_{kind}/' in form.get('action', '')]
        if len(matches) != 1:
            raise AssertionError(f'Expected one {kind} correction form, found {len(matches)}')
        return matches[0]

    @staticmethod
    def hidden_values(form):
        return {name: field.get('value', '') for name, field in form['fields'].items()
                if field.get('type') == 'hidden'}


class OwnerUnifiedReviewTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        clock = patch('haulage_app.owner_analysis.routes.today_london', return_value=date(2026, 10, 18))
        clock.start()
        self.addCleanup(clock.stop)
        self.add_truck()
        self.add_truck(2)
        self.add_driver(first_name='Alice', employment_start=date(2026, 10, 5),
                        employment_end=date(2026, 10, 9))
        self.add_driver(2, first_name='Bob', truck_id=2, employment_start=date(2026, 10, 5),
                        employment_end=date(2026, 10, 9))
        self.day = self.add_day(fuel=True)
        self.job = self.add_job(self.day, earned=0, collection='North depot', delivery='West port')
        self.add_day(on_date=date(2026, 10, 7), status='holiday', truck_id=None)
        self.bob_day = self.add_day(driver_id=2, truck_id=2)
        self.bob_job = self.add_job(self.bob_day, earned=53000)
        self.bob_payslip = self.add_payslip(driver_id=2)
        self.configure_overheads()

    def issue(self, code, *, monthly=False, **fields):
        path = '/owner-analysis/checks/monthly?month=2026-10&week_start=2026-10-10&view=drivers&driver_id=2' if monthly else '/owner-analysis/checks?week_start=2026-10-03'
        _, context = self.get_page(path)
        report = next(week for week in context['weeks'] if week['week_start'] == self.start)
        return next(issue for issue in report['issues'] if issue['code'] == code
                    and all(issue.get(key) == value for key, value in fields.items()))

    def review(self, code, **fields):
        issue = self.issue(code, **fields)
        response, context = self.get_page(issue['investigation_url'])
        return issue, response, context, _ReviewHTML(response.text)

    def source_snapshot(self):
        with db.session.no_autoflush:
            return {name: [tuple(row) for row in db.session.execute(select(table).order_by(table.c.id))]
                    for name, table in db.metadata.tables.items() if name in ('day', 'job', 'fuel', 'payslip')}

    def assert_monthly_return(self, response):
        self.assertEqual(response.status_code, 303, response.text)
        target = urlsplit(response.location)
        self.assertEqual(target.path, '/owner-analysis/checks/monthly')
        self.assertEqual(parse_qs(target.query), {'month': ['2026-10'], 'week_start': ['2026-10-10'],
                                                'view': ['drivers'], 'driver_id': ['2']})
        self.assertEqual(target.fragment, 'week-2026-10-03')

    def test_weekly_and_monthly_lists_have_one_review_link_and_no_per_check_forms(self):
        for path in ('/owner-analysis/checks?week_start=2026-10-03',
                     '/owner-analysis/checks/monthly?month=2026-10&week_start=2026-10-10'):
            with self.subTest(path=path):
                response, context = self.get_page(path)
                html = _ReviewHTML(response.text)
                issues = [issue for report in context['weeks'] for issue in report['outstanding_issues']]
                self.assertTrue(issues)
                self.assertEqual(len(html.checks), len(issues))
                by_key = {issue['key']: issue for issue in issues}
                for card in html.checks:
                    self.assertEqual(card['forms'], [], 'Check list items should contain no correction or decision forms')
                    self.assertEqual(len(card['links']), 1, 'One Review action replaces separate investigation and edit links')
                    issue = by_key[card['key']]
                    self.assertEqual(card['links'][0]['href'], issue.get('review_url', issue['investigation_url']))
                post_paths = {urlsplit(form.get('action', '')).path for form in html.forms
                              if form.get('method', '').lower() == 'post'}
                self.assertFalse(post_paths & {'/owner-analysis/verify', '/owner-analysis/absence'})
                self.assertFalse(any('/add_' in action for action in post_paths))

    def test_missing_weekdays_group_once_per_driver_and_week_without_losing_date_targets_or_counts(self):
        # Both drivers need entries in both completed October payroll weeks.
        db.session.execute(DriverEmploymentHistory.__table__.update().values(end_date=date(2026, 10, 16)))
        db.session.commit()
        for path in ('/owner-analysis/checks?week_start=2026-10-03',
                     '/owner-analysis/checks/monthly?month=2026-10&week_start=2026-10-10&view=drivers&driver_id=2'):
            with self.subTest(path=path):
                response, context = self.get_page(path)
                html = _ReviewHTML(response.text)
                expected = {}
                all_issues = []
                for week in context['weeks']:
                    all_issues.extend(week['outstanding_issues'])
                    self.assertIn(f"{len(week['outstanding_issues'])} outstanding", response.text)
                    for issue in week['outstanding_issues']:
                        if issue['code'] == 'missing_day':
                            identity = (week['week_start'].isoformat(), issue['driver_id'])
                            expected.setdefault(identity, []).append(issue)
                self.assertGreaterEqual(len(expected), 2)
                self.assertEqual(len(html.checks), len(all_issues), 'Grouping must not alter the number of raw checks')
                identities = [(group['week'], group['driver_id']) for group in html.missing_day_groups]
                self.assertCountEqual(identities, expected, 'Each driver gets exactly one group in each affected week')
                seen_dates = []
                for group in html.missing_day_groups:
                    identity = (group['week'], group['driver_id'])
                    issues = {issue['key']: issue for issue in expected[identity]}
                    self.assertCountEqual([card['key'] for card in group['checks']], issues)
                    for card in group['checks']:
                        issue = issues[card['key']]
                        seen_dates.append((group['week'], group['driver_id'], issue['date']))
                        self.assertLess(issue['date'].weekday(), 5)
                        self.assertEqual(card['forms'], [])
                        self.assertEqual(len(card['links']), 1)
                        self.assertEqual(card['links'][0]['href'], issue.get('review_url', issue['investigation_url']))
                        target = urlsplit(card['links'][0]['href'])
                        self.assertEqual(target.path, '/owner-analysis/checks/investigate')
                        self.assertEqual(parse_qs(target.query)['week_start'], [group['week']])
                        self.assertEqual(parse_qs(target.query)['issue_key'], [issue['key']])
                expected_dates = [(week, driver, issue['date']) for (week, driver), issues in expected.items()
                                  for issue in issues]
                self.assertCountEqual(seen_dates, expected_dates)
                self.assertEqual(len(seen_dates), len(set(seen_dates)), 'A missing date must appear exactly once')

    def test_payroll_review_offers_form_and_explicit_zero_cost_decision_beside_week_evidence(self):
        issue, response, context, html = self.review('missing_payslip', driver_id=1)
        form = html.correction('payslip')
        self.assertEqual(form['fields']['driver_id']['value'], '1')
        self.assertIn('total_wage', form['fields'])
        self.assertIn('total_cost_to_employer', form['fields'])
        token = form['fields']['owner_context']['value']
        self.assertEqual(_serializer().loads(token)['review_issue_key'], issue['key'])
        decisions = [f for f in html.forms if urlsplit(f.get('action', '')).path == '/owner-analysis/verify']
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['fields']['decision']['value'], 'confirmed_zero')
        self.assertEqual(decisions[0]['fields']['issue_key']['value'], issue['key'])
        self.assertIn('Week at a glance', response.text)
        self.assertIn('North depot', response.text)
        self.assertIn('West port', response.text)
        self.assertEqual({row['id'] for row in context['week_context']['payslips']}, {self.bob_payslip})

    def test_invalid_inline_payroll_keeps_selected_check_raw_values_csrf_and_monthly_return(self):
        app.config['WTF_CSRF_ENABLED'] = True
        self.addCleanup(app.config.update, WTF_CSRF_ENABLED=False)
        issue, _, _, html = self.review('missing_payslip', monthly=True, driver_id=1)
        form = html.correction('payslip')
        payload = dict(html.hidden_values(form), total_wage='550.555', total_cost_to_employer='660.66')
        before = self.source_snapshot()
        no_csrf = dict(payload)
        no_csrf.pop('csrf_token', None)
        self.assertEqual(self.client.post(form['action'], data=no_csrf).status_code, 400)
        rejected = self.client.post(form['action'], data=payload)
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.source_snapshot(), before)
        rerendered = _ReviewHTML(rejected.text)
        retry = rerendered.correction('payslip')
        self.assertEqual(retry['fields']['total_wage']['value'], '550.555')
        self.assertEqual(retry['fields']['total_cost_to_employer']['value'], '660.66')
        self.assertEqual(retry['fields']['driver_id']['value'], '1')
        bound = _serializer().loads(retry['fields']['owner_context']['value'])
        self.assertEqual(bound['review_issue_key'], issue['key'])
        self.assertTrue(bound['review_context'])
        self.assertIn('Week at a glance', rejected.text)
        self.assertTrue(any(urlsplit(f.get('action', '')).path == '/owner-analysis/verify'
                            for f in rerendered.forms), 'An invalid entry must retain the other valid review option')
        saved = self.client.post(retry['action'], data=dict(rerendered.hidden_values(retry),
                                    total_wage='550.55', total_cost_to_employer='660.66'))
        self.assert_monthly_return(saved)
        payslip = Payslip.query.filter_by(driver_id=1).one()
        self.assertEqual((payslip.total_wage, payslip.total_cost_to_employer), (55055, 66066))

    def test_missing_day_review_combines_work_entry_and_exact_date_absence_option(self):
        issue, response, _, html = self.review('missing_day', driver_id=1, date=date(2026, 10, 6))
        form = html.correction('day')
        self.assertEqual(form['fields']['driver_id']['value'], '1')
        self.assertEqual(form['fields']['date']['value'], '2026-10-06')
        self.assertEqual(form['fields']['date']['type'], 'hidden')
        self.assertIn('start_mileage', form['fields'])
        self.assertIn('end_mileage', form['fields'])
        self.assertIn('status', form['fields'])
        decisions = [f for f in html.forms if urlsplit(f.get('action', '')).path == '/owner-analysis/absence']
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['fields']['absent_date']['value'], '2026-10-06')
        self.assertEqual(decisions[0]['fields']['fingerprint']['value'], issue['fingerprint'])
        self.assertFalse(any(urlsplit(f.get('action', '')).path == '/owner-analysis/verify' for f in html.forms))
        self.assertIn('No entry', response.text)

    def test_missing_fuel_review_can_add_receipt_or_clear_accidental_flag_in_place(self):
        issue, response, _, html = self.review('missing_fuel_receipt', truck_id=1)
        forms = [form for form in html.forms if 'owner_context' in form['fields']]
        by_kind = {_serializer().loads(form['fields']['owner_context']['value'])['kind']: form for form in forms}
        self.assertEqual(set(by_kind), {'fuel', 'fuel_flag'})
        receipt, flag = by_kind['fuel'], by_kind['fuel_flag']
        self.assertEqual(receipt['fields']['truck_id']['value'], '1')
        self.assertEqual(receipt['fields']['date']['value'], '2026-10-05')
        self.assertIn('fuel_card_name', receipt['fields'])
        self.assertIn('fuel_volume', receipt['fields'])
        self.assertIn('fuel_cost', receipt['fields'])
        for form in forms:
            self.assertEqual(_serializer().loads(form['fields']['owner_context']['value'])['review_issue_key'], issue['key'])
        self.assertIn('does not add a receipt or fuel cost', response.text.lower())
        saved = self.client.post(flag['action'], data=html.hidden_values(flag))
        self.assertEqual(saved.status_code, 303, saved.text)
        self.assertFalse(db.session.get(Day, self.day).fuel)
        self.assertEqual(Fuel.query.count(), 0)
        self.assertEqual(self.client.get(issue['investigation_url']).status_code, 404)
        self.assertEqual(self.client.post(receipt['action'], data=dict(html.hidden_values(receipt),
            fuel_card_name='Fleet', fuel_volume='100.00', fuel_cost='120.00')).status_code, 409)
        self.assertEqual(Fuel.query.count(), 0, 'The alternate stale action cannot create fuel after the check is cleared')

    def test_exact_source_change_rejects_inline_save_but_other_driver_evidence_does_not(self):
        _, _, _, html = self.review('job_amount_out_of_range', record_id=self.job)
        form = html.correction('job')
        payload = dict(html.hidden_values(form), earned='150.25', collection='North depot', delivery='West port', notes='Checked')
        db.session.execute(Job.__table__.update().where(Job.id == self.job).values(earned=25000))
        db.session.commit()
        stale = self.client.post(form['action'], data=payload)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(db.session.get(Job, self.job).earned, 25000)
        # An unchanged target remains editable even when contextual evidence changes.
        _, _, _, html = self.review('missing_payslip', driver_id=1)
        form = html.correction('payslip')
        db.session.execute(text('UPDATE payslip SET total_wage=total_wage+100 WHERE id=:id'), {'id': self.bob_payslip})
        db.session.commit()
        saved = self.client.post(form['action'], data=dict(html.hidden_values(form), total_wage='550.55', total_cost_to_employer='660.66'))
        self.assertEqual(saved.status_code, 303, saved.text)
        self.assertEqual(Payslip.query.filter_by(driver_id=1).one().total_wage, 55055)

    def test_split_job_review_is_read_only_and_gets_never_flush_pending_source_edits(self):
        db.session.execute(Job.__table__.update().where(Job.id == self.job).values(split=True))
        db.session.commit()
        issue = self.issue('job_amount_out_of_range', record_id=self.job)
        pending = db.session.get(Job, self.bob_job)
        pending.notes = 'Unsaved other driver note'
        before = self.source_snapshot()
        response, context = self.get_page(issue['investigation_url'])
        html = _ReviewHTML(response.text)
        self.assertIn('read-only', response.text)
        self.assertFalse(any('owner_context' in form['fields'] for form in html.forms))
        self.assertNotIn('name="earned"', response.text)
        self.assertEqual(context['week_context']['driver_id'], 1)
        self.assertIn(pending, db.session.dirty)
        self.assertEqual(self.source_snapshot(), before)
        self.assertTrue(db.session.get(Job, self.job).split)

    def test_duplicate_group_compares_rows_and_requires_explicit_per_record_deletion(self):
        self.add_payslip(driver_id=1, id=20, total_wage=49000, total_cost_to_employer=54000)
        self.add_payslip(driver_id=1, id=21, total_wage=49500, total_cost_to_employer=54500)
        issue, response, _, html = self.review('multiple_payslips', monthly=True, driver_id=1)
        self.assertIn('£540.00', response.text)
        self.assertIn('£545.00', response.text)
        delete_forms = [form for form in html.forms if '/payslip/delete_payslip/' in form.get('action', '')]
        self.assertEqual(len(delete_forms), 2)
        for form in delete_forms:
            self.assertIn('confirm_delete', form['fields'])
            self.assertEqual(_serializer().loads(form['fields']['owner_context']['value'])['review_issue_key'], issue['key'])
        chosen = next(form for form in delete_forms if '/delete_payslip/21?' in form['action'])
        before = self.source_snapshot()
        self.assertEqual(self.client.post(chosen['action'], data=html.hidden_values(chosen)).status_code, 400)
        self.assertEqual(self.source_snapshot(), before)
        saved = self.client.post(chosen['action'], data=dict(html.hidden_values(chosen), confirm_delete='yes'))
        self.assert_monthly_return(saved)
        self.assertEqual({row.id for row in Payslip.query.filter_by(driver_id=1)}, {20})
        self.assertIsNotNone(db.session.get(Payslip, self.bob_payslip))

    def test_duplicate_member_editor_keeps_original_check_and_other_actions_after_invalid_submit(self):
        self.add_payslip(driver_id=1, id=20, total_wage=49000, total_cost_to_employer=54000)
        self.add_payslip(driver_id=1, id=21, total_wage=49500, total_cost_to_employer=54500)
        issue, _, _, html = self.review('multiple_payslips', monthly=True, driver_id=1)
        edits = [link['href'] for link in html.links if '/payslip/add_payslip/20/edit?' in link.get('href', '')]
        self.assertEqual(len(edits), 1)
        response, context = self.get_page(edits[0])
        self.assertEqual(context['issue']['key'], issue['key'])
        form = _ReviewHTML(response.text).correction('payslip')
        self.assertEqual(form['fields']['total_wage']['value'], '490.00')
        payload = dict(_ReviewHTML.hidden_values(form), date=form['fields']['date']['value'],
                       total_wage='490.001', total_cost_to_employer='541.25')
        rejected = self.client.post(form['action'], data=payload)
        self.assertEqual(rejected.status_code, 400)
        retry = _ReviewHTML(rejected.text).correction('payslip')
        self.assertEqual(retry['fields']['total_wage']['value'], '490.001')
        self.assertEqual(retry['fields']['total_cost_to_employer']['value'], '541.25')
        self.assertEqual(_serializer().loads(retry['fields']['owner_context']['value'])['review_issue_key'], issue['key'])
        self.assertIn('Week at a glance', rejected.text)
        self.assertIn('£545.00', rejected.text)
        self.assertEqual(Payslip.query.filter_by(driver_id=1).count(), 2)
        saved = self.client.post(retry['action'], data=dict(_ReviewHTML.hidden_values(retry),
            date=retry['fields']['date']['value'], total_wage='490.00', total_cost_to_employer='541.25'))
        self.assert_monthly_return(saved)
        self.assertEqual(db.session.get(Payslip, 20).total_cost_to_employer, 54125)
        self.assertEqual(db.session.get(Payslip, 21).total_cost_to_employer, 54500)
        self.assertEqual(Payslip.query.filter_by(driver_id=1).count(), 2)
        self.assertFalse(self.issue('multiple_payslips', driver_id=1)['resolved'],
                         'Editing one amount cannot silently verify a duplicate group')

    def test_duplicate_member_exception_cannot_create_move_or_reassign_payroll(self):
        self.add_payslip(driver_id=1, id=20, total_wage=49000, total_cost_to_employer=54000)
        self.add_payslip(driver_id=1, id=21, total_wage=49500, total_cost_to_employer=54500)
        _, _, _, html = self.review('multiple_payslips', driver_id=1)
        edit_url = next(link['href'] for link in html.links if '/payslip/add_payslip/20/edit?' in link.get('href', ''))
        response, _ = self.get_page(edit_url)
        form = _ReviewHTML(response.text).correction('payslip')
        data = dict(_ReviewHTML.hidden_values(form), date=form['fields']['date']['value'],
                    total_wage='490.00', total_cost_to_employer='541.25')
        before = self.source_snapshot()
        for change in ({'driver_id': '2'}, {'date': '2026-10-08'}):
            with self.subTest(change=change):
                self.assertEqual(self.client.post(form['action'], data=dict(data, **change)).status_code, 400)
                self.assertEqual(self.source_snapshot(), before)
        with app.test_request_context():
            legacy = correction_url(self.start, {'code': 'payslip_amount_out_of_range',
                'record_type': 'payslip', 'record_id': 20})
            add = correction_url(self.start, {'code': 'missing_payslip', 'driver_id': 1})
        # The narrow reviewed-member exception does not weaken old add/edit guards.
        self.assertEqual(self.client.post(legacy, data={key: value for key, value in data.items()
                         if key != 'owner_context'}).status_code, 400)
        self.assertEqual(self.client.post(add, data={'date': '2026-10-05', 'driver_id': '1',
            'total_wage': '490.00', 'total_cost_to_employer': '541.25'}).status_code, 400)
        self.assertEqual(self.source_snapshot(), before)

    def test_signed_issue_key_cannot_be_rebound_to_another_valid_check(self):
        _, _, _, html = self.review('job_amount_out_of_range', record_id=self.job)
        form = html.correction('job')
        payload = _serializer().loads(form['fields']['owner_context']['value'])
        payload['review_issue_key'] = self.issue('missing_payslip', driver_id=1)['key']
        forged_token = _serializer().dumps(payload)
        target = urlsplit(form['action'])
        query = parse_qs(target.query)
        query['owner_context'] = [forged_token]
        forged_url = target.path + '?' + urlencode(query, doseq=True)
        before = self.source_snapshot()
        self.assertEqual(self.client.get(forged_url).status_code, 400)
        rejected = self.client.post(forged_url, data=dict(owner_context=forged_token,
            date_cd='2026-10-05', driver_id='1', earned='150.25', collection='Depot', delivery='Port'))
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.source_snapshot(), before)

    def test_verification_removes_editor_and_previously_open_correction_cannot_overwrite_decision(self):
        issue, _, _, html = self.review('missing_payslip', driver_id=1)
        editor = html.correction('payslip')
        verify = next(form for form in html.forms if urlsplit(form.get('action', '')).path == '/owner-analysis/verify')
        saved = self.client.post(verify['action'], data=dict(html.hidden_values(verify),
            decision='confirmed_zero', note='Unpaid leave confirmed; no employer cost.'))
        self.assertEqual(saved.status_code, 303)
        response, context = self.get_page(issue['investigation_url'])
        self.assertTrue(context['issue']['resolved'])
        self.assertIn('Unpaid leave confirmed', response.text)
        self.assertFalse(any(form.get('method', '').lower() == 'post' for form in _ReviewHTML(response.text).forms))
        before = self.source_snapshot()
        rejected = self.client.post(editor['action'], data=dict(html.hidden_values(editor),
            total_wage='550.00', total_cost_to_employer='660.00'))
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(self.source_snapshot(), before)

    def test_inline_correction_rejects_duplicate_or_untrusted_navigation_parameters_before_writes(self):
        _, _, _, html = self.review('job_amount_out_of_range', record_id=self.job)
        form = html.correction('job')
        token = form['fields']['owner_context']['value']
        payload = dict(html.hidden_values(form), earned='150.25', collection='Depot', delivery='Port')
        before = self.source_snapshot()
        for suffix in ('&owner_context=' + token, '&nearby=1&nearby=0', '&issue_key=other', '&driver_id=2'):
            with self.subTest(suffix=suffix.split('=')[0]):
                response = self.client.post(form['action'] + suffix, data=payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.source_snapshot(), before)
        repeated = MultiDict(payload)
        repeated.add('owner_context', token)
        self.assertEqual(self.client.post(form['action'], data=repeated).status_code, 400)
        self.assertEqual(self.source_snapshot(), before)

    def test_failed_verification_keeps_note_selected_check_editor_and_monthly_return(self):
        issue, _, _, html = self.review('missing_payslip', monthly=True, driver_id=1)
        verify = next(form for form in html.forms if urlsplit(form.get('action', '')).path == '/owner-analysis/verify')
        self.assertTrue(verify['fields']['review_return']['value'])
        note = 'Payroll <checked> but decision needs correcting.'
        before = self.source_snapshot()
        # Missing payroll requires explicit zero cost, rather than generic verification.
        rejected = self.client.post(verify['action'], data=dict(html.hidden_values(verify),
            decision='verified', note=note))
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.source_snapshot(), before)
        self.assertEqual(OwnerIssueVerification.query.count(), 0)
        retry_html = _ReviewHTML(rejected.text)
        retry = next(form for form in retry_html.forms if urlsplit(form.get('action', '')).path == '/owner-analysis/verify')
        self.assertEqual(retry['fields']['note']['value'], note)
        self.assertEqual(retry['fields']['issue_key']['value'], issue['key'])
        self.assertTrue(retry_html.correction('payslip'))
        self.assertIn('Week at a glance', rejected.text)
        self.assertNotIn('Payroll <checked>', rejected.text)
        saved = self.client.post(retry['action'], data=dict(retry_html.hidden_values(retry),
            decision='confirmed_zero', note=note))
        self.assert_monthly_return(saved)
        self.assertTrue(self.issue('missing_payslip', driver_id=1)['resolved'])

    def test_failed_absence_keeps_note_status_exact_day_and_monthly_return(self):
        issue, _, _, html = self.review('missing_day', monthly=True, driver_id=1, date=date(2026, 10, 6))
        absence = next(form for form in html.forms if urlsplit(form.get('action', '')).path == '/owner-analysis/absence')
        self.assertTrue(absence['fields']['review_return']['value'])
        note = '<holiday checked> ' + 'x' * 4000
        before = self.source_snapshot()
        rejected = self.client.post(absence['action'], data=dict(html.hidden_values(absence),
            absent_date='2026-10-06', status='holiday', note=note))
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.source_snapshot(), before)
        retry_html = _ReviewHTML(rejected.text)
        retry = next(form for form in retry_html.forms if urlsplit(form.get('action', '')).path == '/owner-analysis/absence')
        self.assertEqual(retry['fields']['note']['value'], note)
        self.assertEqual(retry['fields']['status']['value'], 'holiday')
        self.assertEqual(retry['fields']['absent_date']['value'], '2026-10-06')
        self.assertEqual(retry['fields']['driver_id']['value'], '1')
        self.assertTrue(retry_html.correction('day'))
        self.assertIn('Week at a glance', rejected.text)
        self.assertNotIn('<holiday checked>', rejected.text)
        saved = self.client.post(retry['action'], data=dict(retry_html.hidden_values(retry),
            absent_date='2026-10-06', status='holiday', note='Holiday confirmed by dispatch.'))
        self.assert_monthly_return(saved)
        self.assertEqual(Day.query.filter_by(driver_id=1, date=date(2026, 10, 6)).one().status, 'holiday')

    def test_review_return_cannot_verify_another_issue_or_record_absence_for_another_day(self):
        _, _, _, payroll_html = self.review('missing_payslip', driver_id=1)
        verify = next(form for form in payroll_html.forms if urlsplit(form.get('action', '')).path == '/owner-analysis/verify')
        job_issue = self.issue('job_amount_out_of_range', record_id=self.job)
        before = self.source_snapshot()
        changed_issue = dict(payroll_html.hidden_values(verify), issue_key=job_issue['key'],
            fingerprint=job_issue['fingerprint'], decision='verified', note='Source document checked.')
        self.assertEqual(self.client.post(verify['action'], data=changed_issue).status_code, 400)
        self.assertEqual(OwnerIssueVerification.query.count(), 0)
        _, _, _, day_html = self.review('missing_day', driver_id=1, date=date(2026, 10, 6))
        absence = next(form for form in day_html.forms if urlsplit(form.get('action', '')).path == '/owner-analysis/absence')
        other_day = self.issue('missing_day', driver_id=1, date=date(2026, 10, 8))
        changed_day = dict(day_html.hidden_values(absence), absent_date='2026-10-08',
            fingerprint=other_day['fingerprint'], status='absent', note='Unpaid leave.')
        self.assertEqual(self.client.post(absence['action'], data=changed_day).status_code, 400)
        self.assertEqual(self.source_snapshot(), before)
        tampered = dict(payroll_html.hidden_values(verify), review_return='bad-token',
                        decision='confirmed_zero', note='No employer cost due.')
        self.assertEqual(self.client.post(verify['action'], data=tampered).status_code, 400)
        self.assertEqual(OwnerIssueVerification.query.count(), 0)

    def test_default_review_is_bounded_and_never_queries_unrelated_recent_history(self):
        issue = self.issue('missing_payslip', driver_id=1)
        # A large unrelated history must not turn this review into a full history page.
        for offset in range(35):
            other_day = self.add_day(driver_id=2, on_date=date(2027, 1, 1) + timedelta(days=offset))
            self.add_job(other_day)
        statements = []
        def capture(connection, cursor, statement, parameters, *unused):
            if statement.lstrip().lower().startswith('select'):
                statements.append((statement.lower(), str(parameters)))
        event.listen(db.engine, 'before_cursor_execute', capture)
        try:
            self.get_page(issue['investigation_url'])
        finally:
            event.remove(db.engine, 'before_cursor_execute', capture)
        self.assertTrue(statements)
        self.assertFalse(any('row_number' in statement for statement, _ in statements))
        self.assertFalse(any('2027-01-01' in params for _, params in statements))
        self.assertFalse(any('2026-09-26' in params or '2026-10-16' in params
                             for statement, params in statements if 'payslip' in statement))
