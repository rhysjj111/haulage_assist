"""Signed, single-record entry forms opened from Data Checks.

The ordinary entry/history flows are untouched. A correction context binds the
selected payroll week, exact target and its current source values; a changed or
moved record must be reopened from a fresh report before it can be changed.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_wtf import FlaskForm
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from wtforms import HiddenField

from haulage_app import db, f
from haulage_app.models import Day, Driver, Fuel, Job, Payslip, Truck
from .dates import validate_week_start, week_end
from .navigation import checks_url, read_review_context


class CorrectionForm(FlaskForm):
    owner_context = HiddenField()


_MODELS = {'day': Day, 'job': Job, 'fuel': Fuel, 'payslip': Payslip}
_FIELDS = {
    'days': ('id', 'date', 'driver_id', 'truck_id', 'status', 'overnight', 'fuel',
             'start_mileage', 'end_mileage', 'additional_earned', 'additional_wages'),
    'jobs': ('id', 'day_id', 'earned', 'collection', 'delivery', 'split', 'notes'),
    'fuel_entries': ('id', 'date', 'truck_id', 'day_id', 'fuel_cost', 'fuel_volume', 'fuel_card_name'),
    'payslips': ('id', 'date', 'driver_id', 'day_id', 'total_wage', 'total_cost_to_employer'),
}
_KEYS = {'day': 'days', 'job': 'jobs', 'fuel': 'fuel_entries', 'payslip': 'payslips'}


def _normal(value):
    if isinstance(value, date):
        return value.isoformat()
    return value


def _rows(rows, fields):
    return sorted(({key: _normal(row.get(key) if isinstance(row, dict) else getattr(row, key))
                    for key in fields} for row in rows), key=lambda row: row['id'])


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='owner-analysis-correction-v1')


def _week_basis(week):
    """Bounded queries only, also usable when a caller did not supply a report."""
    end = week_end(week)
    with db.session.no_autoflush:
        refresh = not (db.session.new or db.session.dirty or db.session.deleted)
        def fresh(statement):
            return statement.execution_options(populate_existing=True) if refresh else statement
        days = db.session.execute(fresh(select(Day).where(Day.date.between(week, end)))).scalars().all()
        day_ids = [day.id for day in days]
        jobs = (db.session.execute(fresh(select(Job).where(Job.day_id.in_(day_ids)))).scalars().all()
                if day_ids else [])
        fuel = db.session.execute(fresh(select(Fuel).where(Fuel.date.between(week, end)))).scalars().all()
        payslips = db.session.execute(fresh(select(Payslip).where(Payslip.date.between(week, end)))).scalars().all()
        return {key: _rows(values, _FIELDS[key]) for key, values in (
            ('days', days), ('jobs', jobs), ('fuel_entries', fuel), ('payslips', payslips))}


def _scope(payload, basis):
    """Source values and membership for this correction, independent of other drivers."""
    kind, mode = payload['kind'], payload['mode']
    rows = basis[_KEYS[kind]] if kind != 'fuel_flag' else basis['days']
    if mode == 'edit':
        selected = [row for row in rows if row['id'] == payload['record_id']]
        related = []
        if kind == 'job':
            related = [row for row in basis['days'] if selected and row['id'] == selected[0]['day_id']]
        elif kind in ('fuel', 'payslip'):
            related = [row for row in basis['days'] if selected and row['id'] == selected[0]['day_id']]
        return {'records': selected, 'days': related}
    driver_id, truck_id, target_date = payload.get('driver_id'), payload.get('truck_id'), payload.get('date')
    if kind == 'day':
        return {'records': [row for row in basis['days'] if row['driver_id'] == driver_id and row['date'] == target_date]}
    if kind == 'job':
        days = [row for row in basis['days'] if row['id'] == payload['day_id']]
        return {'records': [row for row in basis['jobs'] if row['day_id'] == payload['day_id']], 'days': days}
    if kind in ('fuel', 'fuel_flag'):
        return {'records': [row for row in basis['fuel_entries'] if row['truck_id'] == truck_id and row['date'] == target_date],
                'days': [row for row in basis['days'] if row['truck_id'] == truck_id and row['date'] == target_date]}
    return {'records': [row for row in basis['payslips'] if row['driver_id'] == driver_id],
            'days': [row for row in basis['days'] if row['driver_id'] == driver_id]}


def _issue_target(week, issue, basis, fuel_flag=False):
    code = issue.get('code')
    payload = {'v': 1, 'week': week.isoformat()}
    if code == 'missing_day':
        payload.update(kind='day', mode='add', driver_id=issue.get('driver_id'), date=_normal(issue.get('date')))
    elif code == 'working_day_without_earnings':
        record_id = issue.get('record_id')
        day = next((row for row in basis['days'] if row['id'] == record_id), None)
        if not day:
            return None
        payload.update(kind='job', mode='add', day_id=record_id, driver_id=day['driver_id'], date=day['date'])
    elif code == 'missing_fuel_receipt':
        payload.update(kind='fuel_flag' if fuel_flag else 'fuel', mode='add',
                       truck_id=issue.get('truck_id'), date=_normal(issue.get('date')))
    elif code in ('missing_payslip', 'multiple_payslips'):
        days = [row for row in basis['days'] if row['driver_id'] == issue.get('driver_id')]
        if not days and code == 'missing_payslip':
            return None
        target = max((row['date'] for row in days), default=week.isoformat())
        payload.update(kind='payslip', mode='group' if code == 'multiple_payslips' else 'add',
                       driver_id=issue.get('driver_id'), date=target)
    elif issue.get('record_type') in _MODELS and issue.get('record_id'):
        payload.update(kind=issue['record_type'], mode='edit', record_id=issue['record_id'])
    else:
        return None
    if fuel_flag and payload['kind'] != 'fuel_flag':
        return None
    payload['source'] = _digest(_scope(payload, basis))
    return payload


def _make_url(week, issue, report, fuel_flag=False, review_context=None):
    validate_week_start(week)
    if review_context is not None:
        read_review_context(review_context, week=week)
    basis = report.get('review_basis') if report is not None else None
    if basis is None:
        basis = _week_basis(week)
    # Normalize supplied report values without touching the ORM or querying it.
    basis = {key: _rows(basis.get(key, []), fields) for key, fields in _FIELDS.items()}
    payload = _issue_target(week, issue, basis, fuel_flag)
    if payload is None:
        return None
    if review_context is not None:
        payload['review_context'] = review_context
    token = _serializer().dumps(payload)
    kind = 'fuel' if payload['kind'] == 'fuel_flag' else payload['kind']
    item_id = payload.get('record_id', 0)
    return url_for(f'{kind}.add_{kind}', item_id=item_id,
                   tab='edit' if payload['mode'] == 'edit' else 'entry', owner_context=token)


def correction_url(week, issue, report=None, *, review_context=None):
    return _make_url(week, issue, report, review_context=review_context)


def fuel_flag_correction_url(week, issue, report=None, *, review_context=None):
    return _make_url(week, issue, report, fuel_flag=True, review_context=review_context)


def _load_context(kind, item_id, action='entry'):
    token = request.args.get('owner_context') or request.form.get('owner_context')
    if not token:
        return None
    if request.args.get('owner_context') and request.form.get('owner_context') not in (None, '', token):
        abort(400, 'Conflicting correction contexts.')
    try:
        payload = _serializer().loads(token, max_age=7 * 24 * 60 * 60)
        if not isinstance(payload, dict) or payload.get('v') != 1:
            raise ValueError()
        selected_week = date.fromisoformat(payload['week'])
        validate_week_start(selected_week)
        if payload['week'] != selected_week.isoformat():
            raise ValueError()
        if 'review_context' in payload:
            read_review_context(payload['review_context'], week=selected_week)
        context_kind, mode = payload['kind'], payload['mode']
        if context_kind not in (*_MODELS, 'fuel_flag') or mode not in ('add', 'edit', 'group'):
            raise ValueError()
        if ('fuel' if context_kind == 'fuel_flag' else context_kind) != kind:
            raise ValueError()
        for key in ('driver_id', 'truck_id', 'record_id', 'day_id'):
            if key in payload and (type(payload[key]) is not int or payload[key] <= 0):
                raise ValueError()
        if mode == 'edit' and item_id != payload['record_id']:
            raise ValueError()
        if mode != 'edit' and item_id != 0 and not (mode == 'group' and action == 'delete'):
            raise ValueError()
        if 'date' in payload:
            target_date = date.fromisoformat(payload['date'])
            if not selected_week <= target_date <= week_end(selected_week):
                raise ValueError()
        if not isinstance(payload['source'], str) or len(payload['source']) != 64:
            raise ValueError()
    except (BadData, ValueError, TypeError, KeyError, OverflowError):
        abort(400, 'Invalid or expired correction. Reopen it from Data Checks.')
    basis = _week_basis(selected_week)
    if _digest(_scope(payload, basis)) != payload['source']:
        abort(409, 'This record has changed or moved. Reopen the correction from Data Checks.')
    scope = _scope(payload, basis)
    if mode == 'edit' and len(scope['records']) != 1:
        abort(409, 'The original record is no longer in this week.')
    if mode == 'group' and action == 'delete' and item_id not in {row['id'] for row in scope['records']}:
        abort(400, 'This payslip is outside the selected correction.')
    return token, payload, selected_week, basis, scope


def _return(week, payload):
    return redirect(checks_url(week, payload.get('review_context')), code=303)


def _decimal_value(name):
    value = request.form.get(name, '').strip()
    try:
        parsed = Decimal(value)
        if not parsed.is_finite() or parsed != parsed.quantize(Decimal('.01')):
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise ValueError(f'Please enter {name.replace("_", " ")} as a number with at most two decimal places.')
    return value


def _store_number(entry, field, value):
    # Reuse the model's range/status validation, then retain exact integer pence
    # (or hundredths of a litre/mile). The legacy float converter can otherwise
    # produce e.g. 14511.000000000002 for an input of 145.11. Assignment above
    # has already recorded the SQLAlchemy change history before normalization.
    setattr(entry, field, value)
    entry.__dict__[field] = int(Decimal(str(value)) * 100)


def _submitted_target(payload, week):
    """Corrections cannot silently become a different driver/truck/date record."""
    kind, mode = payload['kind'], payload['mode']
    if kind == 'fuel_flag':
        return
    raw_date = request.form.get('date_cd' if kind == 'job' else 'date', '')
    try:
        submitted_date = f.date_to_db(raw_date)
    except (TypeError, ValueError):
        raise ValueError('Please enter a valid date.')
    if not week <= submitted_date <= week_end(week):
        raise ValueError('Keep the correction within the selected payroll week.')
    if mode == 'add' and submitted_date.isoformat() != payload['date']:
        raise ValueError('Use the date selected by this check.')
    if kind in ('day', 'job', 'payslip'):
        try:
            selected_driver = int(request.form.get('driver_id', ''))
        except (ValueError, TypeError):
            raise ValueError('Please select a driver.')
        if mode == 'add' and selected_driver != payload['driver_id']:
            raise ValueError('Use the driver selected by this check.')
    if kind == 'fuel' and mode == 'add':
        if request.form.get('truck_id') != str(payload['truck_id']):
            raise ValueError('Use the truck selected by this check.')
    if kind == 'job' and request.form.get('split'):
        raise ValueError('Split-job allocations need to be reviewed together; this correction does not split jobs.')


def _save(payload, basis, week, item_id):
    kind, mode = payload['kind'], payload['mode']
    _submitted_target(payload, week)
    if kind in ('day', 'job', 'payslip') and mode == 'edit':
        source = _scope(payload, basis)
        original = source['days'][0] if kind == 'job' else source['records'][0]
        if request.form.get('driver_id') != str(original['driver_id']):
            raise ValueError('Keep the driver recorded on this entry. Reopen another record to correct a different driver.')
    if kind == 'fuel_flag':
        days = _scope(payload, basis)['days']
        if _scope(payload, basis)['records']:
            raise ValueError('A fuel receipt has already been recorded for this truck and date.')
        for row in days:
            entry = db.session.get(Day, row['id'])
            entry.fuel = ''
        return
    entry = db.session.get(_MODELS[kind], item_id) if mode == 'edit' else None
    if kind == 'day':
        status = request.form.get('status')
        if status not in ('working', 'holiday', 'absent'):
            raise ValueError('Please select Working, Holiday or Absent.')
        if entry is None:
            entry = Day()
        entry.date = request.form.get('date')
        entry.driver_id = request.form.get('driver_id')
        entry.status = status
        if status == 'working':
            entry.truck_id = request.form.get('truck_id')
            entry.overnight = request.form.get('overnight')
            entry.fuel = request.form.get('fuel')
            for field in ('start_mileage', 'end_mileage', 'additional_earned', 'additional_wages'):
                _store_number(entry, field, _decimal_value(field) if request.form.get(field) else '0')
        else:
            entry.truck_id = None
            entry.overnight = None
            entry.fuel = None
            entry.start_mileage = '0'
            entry.end_mileage = '0'
            entry.additional_earned = '0'
            entry.additional_wages = '0'
    elif kind == 'job':
        if entry is not None and entry.split:
            raise ValueError('Split-job allocations must be reviewed together and are read-only here.')
        day = db.session.execute(select(Day).where(Day.date == f.date_to_db(request.form['date_cd']),
                                                 Day.driver_id == request.form.get('driver_id'))).scalar_one_or_none()
        if day is None or day.status != 'working':
            raise ValueError('A Working day entry is required for the selected driver and date.')
        entry = entry if entry is not None else Job()
        entry.day_id = day.id
        _store_number(entry, 'earned', _decimal_value('earned'))
        entry.collection = request.form.get('collection')
        entry.delivery = request.form.get('delivery')
        entry.notes = request.form.get('notes')
        entry.split = None
    elif kind == 'fuel':
        entry = entry if entry is not None else Fuel()
        entry.date = request.form.get('date')
        entry.truck_id = request.form.get('truck_id')
        if db.session.get(Truck, int(entry.truck_id)) is None:
            raise ValueError('Please select an existing truck.')
        entry.fuel_card_name = request.form.get('fuel_card_name', '').strip()
        if not entry.fuel_card_name or len(entry.fuel_card_name) > 50:
            raise ValueError('Please select a fuel card.')
        _store_number(entry, 'fuel_volume', _decimal_value('fuel_volume'))
        _store_number(entry, 'fuel_cost', _decimal_value('fuel_cost'))
        matching = db.session.execute(select(Day.id).where(Day.date == entry.date, Day.truck_id == entry.truck_id)
                                      .order_by(Day.id).limit(2)).scalars().all()
        entry.day_id = matching[0] if len(matching) == 1 else None
    else:
        entry = entry if entry is not None else Payslip()
        entry.date = request.form.get('date')
        entry.driver_id = int(request.form.get('driver_id'))
        if db.session.get(Driver, entry.driver_id) is None:
            raise ValueError('Please select an existing driver.')
        others = db.session.execute(select(Payslip.id).where(Payslip.driver_id == entry.driver_id,
                    Payslip.date.between(week, week_end(week)), Payslip.id != (entry.id or 0))).scalars().all()
        if others:
            raise ValueError('Another payslip exists in this payroll week. Review it before saving.')
        _store_number(entry, 'total_wage', _decimal_value('total_wage'))
        _store_number(entry, 'total_cost_to_employer', _decimal_value('total_cost_to_employer'))
        day = db.session.execute(select(Day.id).where(Day.date == entry.date, Day.driver_id == entry.driver_id)).scalar_one_or_none()
        entry.day_id = day
    db.session.add(entry)


def _render(context, error=None):
    # Include reused macros and the application's notification context processor
    # in the read-only scope as well as the bounded source queries.
    with db.session.no_autoflush:
        return _render_form(context, error=error)


def _render_form(context, error=None):
    token, payload, week, basis, scope = context
    kind, mode = payload['kind'], payload['mode']
    form = CorrectionForm()
    form.owner_context.data = token
    entry = None
    values = {}
    if mode == 'edit':
        entry = db.session.get(_MODELS[kind], payload['record_id'])
        values = entry
    elif mode == 'add' and kind != 'fuel_flag':
        values = {key: payload[key] for key in ('driver_id', 'truck_id', 'date') if key in payload}
        if kind == 'job':
            values['date_cd'] = values.pop('date')
        if kind == 'day':
            values['status'] = 'working'
    drivers = []
    trucks = []
    driver_id = payload.get('driver_id')
    if entry is not None and kind == 'job':
        driver_id = entry.day.driver_id
    elif entry is not None and kind in ('day', 'payslip'):
        driver_id = entry.driver_id
    if driver_id is not None:
        driver = db.session.get(Driver, driver_id)
        if driver is not None:
            drivers.append(driver)
    if kind in ('day', 'fuel'):
        trucks = db.session.execute(select(Truck).order_by(Truck.registration)).scalars().all()
    if request.method == 'POST' and error:
        # Posted monetary values are pounds already; do not divide them again.
        values = request.form
    split_read_only = kind == 'job' and entry is not None and entry.split
    group_rows = []
    if mode == 'group':
        for row in scope['records']:
            issue = {'code': 'payslip_amount_out_of_range', 'record_type': 'payslip', 'record_id': row['id']}
            group_rows.append(dict(row, edit_url=correction_url(week, issue, {'review_basis': basis},
                                                               review_context=payload.get('review_context'))))
    return render_template('owner_correction_entry.html', kind=kind, mode=mode, entry=entry, values=values,
            drivers=drivers, trucks=trucks, form=form, token=token, week=week, week_end=week_end(week),
            back_url=checks_url(week, payload.get('review_context')),
            error=error, split_read_only=split_read_only, group_rows=group_rows,
            macro_type='edit' if mode == 'edit' and not error else 'add',
            action=url_for(f'{"fuel" if kind == "fuel_flag" else kind}.add_{"fuel" if kind == "fuel_flag" else kind}',
                           item_id=payload.get('record_id', 0), tab='edit' if mode == 'edit' else 'entry', owner_context=token))


def owner_entry_response(kind, item_id, tab):
    context = _load_context(kind, item_id)
    if context is None:
        return None
    token, payload, week, basis, scope = context
    if request.method == 'POST':
        form = CorrectionForm()
        if not form.validate_on_submit():
            abort(400, 'Invalid correction form. Reload the page and try again.')
        if payload['mode'] == 'group':
            abort(400, 'Select an individual payslip to change.')
        try:
            with db.session.no_autoflush:
                _save(payload, basis, week, item_id)
            db.session.commit()
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            message = str(error) if isinstance(error, ValueError) else 'A conflicting entry already exists. Reopen Data Checks to check it.'
            return _render(context, error=message), 400
        flash('Correction saved. The weekly figures and checks have been refreshed.', 'success-msg')
        return _return(week, payload)
    return _render(context)


def owner_mutation_response(kind, item_id, action='edit'):
    context = _load_context(kind, item_id, action=action)
    if context is None:
        return None
    if action != 'delete':
        # The bounded form uses its own POST path, never the broad legacy editor.
        return owner_entry_response(kind, item_id, 'edit')
    _, payload, week, _, _ = context
    form = CorrectionForm()
    if not form.validate_on_submit():
        abort(400, 'Invalid correction form. Reload the page and try again.')
    if kind != 'payslip' or payload['mode'] != 'group':
        abort(400, 'Only a duplicate payslip selected in this correction can be deleted.')
    entry = db.session.get(Payslip, item_id)
    db.session.delete(entry)
    db.session.commit()
    flash('Duplicate payslip deleted. Review the refreshed weekly figures.', 'success-msg')
    return _return(week, payload)
