"""Weekly/monthly owner reporting and explicit, version-checked review actions."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import re
from zoneinfo import ZoneInfo

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from haulage_app import db
from haulage_app.models import Day, Driver, Truck
from haulage_app.owner_analysis import owner_analysis_bp
from haulage_app.owner_analysis.breakdowns import build_breakdown
from haulage_app.owner_analysis.corrections import correction_url, fuel_flag_correction_url
from haulage_app.owner_analysis.dates import (
    payroll_month_for_week, payroll_week_start, payroll_weeks_for_month,
    shift_month, validate_week_start, week_end,
)
from haulage_app.owner_analysis.forms import (
    AbsenceForm, IssueVerificationForm, OverheadSettingsForm, WeekNoteForm, WeekReviewForm,
)
from haulage_app.owner_analysis.overheads import (
    ensure_weekly_overhead, get_weekly_overhead, overhead_settings_fingerprint, set_overhead_settings,
)
from haulage_app.owner_analysis.models import OwnerOverheadSetting
from haulage_app.owner_analysis.overhead_presentation import build_overhead_basis
from haulage_app.owner_analysis.reviews import (
    get_reviewed_week, save_issue_verification, save_week_note, save_week_review,
)


def today_london():
    return datetime.now(ZoneInfo("Europe/London")).date()


def _parse_week(value, *, normalize=False):
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("Please select a valid week.") from None
    return payroll_week_start(parsed) if normalize else validate_week_start(parsed)


def _back(week):
    return redirect(url_for("owner_analysis.weekly", week_start=week.isoformat()), code=303)


def _adjacent_week(week, offset):
    try:
        target = week + timedelta(days=offset)
        week_end(target)
        return target.isoformat()
    except (ValueError, OverflowError):
        return None


def _post(form, action, message):
    fallback = payroll_week_start(today_london())
    field = "selected_week" if hasattr(form, "selected_week") else "week_start"
    try:
        week = _parse_week(request.form.get(field))
    except (ValueError, OverflowError) as exc:
        flash(str(exc), "error-msg")
        return _back(fallback)
    if not form.validate_on_submit():
        errors = [error for messages in form.errors.values() for error in messages]
        flash(" ".join(errors) or "Please check the form and try again.", "error-msg")
        return _back(week)
    try:
        action(week)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error-msg")
    except IntegrityError:
        db.session.rollback()
        flash("The entry changed or already exists. Refresh the week and check it again.", "error-msg")
    else:
        flash(message, "success-msg")
    return _back(week)


_ISSUE_LABELS = {
    "missing_day": "Missing day", "working_day_without_earnings": "Working day without earnings",
    "missing_fuel_receipt": "Missing fuel receipt", "missing_payslip": "Missing employer wage cost",
    "multiple_payslips": "Multiple payslips", "missing_overhead_settings": "Overheads need setting",
    "mileage_end_before_start": "Mileage needs checking", "missing_mileage": "Missing mileage",
    "working_day_without_truck": "Truck needs checking", "fuel_flag_without_truck": "Fuel purchase without a truck",
    "earnings_on_nonworking_day": "Earnings on a non-working day", "job_amount_out_of_range": "Job amount needs checking",
    "fuel_amount_out_of_range": "Fuel amount needs checking", "payslip_amount_out_of_range": "Payslip amount needs checking",
    "employer_cost_below_wage": "Employer cost needs checking", "invalid_day_status": "Day status needs correcting",
}


def _label_history(report):
    subjects = []
    for item in report["verification_history"]:
        parts = item["scope_key"].split(":")
        details = dict(part.split("=", 1) for part in parts[2:] if "=" in part)
        subjects.append((item, parts[0], details))
    driver_ids = {int(d["driver_id"]) for _, _, d in subjects if d.get("driver_id", "").isdigit()}
    truck_ids = {int(d["truck_id"]) for _, _, d in subjects if d.get("truck_id", "").isdigit()}
    driver_names, truck_names = dict(report["driver_names"]), dict(report["truck_names"])
    with db.session.no_autoflush:
        if driver_ids - driver_names.keys():
            driver_names.update({row.id: row.full_name for row in Driver.query.filter(Driver.id.in_(driver_ids - driver_names.keys()))})
        if truck_ids - truck_names.keys():
            truck_names.update({row.id: row.registration for row in Truck.query.filter(Truck.id.in_(truck_ids - truck_names.keys()))})
    for item, code, details in subjects:
        item["label"] = {"week_note": "Week note", "week_review": "Week reviewed",
                         "recorded_absence": "Holiday or absence recorded"}.get(code, _ISSUE_LABELS.get(code, "Entry checked"))
        labels = []
        for key, names, fallback in (("driver_id", driver_names, "Driver"), ("truck_id", truck_names, "Truck")):
            if details.get(key, "").isdigit():
                identifier = int(details[key])
                labels.append(names.get(identifier, f"{fallback} {identifier}"))
        if details.get("date"):
            try:
                labels.append(date.fromisoformat(details["date"]).strftime("%d %b %Y"))
            except ValueError:
                pass
        item["context_label"] = " · ".join(labels)


def _prepare_week_presentation(report, *, correction_links=False):
    week = report["week_start"]
    for issue in report["issues"]:
        issue["label"] = _ISSUE_LABELS.get(issue["code"], "Entry needs checking")
        issue["context_label"] = issue.get("record_label") or " · ".join(str(value) for value in (
            issue.get("driver_name"), issue.get("truck_registration"),
            issue.get("date").strftime("%d %b %Y") if issue.get("date") else None) if value)
        if correction_links:
            issue["correction_url"] = url_for("owner_analysis.overhead_settings", week_start=week.isoformat()) if issue["code"] == "missing_overhead_settings" else correction_url(week, issue, report=report)
            issue["fuel_flag_correction_url"] = fuel_flag_correction_url(week, issue, report=report) if issue["code"] == "missing_fuel_receipt" else None
        issue["can_confirm_zero"] = "confirmed_zero" in issue.get("verification_decisions", [])
        issue["can_mark_absence"] = issue["code"] == "missing_day"
    outstanding_keys = {item["key"] for item in report["outstanding_issues"]}
    report["outstanding_issues"] = [item for item in report["issues"] if item["key"] in outstanding_keys]
    report["can_review"] = report["period_state"] == "finished" and not report["outstanding_issues"]
    report["payroll_pending"] = any(item["code"] in {"missing_payslip", "multiple_payslips"} for item in report["outstanding_issues"])
    report["fuel_pending"] = any(item["code"] in {"missing_fuel_receipt", "fuel_flag_without_truck"} for item in report["outstanding_issues"])
    for name in ("reviewed_at", "last_reviewed_at"):
        value = report.get(name)
        if value is not None:
            report[name] = (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(ZoneInfo("Europe/London"))
    for item in report["verification_history"]:
        value = item["created_at"]
        item["created_at"] = (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(ZoneInfo("Europe/London"))
        item["created_at_label"] = item["created_at"].strftime("%d %b %Y at %H:%M")
    _label_history(report)
    return report


def _analysis_selection():
    for key in ("view", "driver_id", "truck_id"):
        if len(request.args.getlist(key)) > 1:
            abort(400, description="Please select one analysis view and filter.")
    view = request.args.get("view", "overview")
    if view not in {"overview", "drivers", "trucks"}:
        abort(400, description="Please select a valid analysis view.")
    selected_id = None
    for key, expected_view in (("driver_id", "drivers"), ("truck_id", "trucks")):
        if key not in request.args:
            continue
        value = request.args[key]
        if view == expected_view and value == "all":
            continue
        if view != expected_view or re.fullmatch(r"[1-9][0-9]{0,9}", value) is None or int(value) > 2147483647:
            abort(400, description="Please select a valid driver or truck.")
        selected_id = int(value)
    return view, selected_id


def _analysis_context(report, view, selected_id, *, selected_month=None, chosen_week=None):
    monthly_view = "weeks" in report
    endpoint = "owner_analysis.monthly" if monthly_view else "owner_analysis.weekly"
    period_args = {"month": selected_month, "week_start": chosen_week.isoformat()} if monthly_view else {"week_start": report["week_start"].isoformat()}
    view_args = {"view": view} if view != "overview" else {}
    breakdown = None
    if view != "overview":
        kind = "driver" if view == "drivers" else "truck"
        selected_label = None
        if selected_id is not None:
            view_args[f"{kind}_id"] = selected_id
            row = report[view].get(selected_id)
            if row is not None:
                selected_label = row["driver_name" if kind == "driver" else "truck_registration"]
            else:
                with db.session.no_autoflush:
                    entity = db.session.get(Driver if kind == "driver" else Truck, selected_id)
                if entity is None:
                    abort(404, description="That driver or truck could not be found.")
                selected_label = entity.full_name if kind == "driver" else entity.registration
        breakdown = build_breakdown(report, kind, selected_id=selected_id, selected_label=selected_label)
        weeks = report["weeks"] if monthly_view else [report]
        breakdown["weekly_links"] = [{"week_start": item["week_start"], "week_end": item["week_end"],
            "review_status": item["review_status"], "url": url_for("owner_analysis.weekly", week_start=item["week_start"].isoformat())} for item in weeks]
        breakdown["filter_action"] = url_for(endpoint)
        breakdown["filter_fields"] = dict(period_args, view=view)
    return {"analysis_view": view, "view_args": view_args, "breakdown": breakdown,
            "view_links": {name: url_for(endpoint, **period_args, **({"view": name} if name != "overview" else {}))
                           for name in ("overview", "drivers", "trucks")}}


@owner_analysis_bp.route("/owner-analysis", methods=["GET"])
def weekly():
    view, selected_id = _analysis_selection()
    today = today_london()
    current = payroll_week_start(today)
    try:
        week = _parse_week(request.args.get("week_start", current.isoformat()), normalize=True)
        week_end(week)
    except (ValueError, OverflowError) as exc:
        abort(400, description=str(exc))
    report = _prepare_week_presentation(get_reviewed_week(week, as_of=today), correction_links=view == "overview")
    assigned_month = payroll_month_for_week(week)
    selected_month = f"{assigned_month.year:04d}-{assigned_month.month:02d}"
    # Shared notification context processors also query the database while
    # rendering. Keep the entire read-only response inside this guard.
    with db.session.no_autoflush:
        return render_template("owner_analysis/weekly.html", report=report,
            previous_week=_adjacent_week(week, -7), next_week=_adjacent_week(week, 7), current_week=current.isoformat(),
            selected_month=selected_month, verification_form=IssueVerificationForm(),
            overhead_basis=build_overhead_basis([report]),
            settings_url=url_for("owner_analysis.overhead_settings", week_start=week.isoformat()),
            note_form=WeekNoteForm(data={"week_start": week.isoformat(), "fingerprint": report["week_fingerprint"], "scope_key": "week_note"}),
            review_form=WeekReviewForm(data={"week_start": week.isoformat(), "fingerprint": report["week_fingerprint"]}),
            absence_form=AbsenceForm(), **_analysis_context(report, view, selected_id))


def _month_key(value):
    return f"{value.year:04d}-{value.month:02d}" if value is not None else None


@owner_analysis_bp.route("/owner-analysis/monthly", methods=["GET"])
def monthly():
    from haulage_app.owner_analysis.monthly import get_monthly_report
    view, selected_id = _analysis_selection()
    today = today_london()
    selected_month = request.args.get("month", _month_key(today))
    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}", selected_month) is None:
            raise ValueError()
        selected = date.fromisoformat(selected_month + "-01")
        report = get_monthly_report(selected.year, selected.month, as_of=today)
    except (TypeError, ValueError, OverflowError):
        abort(400, description="Please select a valid month.")
    def adjacent(offset):
        try:
            candidate = shift_month(selected, offset)
            starts = payroll_weeks_for_month(candidate.year, candidate.month)
            week_end(starts[-1])
            return _month_key(candidate)
        except (ValueError, OverflowError):
            return None
    for item in report["weeks"]:
        _prepare_week_presentation(item)
    chosen_week = report.get("active_week") or (report["weeks"][-1]["week_start"] if report["weeks"] else report["expected_week_starts"][0])
    if request.args.get("week_start"):
        try:
            candidate = _parse_week(request.args["week_start"], normalize=True)
            if candidate in report["expected_week_starts"]:
                chosen_week = candidate
        except (ValueError, OverflowError):
            pass
    with db.session.no_autoflush:
        return render_template("owner_analysis/monthly.html", report=report, selected_month=selected_month,
            previous_month=adjacent(-1), next_month=adjacent(1), current_month=_month_key(today),
            overhead_basis=build_overhead_basis(report["weeks"]),
            settings_url=url_for("owner_analysis.overhead_settings", week_start=chosen_week.isoformat(), month=selected_month),
            weekly_toggle_week=chosen_week.isoformat(), **_analysis_context(report, view, selected_id,
            selected_month=selected_month, chosen_week=chosen_week))


def _settings_month():
    """Keep return navigation within a validated, local report period."""
    if len(request.args.getlist("month")) > 1:
        abort(400, description="Please select one return month.")
    value = request.args.get("month")
    if value is not None:
        try:
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}", value) is None:
                raise ValueError()
            selected = date.fromisoformat(value + "-01")
            week_end(payroll_weeks_for_month(selected.year, selected.month)[-1])
        except (TypeError, ValueError, OverflowError):
            abort(400, description="Please select a valid return month.")
    return value


def _settings_url(week, month=None):
    return url_for("owner_analysis.overhead_settings", week_start=week.isoformat(),
                   **({"month": month} if month is not None else {}))


def _render_overhead_settings(selected_week, *, month=None, form=None, save_error=None, status=200):
    # Notification context processors query while rendering, too. Keep this
    # entire GET/error response read-only, including any pending source edits.
    with db.session.no_autoflush:
        current_week = payroll_week_start(today_london())
        rows = OwnerOverheadSetting.query.order_by(OwnerOverheadSetting.effective_week_start.desc()).all()
        sources = {row.id: row for row in rows}

        def values_for(week):
            effective = get_weekly_overhead(week)
            if effective is None:
                return None
            source = sources[effective.source_setting_id]
            return {"effective_week_start": source.effective_week_start,
                    "truck_count": effective.truck_count,
                    "allowance_per_truck": effective.allowance_per_truck,
                    "total": effective.total}

        current_setting = values_for(current_week)
        selected_setting = values_for(selected_week)
        active = next((row for row in rows if row.effective_week_start <= current_week), None)
        history = [{"effective_week_start": row.effective_week_start,
                    "truck_count": row.truck_count, "allowance_per_truck": row.allowance_per_truck,
                    "total": row.total,
                    "status": "scheduled" if row.effective_week_start > current_week else
                              "current" if row is active else "previous"} for row in rows]
        if form is None:
            form = OverheadSettingsForm(data={
                "selected_week": selected_week.isoformat(), "effective_week_start": current_week,
                "fingerprint": overhead_settings_fingerprint(),
                "truck_count": current_setting["truck_count"] if current_setting is not None else 4,
                "allowance_per_truck": Decimal(current_setting["allowance_per_truck"]) / 100
                                       if current_setting is not None else None,
            })
        return render_template("owner_analysis/overheads.html", overhead_form=form,
            current_week=current_week, selected_week=selected_week, current_setting=current_setting,
            selected_setting=selected_setting, settings_history=history, save_error=save_error,
            settings_url=_settings_url(selected_week, month),
            form_action=url_for("owner_analysis.save_overheads", **({"month": month} if month is not None else {})),
            back_url=url_for("owner_analysis.monthly", month=month, week_start=selected_week.isoformat())
                     if month is not None else url_for("owner_analysis.weekly", week_start=selected_week.isoformat()),
            back_label="Back to monthly analysis" if month is not None else "Back to weekly analysis"), status


@owner_analysis_bp.route("/owner-analysis/overheads", methods=["GET"])
def overhead_settings():
    if len(request.args.getlist("week_start")) > 1:
        abort(400, description="Please select one report week.")
    try:
        selected_week = _parse_week(request.args.get("week_start", payroll_week_start(today_london()).isoformat()), normalize=True)
        week_end(selected_week)
    except (ValueError, OverflowError) as exc:
        abort(400, description=str(exc))
    return _render_overhead_settings(selected_week, month=_settings_month())


@owner_analysis_bp.route("/owner-analysis/overheads", methods=["POST"])
def save_overheads():
    month = _settings_month()
    form = OverheadSettingsForm()
    try:
        selected_week = _parse_week(form.selected_week.data)
        week_end(selected_week)
    except (ValueError, OverflowError):
        flash("Please reopen the settings page and select a valid report week.", "error-msg")
        return redirect(_settings_url(payroll_week_start(today_london()), month), code=303)
    if not form.validate_on_submit():
        return _render_overhead_settings(selected_week, month=month, form=form, status=400)
    try:
        if form.fingerprint.data != overhead_settings_fingerprint():
            raise ValueError("Overhead settings have changed since this form opened. Refresh the settings and review the changes before saving.")
        set_overhead_settings(form.effective_week_start.data, form.truck_count.data,
                              int(form.allowance_per_truck.data * 100))
        # The selected report week is only return context. A change creates a
        # snapshot for its actual first affected week, never an unrelated week.
        ensure_weekly_overhead(form.effective_week_start.data)
        db.session.commit()
    except (ValueError, OverflowError) as exc:
        db.session.rollback()
        return _render_overhead_settings(selected_week, month=month, form=form, save_error=str(exc), status=409)
    except IntegrityError:
        db.session.rollback()
        return _render_overhead_settings(selected_week, month=month, form=form,
            save_error="The settings changed while you were saving. Refresh the settings and check the history before trying again.", status=409)
    flash("Overhead settings saved from the selected starting week.", "success-msg")
    return redirect(_settings_url(selected_week, month), code=303)


@owner_analysis_bp.route("/owner-analysis/verify", methods=["POST"])
def verify_issue():
    form = IssueVerificationForm()
    return _post(form, lambda week: save_issue_verification(week, form.issue_key.data, form.note.data,
        form.fingerprint.data, decision=form.decision.data, as_of=today_london()), "Verification and explanation saved.")


@owner_analysis_bp.route("/owner-analysis/note", methods=["POST"])
def week_note():
    form = WeekNoteForm()
    return _post(form, lambda week: save_week_note(week, form.note.data, form.fingerprint.data,
        scope_key=form.scope_key.data, as_of=today_london()), "Week note saved.")


@owner_analysis_bp.route("/owner-analysis/review", methods=["POST"])
def review_week():
    form = WeekReviewForm()
    return _post(form, lambda week: save_week_review(week, form.fingerprint.data,
        note=form.note.data or "", as_of=today_london()), "Week marked reviewed.")


@owner_analysis_bp.route("/owner-analysis/absence", methods=["POST"])
def record_absence():
    form = AbsenceForm()
    def save(week):
        report = get_reviewed_week(week, as_of=today_london())
        issue = next((item for item in report["outstanding_issues"] if item["code"] == "missing_day"
            and item.get("driver_id") == form.driver_id.data and item.get("date") == form.absent_date.data), None)
        if issue is None or issue["fingerprint"] != form.fingerprint.data:
            raise ValueError("This day or its source records have changed. Reload the week before recording an absence.")
        db.session.execute(Day.__table__.insert().values(date=form.absent_date.data, driver_id=form.driver_id.data,
            truck_id=None, status=form.status.data, start_mileage=0, end_mileage=0, fuel=False,
            overnight=False, additional_earned=0, additional_wages=0))
        updated = get_reviewed_week(week, as_of=today_london())
        scope = f"recorded_absence:{week.isoformat()}:driver_id={form.driver_id.data}:date={form.absent_date.data.isoformat()}"
        save_week_note(week, form.note.data, updated["week_fingerprint"], scope_key=scope, as_of=today_london())
    return _post(form, save, "Day status and explanation recorded.")
