"""Read-only presentation of recorded figures; filtering never changes review state."""


def _scope_subject(scope_key):
    details = {}
    for part in scope_key.split(":")[2:]:
        if "=" in part:
            name, value = part.split("=", 1)
            if name in {"driver_id", "truck_id"} and value.isdigit():
                details[name] = int(value)
    return details


def _matches(subject, kind, selected_id):
    identifier = subject.get(f"{kind}_id")
    if identifier is not None:
        return selected_id is None or identifier == selected_id
    return subject.get("driver_id") is None and subject.get("truck_id") is None


def build_breakdown(report, kind, *, selected_id=None, selected_label=None):
    weeks = report["weeks"] if "weeks" in report else [report]
    source = report["drivers" if kind == "driver" else "trucks"]
    id_key = f"{kind}_id"
    name_key = "driver_name" if kind == "driver" else "truck_registration"
    rows = [dict(row) for identifier, row in source.items() if selected_id is None or identifier == selected_id]
    rows.sort(key=lambda row: (row[name_key].casefold(), row[id_key]))
    options = [{"id": identifier, "label": row[name_key]} for identifier, row in source.items()]
    if selected_id is not None and selected_id not in source:
        options.append({"id": selected_id, "label": selected_label})
    options.sort(key=lambda row: (row["label"].casefold(), row["id"]))
    issues, history = [], []
    for week in weeks:
        context = {"week_start": week["week_start"], "week_end": week["week_end"]}
        issues.extend(dict(item, **context) for item in week["outstanding_issues"] if _matches(item, kind, selected_id))
        history.extend(dict(item, **context) for item in week["verification_history"]
                       if _matches(_scope_subject(item["scope_key"]), kind, selected_id))
    for row in rows:
        relevant = [item for item in issues if item.get(id_key) == row[id_key]]
        if kind == "driver":
            missing_payroll = False
            for week in weeks:
                weekly_row = week["drivers"].get(row[id_key])
                if weekly_row is None or weekly_row["payslip_ids"]:
                    continue
                confirmed_zero = any(
                    item["code"] == "missing_payslip" and item.get("driver_id") == row[id_key]
                    and item.get("resolved") and (item.get("verification") or {}).get("decision") == "confirmed_zero"
                    for item in week["issues"])
                missing_payroll |= not confirmed_zero
            row["payroll_pending"] = missing_payroll or any(item["code"] in {
                "missing_payslip", "multiple_payslips", "payslip_amount_out_of_range", "employer_cost_below_wage"
            } for item in relevant)
            row["entries_pending"] = bool(relevant)
        else:
            row["fuel_pending"] = any(item["code"] in {"missing_fuel_receipt", "fuel_amount_out_of_range"} for item in relevant)
    return {"kind": kind, "options": options, "rows": rows, "selected_id": selected_id,
            "selected_label": selected_label, "issues": issues, "history": history,
            "allowance_weeks": [{"week_start": week["week_start"], "week_end": week["week_end"],
                "allowance_per_truck": week["overhead_settings"]["allowance_per_truck"]
                if week["overhead_settings"] is not None else None} for week in weeks] if kind == "truck" else []}
