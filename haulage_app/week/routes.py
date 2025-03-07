from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Driver, Day, Truck
from haulage_app.week import week_bp
from pprint import pprint


@week_bp.route("/week/<int:item_id>/<tab>", methods=["GET", "POST"])
def week(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())
    components = {'drivers':drivers, 'trucks':trucks}

    day_entries_to_edit = list(
        Day.query.join(Driver)
        .filter(Day.status == 'working')
        .order_by(
            db.case(
                (Day.start_mileage == 0, 0),
                (Day.end_mileage == 0, 0),
                else_=1
            ),  # Prioritize 0 mileages
            Day.driver_id,
            Driver.first_name,
            Driver.last_name,
            Day.date.asc()
        )
        .all()
    )

    all_day_entries = list(
        Day.query.join(Driver)
        .order_by(
            Day.driver_id,
            Driver.first_name,
            Driver.last_name,
            Day.date.asc()
        ).all()
    )

    success = request.args.get('success')
        
    if item_id > 0:
        # Find the index of the entry with matching item_id
        entry_index = next((index for index, entry in enumerate(all_day_entries) 
                        if entry.id == item_id), None)
        # Create new list starting from that entry onwards
        if entry_index is not None:
            if success:
                selected_entry = all_day_entries[entry_index:][1]
            else:
                selected_entry = all_day_entries[entry_index:][0]
    else:
        selected_entry = day_entries_to_edit[0]

    return render_template(
        "week/week.html",
        components=components,
        list=day_entries_to_edit,
        selected_entry=selected_entry,
        tab=tab,
        item_id=0,
        type='week',
    )

