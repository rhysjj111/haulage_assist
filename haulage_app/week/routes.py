from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Driver, Day, Truck
from haulage_app.day.forms import DayForm
from haulage_app.week import week_bp
from pprint import pprint
from datetime import date, timedelta
from haulage_app.calculations.driver_truck_metrics import (
    calculate_driver_metrics_week,
    calculate_truck_metrics_week,
    calculate_total_metric_list,
    calculate_total_metric_dict,
)
from haulage_app.functions import(
    date_to_db,
    get_week_number_sat_to_fri,
)
from haulage_app.analysis.functions import (
    get_start_of_week,
    get_formatted_payslip_weeks,
    get_start_and_end_of_week,
    get_expenses_for_period,
    calculate_weekly_metrics,
    get_weeks_for_month,
    is_complete_month,
    calculate_monthly_metrics,
    get_expected_weeks_in_month,
    get_month_from_week,
    get_available_months,
)
from collections import defaultdict
from pprint import pprint



@week_bp.route("/week/<int:item_id>/<tab>", methods=["GET", "POST"])
def week(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())
    days = list(Day.query.order_by(Day.date).all())

    weekly_data = defaultdict(lambda: defaultdict(list))

    for day in days:
        date_obj = day.date
        driver_id = day.driver_id
        year, week_number = get_week_number_sat_to_fri(date_obj)

        weekly_data[driver_id][(year, week_number)].append(day)

        pprint(weekly_data)

    driver_weeks_forms = {}
    #Drill into outer dict
    for driver_id, weeks_data in weekly_data.items():
        driver_weeks_forms[driver_id] = {}
        #Drill into week number, day entries next layer of dict
        for (year, week_number), entries in weeks_data.items():
            start_date = get_start_of_week(year, week_number)
            week_dates = [start_date + timedelta(days=i) for i in range(7)]
            forms = {}

            for day_date in week_dates:
                #Search for day entry with matching date
                entry_for_day = next((e for e in entries if e.date == day_date), None)
                if entry_for_day:
                    form = DayForm(prefix=f'{driver_id}-{day_date}')
                    form.id.data = entry_for_day.id
                    form.date.data = entry_for_day.date
                    form.start_mileage.data = entry_for_day.start_mileage
                    form.end_mileage.data = entry_for_day.end_mileage
                    form.fuel.data = entry_for_day.fuel
                    form.overnight.data = entry_for_day.overnight
                    form.status.data = entry_for_day.status
                    form.truck.data = entry_for_day.truck_id
                    forms[day_date] = form
                else:
                    forms[day_date] = None
            driver_weeks_forms[driver_id][(year, week_number)] = (week_dates, forms)



    #     for day in week_dates:


    # for (year, week_number), driver_data in weekly_data.items():
    #     for driver, data in driver_data.items():
    #         start_date = data["start_date"]
    #         form = WeekForm()
    #         start_date = date(2023, 10, 23)
    #         for i in range(7):
    #             form.days[i].date.data = start_date + timedelta(days=i)
    #             if 
    # form = {}
    # pprint(weekly_data)




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
        list=day_entries_to_edit,
        selected_entry=selected_entry,
        tab=tab,
        item_id=0,
        type='week',
        form=form,
        driver_weeks_forms = driver_weeks_forms,
    )

