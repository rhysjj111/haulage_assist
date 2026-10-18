"""Append-only owner explanations tied to the relevant actual source values."""

from datetime import date, datetime
import hashlib
import json
import re

from haulage_app import db
from haulage_app.owner_analysis.calculations import calculate_weekly_report
from haulage_app.owner_analysis.models import OwnerIssueVerification, OwnerWeekReview, _review_note
from haulage_app.owner_analysis.policy import (
    FUEL_PRICE_MAX_PENCE_PER_LITRE, FUEL_PRICE_MIN_PENCE_PER_LITRE,
    OPTIONAL_ISSUES, PAYROLL_GAP_MIN_PENCE, PAYROLL_GAP_MULTIPLIER,
    normalize_fuel_provider, review_schedule,
)

RULE_VERSION = 1
VERIFIABLE_ISSUES = {
    "working_day_without_earnings", "working_day_without_truck", "missing_mileage",
    "mileage_end_before_start", "earnings_on_nonworking_day", "job_amount_out_of_range",
    "fuel_amount_out_of_range", "payslip_amount_out_of_range", "employer_cost_below_wage", "multiple_payslips",
    "fuel_price_unusual", "possible_duplicate_fuel", "payroll_gap_unusual",
}
RESOLVING_DECISIONS = {"verified", "confirmed_zero", "dismissed"}
AWAITING_INVOICE_ISSUES = {"missing_fuel_receipt", "fuel_flag_without_truck"}


def _canonical(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple, set)):
        items = [_canonical(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()


def _details(scope_key):
    parts = scope_key.split(":")
    result = {"code": parts[0]}
    for part in parts[2:]:
        if "=" in part:
            name, value = part.split("=", 1)
            result[name] = int(value) if name.endswith("_id") else value
    return result


def _fields(rows, names):
    return [{name: row.get(name) for name in names} for row in rows]


def _scope_basis(report, scope_key):
    basis = report["review_basis"]
    if scope_key in {"week", "week_note"}:
        return basis
    details = _details(scope_key)
    code = details["code"]
    driver_id, truck_id = details.get("driver_id"), details.get("truck_id")
    target_date, record_id = details.get("date"), details.get("record_id")
    days = basis["days"]
    selected = [row for row in days if (driver_id is None or row["driver_id"] == driver_id)
                and (target_date is None or row["date"] == target_date)]
    if code == "recorded_absence":
        return _fields(selected, ("id", "date", "driver_id", "status"))
    employment = [row for row in basis["employment_periods"] if row["driver_id"] == driver_id]
    day_ids = {row["id"] for row in selected}
    jobs = [row for row in basis["jobs"] if row["day_id"] in day_ids]
    if code in {"missing_mileage", "mileage_end_before_start"}:
        return _fields(selected, ("id", "date", "driver_id", "truck_id", "status", "start_mileage", "end_mileage"))
    if code == "working_day_without_truck":
        return _fields(selected, ("id", "date", "driver_id", "truck_id", "status"))
    if code in {"working_day_without_earnings", "earnings_on_nonworking_day"}:
        return {"days": _fields(selected, ("id", "date", "driver_id", "status", "additional_earned")), "jobs": jobs}
    if code == "job_amount_out_of_range":
        return {"jobs": [row for row in basis["jobs"] if row["id"] == record_id],
                "days": _fields(selected, ("id", "date", "driver_id", "status"))}
    if code in {"fuel_amount_out_of_range", "fuel_price_unusual"}:
        return [row for row in basis["fuel_entries"] if row["id"] == record_id]
    if code == "possible_duplicate_fuel":
        # Bind the decision to the complete current group, including membership.
        # A third matching purchase must reopen a previously dismissed pair.
        anchor = next((row for row in basis["fuel_entries"] if row["id"] == record_id), None)
        if anchor is None:
            return []

        def signature(row):
            return (row["truck_id"], row["date"], normalize_fuel_provider(row["fuel_card_name"]),
                    row["fuel_cost"], row["fuel_volume"])

        relevant = _fields([row for row in basis["fuel_entries"] if signature(row) == signature(anchor)],
                           ("id", "date", "truck_id", "fuel_cost", "fuel_volume", "fuel_card_name"))
        return [dict(row, fuel_card_name=normalize_fuel_provider(row["fuel_card_name"])) for row in relevant]
    if code in {"payslip_amount_out_of_range", "employer_cost_below_wage", "payroll_gap_unusual"}:
        return [row for row in basis["payslips"] if row["id"] == record_id]
    if code in {"missing_payslip", "multiple_payslips"}:
        return {"payslips": [row for row in basis["payslips"] if row["driver_id"] == driver_id],
                "employment": employment, "jobs": jobs,
                "days": _fields(selected, ("id", "date", "driver_id", "status", "overnight", "additional_earned", "additional_wages"))}
    if code in {"missing_fuel_receipt", "fuel_flag_without_truck"}:
        return {"days": _fields([row for row in days if row["date"] == target_date and
                                 (truck_id is None or row["truck_id"] == truck_id)],
                                ("id", "date", "driver_id", "truck_id", "fuel", "status")),
                "fuel_entries": [row for row in basis["fuel_entries"] if row["date"] == target_date and
                                 (truck_id is None or row["truck_id"] == truck_id)]}
    if code == "missing_overhead_settings":
        return basis["overhead"]
    if code == "missing_day":
        return {"days": selected, "employment": employment}
    return basis


def fingerprint_for_scope(report, scope_key):
    """Hash source values and absent/present membership, not only record IDs."""
    payload = {"rules": RULE_VERSION, "week_start": report["week_start"],
               "scope": scope_key, "source": _scope_basis(report, scope_key)}
    code = scope_key.split(":", 1)[0]
    if code == "fuel_price_unusual":
        payload["scope_rules"] = {"version": 1, "min_pence_per_litre": FUEL_PRICE_MIN_PENCE_PER_LITRE,
                                  "max_pence_per_litre": FUEL_PRICE_MAX_PENCE_PER_LITRE}
    elif code == "payroll_gap_unusual":
        payload["scope_rules"] = {"version": 1, "multiplier": PAYROLL_GAP_MULTIPLIER,
                                  "minimum_gap_pence": PAYROLL_GAP_MIN_PENCE}
    elif code == "possible_duplicate_fuel":
        payload["scope_rules"] = {"version": 1}
    if scope_key == "week":
        payload["verification_records"] = report.get("_verification_basis", [])
    return _digest(payload)


def _allowed_decisions(issue):
    if issue["code"] == "missing_payslip":
        return ["confirmed_zero"]
    if issue["code"] in AWAITING_INVOICE_ISSUES:
        return ["awaiting_invoice"]
    return ["verified", "dismissed"] if issue["code"] in VERIFIABLE_ISSUES else []


def get_reviewed_week(week_start, *, as_of=None):
    """Derive current review state without writes or old alert-dismissal flags."""
    report = calculate_weekly_report(week_start, as_of=as_of)
    with db.session.no_autoflush:
        saved = OwnerIssueVerification.query.filter_by(week_start=week_start).order_by(OwnerIssueVerification.id).all()
        week_reviews = OwnerWeekReview.query.filter_by(week_start=week_start).order_by(OwnerWeekReview.id).all()
    issues = {issue["key"]: issue for issue in report["issues"]}
    latest = {entry.scope_key: entry for entry in saved}
    history, matching = [], {}
    for entry in saved:
        current = issues.get(entry.scope_key)
        if entry.decision == "note":
            status = "note" if entry.source_fingerprint == fingerprint_for_scope(report, entry.scope_key) else "outdated"
        elif current is None:
            status = "resolved"
        elif entry is not latest[entry.scope_key]:
            status = "superseded"
        elif (entry.source_fingerprint == fingerprint_for_scope(report, entry.scope_key)
              and entry.decision in _allowed_decisions(current)):
            status = "current"
        else:
            status = "outdated"
        item = {"id": entry.id, "scope_key": entry.scope_key, "key": entry.scope_key,
                "decision": entry.decision, "note": entry.note, "created_at": entry.created_at,
                "source_fingerprint": entry.source_fingerprint, "status": status}
        history.append(item)
        if status == "current":
            matching[entry.scope_key] = item
    for issue in report["issues"]:
        issue["fingerprint"] = fingerprint_for_scope(report, issue["key"])
        issue["verification_decisions"] = _allowed_decisions(issue)
        issue["can_verify"] = bool(RESOLVING_DECISIONS.intersection(issue["verification_decisions"]))
        issue["can_review_action"] = bool(issue["verification_decisions"])
        issue["review_action"] = matching.get(issue["key"])
        issue["awaiting_invoice"] = bool(issue["review_action"] and
                                          issue["review_action"]["decision"] == "awaiting_invoice")
        issue["current_note"] = issue["review_action"]["note"] if issue["review_action"] else ""
        issue["verification"] = issue["review_action"] if issue["review_action"] and not issue["awaiting_invoice"] else None
        issue["resolved"] = issue["verification"] is not None
        issue["optional"] = issue["code"] in OPTIONAL_ISSUES
    all_outstanding = [issue for issue in report["issues"] if not issue["resolved"]]
    outstanding = [issue for issue in all_outstanding if not issue["optional"]]
    report["outstanding_issues"] = outstanding
    report["optional_issues"] = [issue for issue in all_outstanding if issue["optional"]]
    report["all_outstanding_issues"] = all_outstanding
    report.update(review_schedule(report["week_end"], report["as_of"]))
    full_verification_basis = [{name: row[name] for name in
        ("id", "scope_key", "decision", "note", "source_fingerprint")} for row in history]
    # Optional reading/assignment explanations do not change financial signoff.
    # Actual source changes remain in the complete source basis as before.
    report["_verification_basis"] = [row for row in full_verification_basis
                                     if row["scope_key"].split(":", 1)[0] not in OPTIONAL_ISSUES]
    report["outstanding_count"] = len(outstanding)
    report["optional_check_count"] = len(report["optional_issues"])
    report["week_fingerprint"] = fingerprint_for_scope(report, "week")
    last = week_reviews[-1] if week_reviews else None
    matches = bool(last and last.source_fingerprint == report["week_fingerprint"])
    if last and not matches and full_verification_basis != report["_verification_basis"]:
        # Older reviews included optional explanations. Match their exact
        # append-only history prefix while ignoring only later optional actions.
        # Never strip a financial decision or note, or alter current sources.
        legacy_basis = list(full_verification_basis)
        legacy_report = dict(report, _verification_basis=legacy_basis)
        while True:
            if last.source_fingerprint == fingerprint_for_scope(legacy_report, "week"):
                matches = True
                break
            if not legacy_basis or legacy_basis[-1]["scope_key"].split(":", 1)[0] not in OPTIONAL_ISSUES:
                break
            legacy_basis.pop()
    if report["period_state"] != "finished":
        status = report["period_state"]
    elif outstanding:
        status = "needs_review" if report["review_overdue"] else "awaiting_records"
    elif matches:
        status = "checked"
    elif last:
        status = "outdated"
    else:
        status = "not_reviewed"
    report["review_status"] = status
    report["check_state"] = status
    report["reviewed_at"] = last.created_at if status == "checked" else None
    report["last_reviewed_at"] = last.created_at if last else None
    report["week_review_outdated"] = bool(last and not matches)
    report["review_note"] = last.note if last else ""
    # Signoff records must remain visible without fingerprinting themselves.
    review_history = [{"id": f"week_review:{row.id}", "record_id": row.id,
                       "scope_key": "week_review", "key": "week_review", "decision": "reviewed",
                       "note": row.note, "created_at": row.created_at,
                       "source_fingerprint": row.source_fingerprint,
                       "status": "superseded" if row is not last else "current" if matches else "outdated"}
                      for row in week_reviews]
    report["week_review_history"] = review_history
    report["verification_history"] = history + review_history
    report["estimated_operating_result"] = None
    if (report["period_state"] == "finished" and report["overheads"] is not None
            and not any(issue["blocking"] for issue in outstanding)):
        report["estimated_operating_result"] = report["earnings"] - report["fuel_spending"] - report["employer_cost"] - report["overheads"]
    return report


def _require_fingerprint(actual, expected):
    if actual != expected:
        raise ValueError("The report has changed since this form opened; reload it and check the updated figures")


def save_issue_verification(week_start, issue_key, note, expected_fingerprint, *, decision="verified", as_of=None):
    note = _review_note(note, required=True)
    report = get_reviewed_week(week_start, as_of=as_of)
    issue = next((row for row in report["issues"] if row["key"] == issue_key), None)
    if issue is None:
        raise ValueError("This issue is no longer present; reload the report")
    if decision not in issue["verification_decisions"]:
        raise ValueError("This issue needs its source entry corrected; it cannot be dismissed with this decision")
    _require_fingerprint(issue["fingerprint"], expected_fingerprint)
    record = OwnerIssueVerification(week_start=week_start, scope_key=issue_key, decision=decision,
                                    note=note, source_fingerprint=issue["fingerprint"])
    db.session.add(record)
    db.session.flush()
    return record


def _validate_note_scope(report, scope_key):
    if scope_key == "week_note":
        return scope_key
    match = re.fullmatch(
        r"recorded_absence:(\d{4}-\d{2}-\d{2}):driver_id=([1-9]\d*):date=(\d{4}-\d{2}-\d{2})",
        scope_key,
    ) if isinstance(scope_key, str) else None
    if match is None or match.group(1) != report["week_start"].isoformat():
        raise ValueError("Invalid absence note scope; reload the report")
    on_date = date.fromisoformat(match.group(3))
    if not report["week_start"] <= on_date <= report["week_end"]:
        raise ValueError("The absence note must belong to this payroll week")
    matching = [row for row in report["review_basis"]["days"]
                if row["driver_id"] == int(match.group(2)) and row["date"] == on_date.isoformat()]
    if len(matching) != 1 or matching[0]["status"] not in {"holiday", "absent"}:
        raise ValueError("An absence note requires an existing Holiday or Absent day")
    return scope_key


def save_week_note(week_start, note, expected_fingerprint, *, scope_key="week_note", as_of=None):
    """Append a period or structured absence explanation; never resolve checks."""
    note = _review_note(note, required=True)
    report = get_reviewed_week(week_start, as_of=as_of)
    _require_fingerprint(report["week_fingerprint"], expected_fingerprint)
    scope_key = _validate_note_scope(report, scope_key)
    record = OwnerIssueVerification(week_start=week_start, scope_key=scope_key, decision="note", note=note,
                                    source_fingerprint=fingerprint_for_scope(report, scope_key))
    db.session.add(record)
    db.session.flush()
    return record


def save_week_review(week_start, expected_fingerprint, *, note="", as_of=None):
    """Explicit finished-week signoff; the caller owns commit/rollback."""
    note = _review_note(note, required=False)
    report = get_reviewed_week(week_start, as_of=as_of)
    _require_fingerprint(report["week_fingerprint"], expected_fingerprint)
    if report["period_state"] != "finished":
        raise ValueError("An in-progress or future week cannot be marked reviewed")
    if report["outstanding_issues"]:
        raise ValueError("Resolve or verify every outstanding issue before marking this week reviewed")
    record = OwnerWeekReview(week_start=week_start, source_fingerprint=report["week_fingerprint"], note=note)
    db.session.add(record)
    db.session.flush()
    return record
