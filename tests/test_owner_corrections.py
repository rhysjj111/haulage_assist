"""Owner corrections bind a single historical record and never load old history."""
import re
from datetime import date, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import event

from owner_test_support import OwnerTestCase, app, db
from haulage_app.models import Day, Fuel, Job, Payslip
from haulage_app.owner_analysis.corrections import (
    _serializer, _week_basis, correction_url, fuel_flag_correction_url,
)
from haulage_app.owner_analysis.navigation import review_context_for


class OwnerCorrectionTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.add_truck()
        self.add_driver(employment_end=date(2026, 1, 1))
        self.day_id = self.add_day()
        self.job_id = self.add_job(self.day_id, earned=0)

    def link(self, code, **fields):
        with app.test_request_context():
            return correction_url(self.start, dict(code=code, **fields))

    def edit_job_url(self):
        return self.link('job_amount_out_of_range', record_type='job', record_id=self.job_id)

    def token(self, path):
        return parse_qs(urlsplit(path).query)['owner_context'][0]

    def job_data(self, **changes):
        values = dict(date_cd='2026-10-05', driver_id='1', earned='175.25',
                      collection='Depot', delivery='Town', notes='Checked')
        values.update(changes)
        return values

    def test_direct_historical_job_form_is_bounded_and_keeps_inactive_driver(self):
        path = self.edit_job_url()
        # More recent records do not hide the selected item under the normal cap.
        for offset in range(55):
            day = self.add_day(on_date=date(2027, 1, 1) + timedelta(days=offset))
            self.add_job(day)
        statements = []
        def capture(connection, cursor, statement, *unused):
            if statement.lstrip().lower().startswith('select'):
                statements.append(statement.lower())
        event.listen(db.engine, 'before_cursor_execute', capture)
        try:
            response = self.client.get(path)
        finally:
            event.remove(db.engine, 'before_cursor_execute', capture)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('Driver1 Test', response.text)
        self.assertIn('Back to Data Checks', response.text)
        self.assertNotIn('name="split"', response.text)
        self.assertNotIn('modal_edit_', response.text)
        self.assertFalse(any('row_number' in query for query in statements))
        self.assertTrue(all('between' in query or ' in (' in query or 'where ' in query
                            or 'notification' in query or 'anomaly' in query for query in statements))

    def test_corrected_job_returns_to_selected_week_with_303(self):
        response = self.client.post(self.edit_job_url(), data=self.job_data())
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(urlsplit(response.location).path, '/owner-analysis/checks')
        self.assertIn('week_start=2026-10-03', response.location)
        self.assertEqual(db.session.get(Job, self.job_id).earned, 17525)

    def test_tampered_signature_writes_nothing(self):
        path = self.edit_job_url()
        path = path.replace('owner_context=', 'owner_context=bad')
        response = self.client.post(path, data=self.job_data())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(db.session.get(Job, self.job_id).earned, 0)

    def test_context_cannot_be_used_for_another_record_or_entry_type(self):
        token = self.token(self.edit_job_url())
        for path in (f'/job/add_job/999/edit?owner_context={token}',
                     f'/fuel/add_fuel/0/entry?owner_context={token}'):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, data=self.job_data()).status_code, 400)
        self.assertEqual(db.session.get(Job, self.job_id).earned, 0)

    def test_actual_source_change_or_record_move_rejects_stale_form(self):
        path = self.edit_job_url()
        db.session.execute(Job.__table__.update().where(Job.id == self.job_id).values(earned=12345))
        db.session.commit()
        self.assertEqual(self.client.post(path, data=self.job_data()).status_code, 409)
        path = self.edit_job_url()
        db.session.execute(Day.__table__.update().where(Day.id == self.day_id).values(date=date(2026, 10, 12)))
        db.session.commit()
        self.assertEqual(self.client.post(path, data=self.job_data()).status_code, 409)
        self.assertEqual(db.session.get(Job, self.job_id).earned, 12345)

    def test_unrelated_driver_changes_do_not_stale_exact_record(self):
        path = self.edit_job_url()
        self.add_driver(driver_id=2)
        self.add_day(driver_id=2)
        response = self.client.post(path, data=self.job_data())
        self.assertEqual(response.status_code, 303)

    def test_driver_and_week_bounds_cannot_be_changed_by_post(self):
        self.add_driver(driver_id=2)
        for changes in (dict(driver_id='2'), dict(date_cd='2026-10-12'),
                        dict(split='on'), dict(earned='NaN'), dict(earned='175.255')):
            with self.subTest(changes=changes):
                response = self.client.post(self.edit_job_url(), data=self.job_data(**changes))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(db.session.get(Job, self.job_id).earned, 0)

    def test_csrf_required_when_enabled(self):
        app.config['WTF_CSRF_ENABLED'] = True
        path = self.edit_job_url()
        response = self.client.post(path, data=self.job_data())
        self.assertEqual(response.status_code, 400)
        page = self.client.get(path)
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text).group(1)
        response = self.client.post(path, data=self.job_data(csrf_token=token))
        self.assertEqual(response.status_code, 303, response.text)
        app.config['WTF_CSRF_ENABLED'] = False

    def test_missing_day_form_adds_exact_historical_driver_date(self):
        path = self.link('missing_day', driver_id=1, date=date(2026, 10, 6))
        self.assertEqual(self.client.get(path).status_code, 200)
        response = self.client.post(path, data=dict(date='2026-10-06', driver_id='1', status='absent'))
        self.assertEqual(response.status_code, 303, response.text)
        entry = Day.query.filter_by(driver_id=1, date=date(2026, 10, 6)).one()
        self.assertEqual(entry.status, 'absent')
        # Reusing the add token cannot create a second record.
        self.assertEqual(self.client.post(path, data=dict(date='2026-10-06', driver_id='1', status='absent')).status_code, 409)

    def test_working_day_without_earnings_adds_single_unsplit_job(self):
        path = self.link('working_day_without_earnings', record_type='day', record_id=self.day_id)
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertNotIn('name="split"', page.text)
        response = self.client.post(path, data=self.job_data())
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(Job.query.filter_by(day_id=self.day_id).count(), 2)

    def test_missing_fuel_receipt_adds_exact_truck_date(self):
        path = self.link('missing_fuel_receipt', truck_id=1, date=date(2026, 10, 5))
        response = self.client.post(path, data=dict(date='2026-10-05', truck_id='1', fuel_card_name='Silvey',
                                                  fuel_volume='100.25', fuel_cost='145.11'))
        self.assertEqual(response.status_code, 303, response.text)
        fuel = Fuel.query.one()
        self.assertEqual((fuel.truck_id, fuel.day_id, fuel.fuel_volume, fuel.fuel_cost),
                         (1, self.day_id, 10025, 14511))

    def test_fuel_flag_correction_clears_flag_without_creating_cost(self):
        db.session.execute(Day.__table__.update().values(fuel=True))
        db.session.commit()
        with app.test_request_context():
            path = fuel_flag_correction_url(self.start, dict(code='missing_fuel_receipt', truck_id=1, date=date(2026, 10, 5)))
        response = self.client.post(path)
        self.assertEqual(response.status_code, 303, response.text)
        self.assertFalse(db.session.get(Day, self.day_id).fuel)
        self.assertEqual(Fuel.query.count(), 0)

    def test_split_job_is_read_only_and_post_cannot_clear_split(self):
        db.session.execute(Job.__table__.update().values(split=True))
        db.session.commit()
        path = self.edit_job_url()
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200)
        self.assertIn('read-only', page.text)
        self.assertNotIn('name="earned"', page.text)
        self.assertEqual(self.client.post(path, data=self.job_data()).status_code, 400)
        self.assertTrue(db.session.get(Job, self.job_id).split)

    def test_duplicate_payslip_review_and_delete_are_bounded(self):
        self.add_payslip(id=1)
        self.add_payslip(id=2)
        path = self.link('multiple_payslips', driver_id=1)
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('Payslip #1', page.text)
        self.assertIn('Payslip #2', page.text)
        delete_url = '/payslip/delete_payslip/2?owner_context=' + self.token(path)
        self.assertEqual(self.client.post('/payslip/delete_payslip/999?owner_context=' + self.token(path)).status_code, 400)
        response = self.client.post(delete_url)
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(Payslip.query.count(), 1)

    def test_report_basis_link_generation_has_no_sql(self):
        report = {'review_basis': _week_basis(self.start)}
        with app.test_request_context(), patch('haulage_app.owner_analysis.corrections._week_basis', side_effect=AssertionError('Unexpected SQL')):
            path = correction_url(self.start, dict(code='job_amount_out_of_range', record_type='job', record_id=self.job_id), report)
            self.assertIn('owner_context=', path)

    def test_missing_payslip_uses_an_existing_day_and_records_exact_cost(self):
        path = self.link('missing_payslip', driver_id=1)
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('Driver1 Test', page.text)
        response = self.client.post(path, data=dict(date='2026-10-05', driver_id='1',
                                                  total_wage='550.55', total_cost_to_employer='660.66'))
        self.assertEqual(response.status_code, 303, response.text)
        entry = Payslip.query.one()
        self.assertEqual((entry.date, entry.day_id, entry.total_wage, entry.total_cost_to_employer),
                         (date(2026, 10, 5), self.day_id, 55055, 66066))

    def test_edit_day_preserves_scaled_values_and_rolls_back_invalid_status(self):
        path = self.link('missing_mileage', record_type='day', record_id=self.day_id)
        data = dict(date='2026-10-05', driver_id='1', status='working', truck_id='1',
                    start_mileage='145.11', end_mileage='300.30', additional_earned='25.25',
                    additional_wages='10.10', fuel='on', overnight='on')
        response = self.client.post(path, data=data)
        self.assertEqual(response.status_code, 303, response.text)
        entry = db.session.get(Day, self.day_id)
        self.assertEqual((entry.start_mileage, entry.end_mileage, entry.additional_earned, entry.additional_wages),
                         (14511, 30030, 2525, 1010))
        self.assertTrue(entry.fuel)
        path = self.link('missing_mileage', record_type='day', record_id=self.day_id)
        data['status'] = 'anything'
        self.assertEqual(self.client.post(path, data=data).status_code, 400)
        self.assertEqual(db.session.get(Day, self.day_id).status, 'working')

    def test_conflicting_form_context_cannot_be_substituted(self):
        path = self.edit_job_url()
        response = self.client.post(path, data=self.job_data(owner_context='different-token'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(db.session.get(Job, self.job_id).earned, 0)

    def test_correction_get_does_not_flush_unrelated_pending_source_edits(self):
        self.add_driver(driver_id=2)
        other_day = self.add_day(driver_id=2)
        other_job = self.add_job(other_day)
        path = self.edit_job_url()
        pending = db.session.get(Job, other_job)
        pending.notes = 'Unrelated unsaved note'
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(pending, db.session.dirty)
        self.assertTrue(db.session.is_modified(pending))

    def test_monthly_driver_context_round_trips_through_correction(self):
        with app.test_request_context():
            context = review_context_for('monthly', date(2026, 10, 17), month='2026-10',
                                         view='drivers', selected_id=1)
            path = correction_url(self.start, dict(code='job_amount_out_of_range',
                record_type='job', record_id=self.job_id), review_context=context)
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('Back to Data Checks', page.text)
        response = self.client.post(path, data=self.job_data())
        self.assertEqual(response.status_code, 303, response.text)
        parsed = urlsplit(response.location)
        self.assertEqual(parsed.path, '/owner-analysis/checks/monthly')
        self.assertEqual(parse_qs(parsed.query), {'month': ['2026-10'], 'week_start': ['2026-10-17'],
                                                'view': ['drivers'], 'driver_id': ['1']})
        self.assertEqual(parsed.fragment, 'week-2026-10-03')
        self.assertEqual(db.session.get(Job, self.job_id).earned, 17525)

    def test_invalid_embedded_navigation_context_rejects_post_before_write(self):
        with app.test_request_context():
            payload = _serializer().loads(self.token(self.edit_job_url()))
            payload['review_context'] = 'tampered-navigation-token'
            token = _serializer().dumps(payload)
        path = f'/job/add_job/{self.job_id}/edit?owner_context={token}'
        response = self.client.post(path, data=self.job_data())
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(db.session.get(Job, self.job_id).earned, 0)

    def test_signed_navigation_for_other_week_rejects_post_before_write(self):
        with app.test_request_context():
            payload = _serializer().loads(self.token(self.edit_job_url()))
            payload['review_context'] = review_context_for('weekly', date(2026, 10, 10))
            token = _serializer().dumps(payload)
        response = self.client.post(f'/job/add_job/{self.job_id}/edit?owner_context={token}',
                                    data=self.job_data())
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(db.session.get(Job, self.job_id).earned, 0)

    def test_duplicate_payslip_sublink_keeps_monthly_context(self):
        self.add_payslip(id=1)
        self.add_payslip(id=2)
        with app.test_request_context():
            context = review_context_for('monthly', self.start, month='2026-10', view='drivers', selected_id=1)
            path = correction_url(self.start, dict(code='multiple_payslips', driver_id=1), review_context=context)
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200, page.text)
        # Individual payslip edits inherit the original signed destination.
        for token in re.findall(r'owner_context=([^"&]+)', page.text):
            with app.app_context():
                payload = _serializer().loads(token)
            self.assertEqual(payload.get('review_context'), context)
        delete_url = '/payslip/delete_payslip/2?owner_context=' + self.token(path)
        response = self.client.post(delete_url)
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(urlsplit(response.location).path, '/owner-analysis/checks/monthly')
        self.assertIn('driver_id=1', response.location)
        self.assertEqual(Payslip.query.count(), 1)
