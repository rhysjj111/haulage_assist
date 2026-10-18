"""Dedicated corrections present human units and preserve bound source targets."""

from datetime import date
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from owner_test_support import OwnerTestCase, app, db
from haulage_app.models import Day, Fuel, Job
from haulage_app.owner_analysis.corrections import correction_url, fuel_flag_correction_url
from haulage_app.owner_analysis.navigation import review_context_for


class _EntryFields(HTMLParser):
    """Read the actual submitted controls without depending on their layout."""

    def __init__(self, html):
        super().__init__()
        self.fields = {}
        self.forms = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.current = dict(attrs, fields={})
            self.forms.append(self.current)
        if tag in ('input', 'select', 'textarea') and 'name' in attrs:
            field = dict(attrs, tag=tag)
            self.fields.setdefault(attrs['name'], []).append(field)
            if self.current is not None:
                self.current['fields'][attrs['name']] = field

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None

    def field(self, name):
        fields = self.fields[name]
        if len(fields) != 1:
            raise AssertionError(f'Expected one {name} input, found {len(fields)}')
        return fields[0]


class OwnerCorrectionFormTests(OwnerTestCase):
    def setUp(self):
        super().setUp()
        self.add_truck()
        self.add_truck(2)
        self.add_driver(first_name='Historical', employment_end=date(2026, 1, 1))
        self.add_driver(2, first_name='Other')
        self.day = self.add_day(start_mileage=14511, end_mileage=30030,
                                additional_earned=2525, additional_wages=1010)
        self.job = self.add_job(self.day, earned=17525)

    def link(self, code, *, navigation=None, **fields):
        with app.test_request_context():
            return correction_url(self.start, dict(code=code, **fields), review_context=navigation)

    def job_link(self, **kwargs):
        return self.link('job_amount_out_of_range', record_type='job', record_id=self.job, **kwargs)

    def job_data(self, **changes):
        data = dict(date_cd='2026-10-05', driver_id='1', earned='175.25',
                    collection='Depot', delivery='Town', notes='Checked')
        data.update(changes)
        return data

    def test_get_displays_pence_and_hundredths_once_for_every_entry_kind(self):
        fuel = self.add_fuel(fuel_cost=14511, fuel_volume=10025)
        payslip = self.add_payslip(total_wage=55055, total_cost_to_employer=66066)
        cases = [
            (self.link('missing_mileage', record_type='day', record_id=self.day),
             {'start_mileage': '145.11', 'end_mileage': '300.30',
              'additional_earned': '25.25', 'additional_wages': '10.10'}),
            (self.job_link(), {'earned': '175.25'}),
            (self.link('fuel_amount_out_of_range', record_type='fuel', record_id=fuel),
             {'fuel_cost': '145.11', 'fuel_volume': '100.25'}),
            (self.link('payslip_amount_out_of_range', record_type='payslip', record_id=payslip),
             {'total_wage': '550.55', 'total_cost_to_employer': '660.66'}),
        ]
        for path, expected in cases:
            with self.subTest(path=urlsplit(path).path):
                response, _ = self.get_page(path)
                fields = _EntryFields(response.text)
                for name, value in expected.items():
                    self.assertEqual(fields.field(name)['value'], value)
                self.assertNotIn('modal_edit_', response.text)
                self.assertNotIn('name="split"', response.text)
                self.assertIn('Cancel', response.text)
                self.assertIn('Week at a glance', response.text)

    def test_locked_historical_driver_is_clear_and_cannot_be_replaced_on_error(self):
        path = self.job_link()
        response, _ = self.get_page(path)
        field = _EntryFields(response.text).field('driver_id')
        self.assertEqual((field['tag'], field['type'], field['value']), ('input', 'hidden', '1'))
        self.assertIn('Historical Test', response.text)
        self.assertNotIn('Other Test', response.text)
        response = self.client.post(path, data=self.job_data(driver_id='2'))
        self.assertEqual(response.status_code, 400)
        field = _EntryFields(response.text).field('driver_id')
        self.assertEqual(field['value'], '1', 'A rejected target override must not become the next submitted identity')
        self.assertEqual(db.session.get(Job, self.job).day_id, self.day)

    def test_add_day_date_is_locked_but_edit_dates_have_selected_week_bounds(self):
        add = self.link('missing_day', driver_id=1, date=date(2026, 10, 6))
        edit = self.link('missing_mileage', record_type='day', record_id=self.day)
        response, _ = self.get_page(add)
        date_field = _EntryFields(response.text).field('date')
        self.assertEqual((date_field['type'], date_field['value']), ('hidden', '2026-10-06'))
        response, _ = self.get_page(edit)
        date_field = _EntryFields(response.text).field('date')
        self.assertEqual((date_field['type'], date_field['min'], date_field['max']),
                         ('date', '2026-10-03', '2026-10-09'))
        rejected = self.client.post(add, data=dict(date='2026-10-07', driver_id='1', status='absent'))
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(_EntryFields(rejected.text).field('date')['value'], '2026-10-06')
        self.assertEqual(Day.query.count(), 1)

    def test_missing_fuel_locks_truck_and_date_while_existing_receipt_can_change_truck(self):
        add = self.link('missing_fuel_receipt', truck_id=1, date=date(2026, 10, 5))
        response, _ = self.get_page(add)
        fields = _EntryFields(response.text)
        self.assertEqual(fields.field('truck_id')['type'], 'hidden')
        self.assertEqual(fields.field('truck_id')['value'], '1')
        self.assertEqual(fields.field('date')['type'], 'hidden')
        self.assertIn('AA26 001', response.text)
        rejected = self.client.post(add, data=dict(date='2026-10-05', truck_id='2', fuel_card_name='Fleet',
                                                 fuel_volume='100.25', fuel_cost='145.11'))
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(_EntryFields(rejected.text).field('truck_id')['value'], '1')
        self.assertEqual(Fuel.query.count(), 0)
        fuel = self.add_fuel()
        edit = self.link('fuel_amount_out_of_range', record_type='fuel', record_id=fuel)
        response, _ = self.get_page(edit)
        self.assertEqual(_EntryFields(response.text).field('truck_id')['tag'], 'select')

    def test_invalid_money_redisplay_keeps_raw_value_without_scaling_and_other_fields(self):
        path = self.job_link()
        note = '<script>unsafe()</script> & a quote "'
        response = self.client.post(path, data=self.job_data(earned='175.255', notes=note))
        self.assertEqual(response.status_code, 400)
        fields = _EntryFields(response.text)
        self.assertEqual(fields.field('earned')['value'], '175.255')
        self.assertEqual(fields.field('date_cd')['value'], '2026-10-05')
        self.assertIn('&lt;script&gt;unsafe()&lt;/script&gt;', response.text)
        self.assertNotIn('<script>unsafe()</script>', response.text)
        self.assertEqual(db.session.get(Job, self.job).earned, 17525)
        # Successful decimal input still uses exact integer pence.
        response = self.client.post(path, data=self.job_data(earned='145.11'))
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(db.session.get(Job, self.job).earned, 14511)

    def test_day_status_controls_preserve_working_values_until_save(self):
        path = self.link('missing_mileage', record_type='day', record_id=self.day)
        page, _ = self.get_page(path)
        fields = _EntryFields(page.text)
        self.assertEqual(fields.field('start_mileage')['value'], '145.11')
        self.assertEqual(fields.field('additional_earned')['value'], '25.25')
        self.assertIn('Holiday', page.text)
        self.assertIn('Absent', page.text)
        self.assertIn('data-owner-working-fields', page.text)
        self.assertIn('owner-working-help', page.text)
        # Only saving a genuine nonworking status clears source working fields.
        self.assertEqual(db.session.get(Day, self.day).additional_earned, 2525)
        response = self.client.post(path, data=dict(date='2026-10-05', driver_id='1', status='holiday',
                                                  truck_id='1', additional_earned='25.25'))
        self.assertEqual(response.status_code, 303, response.text)
        entry = db.session.get(Day, self.day)
        self.assertEqual(entry.status, 'holiday')
        self.assertIsNone(entry.truck_id)
        self.assertEqual(entry.additional_earned, 0)

    def test_split_correction_remains_read_only_without_any_source_mutation_controls(self):
        db.session.execute(Job.__table__.update().where(Job.id == self.job).values(split=True))
        db.session.commit()
        path = self.job_link()
        page, _ = self.get_page(path)
        self.assertIn('read-only', page.text)
        self.assertFalse(any(form.get('method', '').lower() == 'post'
                             for form in _EntryFields(page.text).forms))
        self.assertNotIn('earned', _EntryFields(page.text).fields)
        self.assertEqual(self.client.post(path, data=self.job_data()).status_code, 400)
        self.assertTrue(db.session.get(Job, self.job).split)

    def test_fuel_flag_form_explains_precisely_what_will_change(self):
        db.session.execute(Day.__table__.update().where(Day.id == self.day).values(fuel=True))
        db.session.commit()
        with app.test_request_context():
            path = fuel_flag_correction_url(self.start, dict(code='missing_fuel_receipt', truck_id=1,
                                                             date=date(2026, 10, 5)))
        response, _ = self.get_page(path)
        self.assertIn('AA26 001', response.text)
        self.assertIn('fuel', response.text.lower())
        self.assertIn('does not add a receipt or fuel cost', response.text.lower())
        self.assertIn('Cancel', response.text)
        fields = _EntryFields(response.text)
        self.assertNotIn('fuel_cost', fields.fields)
        self.assertNotIn('fuel_volume', fields.fields)
        self.assertEqual(len([form for form in fields.forms if form.get('method') == 'post']), 1)

    def test_invalid_form_keeps_csrf_nearby_and_monthly_driver_return_then_saves(self):
        app.config['WTF_CSRF_ENABLED'] = True
        self.addCleanup(app.config.update, WTF_CSRF_ENABLED=False)
        with app.test_request_context():
            navigation = review_context_for('monthly', date(2026, 10, 17), month='2026-10',
                                            view='drivers', selected_id=1)
        path = self.job_link(navigation=navigation) + '&nearby=1'
        response, _ = self.get_page(path)
        fields = _EntryFields(response.text)
        form = next(form for form in fields.forms if 'owner_context' in form['fields'])
        csrf = fields.field('csrf_token')['value']
        missing_csrf = self.client.post(form['action'], data=self.job_data())
        self.assertEqual(missing_csrf.status_code, 400)
        invalid = self.client.post(form['action'], data=self.job_data(earned='bad', csrf_token=csrf))
        self.assertEqual(invalid.status_code, 400)
        invalid_form = next(form for form in _EntryFields(invalid.text).forms if 'owner_context' in form['fields'])
        self.assertEqual(parse_qs(urlsplit(invalid_form['action']).query)['nearby'], ['1'])
        self.assertEqual(invalid_form['fields']['earned']['value'], 'bad')
        saved = self.client.post(invalid_form['action'], data=self.job_data(earned='200.20',
                    csrf_token=invalid_form['fields']['csrf_token']['value']))
        self.assertEqual(saved.status_code, 303, saved.text)
        target = urlsplit(saved.location)
        self.assertEqual(target.path, '/owner-analysis/checks/monthly')
        self.assertEqual(parse_qs(target.query), {'month': ['2026-10'], 'week_start': ['2026-10-17'],
                                                'view': ['drivers'], 'driver_id': ['1']})
        self.assertEqual(target.fragment, 'week-2026-10-03')
        self.assertEqual(db.session.get(Job, self.job).earned, 20020)

    def test_same_visible_form_is_rejected_when_exact_source_changes(self):
        path = self.job_link()
        page, _ = self.get_page(path)
        form = next(form for form in _EntryFields(page.text).forms if 'owner_context' in form['fields'])
        db.session.execute(Job.__table__.update().where(Job.id == self.job).values(earned=20123))
        db.session.commit()
        response = self.client.post(form['action'], data=self.job_data())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(db.session.get(Job, self.job).earned, 20123)
