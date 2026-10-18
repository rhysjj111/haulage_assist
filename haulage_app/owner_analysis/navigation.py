"""Signed, bounded report context for checks and their correction forms.

Only known payroll periods and view/filter values are carried between pages.
No caller-provided URL is ever used as a redirect target.
"""

from datetime import date
import re

from flask import current_app, url_for
from itsdangerous import BadData, URLSafeTimedSerializer

from .dates import payroll_weeks_for_month, validate_week_start, week_end


_MAX_AGE = 8 * 60 * 60
_VIEWS = {'overview', 'drivers', 'trucks'}


def _serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='owner-analysis-navigation-v1')


def _week(value):
    if not isinstance(value, str):
        raise ValueError('Invalid payroll week.')
    parsed = date.fromisoformat(value)
    if value != parsed.isoformat():
        raise ValueError('Invalid payroll week.')
    validate_week_start(parsed)
    week_end(parsed)
    return parsed


def _validate(payload, *, week=None):
    if (not isinstance(payload, dict) or not isinstance(payload.get('period'), str)
            or payload['period'] not in {'weekly', 'monthly'}):
        raise ValueError('Invalid review period.')
    expected = {'period', 'week_start', 'view', 'selected_id'}
    if payload['period'] == 'monthly':
        expected.add('month')
    if set(payload) != expected:
        raise ValueError('Invalid review context.')
    selected_week = _week(payload['week_start'])
    if not isinstance(payload['view'], str) or payload['view'] not in _VIEWS:
        raise ValueError('Invalid analysis view.')
    selected_id = payload['selected_id']
    if selected_id is not None and (type(selected_id) is not int or not 1 <= selected_id <= 2147483647):
        raise ValueError('Invalid analysis filter.')
    if payload['view'] == 'overview' and selected_id is not None:
        raise ValueError('The overview has no driver or truck filter.')
    allowed_weeks = [selected_week]
    if payload['period'] == 'monthly':
        month = payload['month']
        if not isinstance(month, str) or re.fullmatch(r'[0-9]{4}-[0-9]{2}', month) is None:
            raise ValueError('Invalid payroll month.')
        selected_month = date.fromisoformat(month + '-01')
        allowed_weeks = payroll_weeks_for_month(selected_month.year, selected_month.month)
        week_end(allowed_weeks[-1])
        if selected_week not in allowed_weeks:
            raise ValueError('The remembered week is outside the selected payroll month.')
    if week is not None:
        validate_week_start(week)
        week_end(week)
        if week not in allowed_weeks:
            raise ValueError('The correction is outside the selected review period.')
    return dict(payload)


def review_context_for(period, week_start, *, month=None, view='overview', selected_id=None):
    """Sign a canonical report selection; reject unsupported or mixed filters."""
    validate_week_start(week_start)
    payload = {'period': period, 'week_start': week_start.isoformat(),
               'view': view, 'selected_id': selected_id}
    if month is not None:
        payload['month'] = month
    return _serializer().dumps(_validate(payload))


def read_review_context(token, *, week=None):
    """Validate a signed context, optionally binding a correction's payroll week."""
    try:
        if not isinstance(token, str) or not token:
            raise ValueError('Missing review context.')
        payload = _serializer().loads(token, max_age=_MAX_AGE)
        return _validate(payload, week=week)
    except (BadData, KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError('Invalid or expired Data Checks context. Reopen the check.') from error


def _destination(week, token, *, checks):
    validate_week_start(week)
    week_end(week)
    context = read_review_context(token, week=week) if token is not None else {
        'period': 'weekly', 'week_start': week.isoformat(), 'view': 'overview', 'selected_id': None,
    }
    monthly = context['period'] == 'monthly'
    endpoint = ('owner_analysis.monthly_checks' if monthly else 'owner_analysis.checks') if checks else (
        'owner_analysis.monthly' if monthly else 'owner_analysis.weekly')
    args = {'week_start': context['week_start'], 'view': context['view']}
    if monthly:
        args['month'] = context['month']
    if context['selected_id'] is not None:
        args['driver_id' if context['view'] == 'drivers' else 'truck_id'] = context['selected_id']
    if checks:
        args['_anchor'] = 'week-' + week.isoformat()
    return url_for(endpoint, **args)


def checks_url(week, token=None):
    """Return a local checks URL with the originating report selection."""
    return _destination(week, token, checks=True)


def analysis_url(week, token=None):
    """Return a local analysis URL with the originating report selection."""
    return _destination(week, token, checks=False)
