"""Display the settings actually used by a report, without reading policy history."""


def build_overhead_basis(weeks):
    """Describe only the supplied weekly reports; monthly callers pass completed weeks.

    A new source setting with the same count and allowance does not change the
    displayed basis. Missing settings remain distinct from an explicit zero.
    """
    rows = []
    for week in weeks:
        settings = week["overhead_settings"]
        rows.append({
            "week_start": week["week_start"],
            "week_end": week["week_end"],
            "truck_count": settings["truck_count"] if settings is not None else None,
            "allowance_per_truck": settings["allowance_per_truck"] if settings is not None else None,
        })

    values = {(row["truck_count"], row["allowance_per_truck"]) for row in rows}
    if not rows:
        state = "empty"
    elif values == {(None, None)}:
        state = "missing"
    elif len(values) == 1:
        state = "uniform"
    else:
        state = "mixed"
    return {
        "state": state,
        "week_count": len(rows),
        "weeks": rows,
        "truck_count": rows[0]["truck_count"] if state == "uniform" else None,
        "allowance_per_truck": rows[0]["allowance_per_truck"] if state == "uniform" else None,
    }
