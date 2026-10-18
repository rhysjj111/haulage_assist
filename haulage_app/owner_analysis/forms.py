"""CSRF-protected forms for explicit owner review actions."""

from flask_wtf import FlaskForm
from wtforms import DateField, DecimalField, HiddenField, IntegerField, SelectField, TextAreaField
from wtforms.validators import AnyOf, InputRequired, Length, NumberRange, Optional, ValidationError
from wtforms.widgets import HiddenInput

from haulage_app.owner_analysis.dates import validate_week_start, week_end


def _allowance(form, field):
    value = field.data
    if value is None or not value.is_finite():
        raise ValidationError("Enter a finite weekly allowance.")
    if value < 0 or value * 100 > 2147483647:
        raise ValidationError("Enter a nonnegative allowance within the permitted range.")
    if value.as_tuple().exponent < -2:
        raise ValidationError("Use no more than two decimal places.")


def _effective_week(form, field):
    try:
        validate_week_start(field.data)
        week_end(field.data)
    except (TypeError, ValueError, OverflowError):
        raise ValidationError("Choose a Saturday as the first affected payroll week.") from None


class ReviewContextForm(FlaskForm):
    review_context = HiddenField(validators=[Optional(), Length(max=4096)])


class OverheadSettingsForm(ReviewContextForm):
    selected_week = HiddenField(validators=[InputRequired()])
    effective_week_start = DateField("Applies from week beginning (Saturday)", validators=[InputRequired(), _effective_week])
    truck_count = IntegerField("Truck count", validators=[InputRequired(), NumberRange(min=0, max=2147483647)])
    allowance_per_truck = DecimalField("Weekly allowance per truck (£)", places=None,
                                       validators=[InputRequired(), _allowance])
    fingerprint = HiddenField(validators=[InputRequired(), Length(min=64, max=64)])


class IssueVerificationForm(ReviewContextForm):
    week_start = HiddenField(validators=[InputRequired()])
    issue_key = HiddenField(validators=[InputRequired(), Length(max=255)])
    fingerprint = HiddenField(validators=[InputRequired(), Length(min=64, max=64)])
    decision = SelectField("Decision", choices=[("verified", "Verified"),
                                                ("confirmed_zero", "Confirmed no employer wage cost"),
                                                ("dismissed", "Dismissed with explanation"),
                                                ("awaiting_invoice", "Awaiting fuel invoice")])
    note = TextAreaField("What was checked?", validators=[InputRequired(), Length(max=4000)])


class WeekNoteForm(ReviewContextForm):
    week_start = HiddenField(validators=[InputRequired()])
    fingerprint = HiddenField(validators=[InputRequired(), Length(min=64, max=64)])
    scope_key = HiddenField(default="week_note", validators=[InputRequired(), Length(max=255)])
    note = TextAreaField("Brief note", validators=[InputRequired(), Length(max=4000)])


class WeekReviewForm(ReviewContextForm):
    week_start = HiddenField(validators=[InputRequired()])
    fingerprint = HiddenField(validators=[InputRequired(), Length(min=64, max=64)])
    review_id = IntegerField(widget=HiddenInput(), validators=[InputRequired(), NumberRange(min=0)])
    action = HiddenField(validators=[InputRequired(), AnyOf(["check", "undo"])])


class AbsenceForm(ReviewContextForm):
    week_start = HiddenField(validators=[InputRequired()])
    fingerprint = HiddenField(validators=[InputRequired(), Length(min=64, max=64)])
    driver_id = IntegerField(widget=HiddenInput(),
                             validators=[InputRequired(), NumberRange(min=1, max=2147483647)])
    absent_date = DateField("Date", validators=[InputRequired()])
    status = SelectField("Day status", choices=[("holiday", "Holiday"), ("absent", "Absent")],
                         validators=[InputRequired()])
    note = TextAreaField("Brief explanation", validators=[InputRequired(), Length(max=4000)])
