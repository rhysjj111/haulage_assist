from flask import render_template, request
from haulage_app import db, f
from haulage_app.models import Driver, Day, Job, Payslip
from haulage_app.verification.models import IncorrectMileage, MissingEntryAnomaly, TableName
from datetime import timedelta, date, datetime
from haulage_app.wages_calculator import wages_calculator_bp
from haulage_app.calculations.driver_truck_metrics import (
    calculate_driver_metrics_week,
)
from haulage_app.functions import(
    get_week_number_sat_to_fri,
)
from haulage_app.analysis.functions import (
    get_start_and_end_of_week,
)
from pprint import pprint
from haulage_app.analysis.routes import get_active_drivers_for_period

@wages_calculator_bp.route("/wages_calculator", methods=["GET"])
def wages_calculator():
    # drivers = list(Driver.query.order_by(Driver.first_name).all())

    today_year, today_week = get_week_number_sat_to_fri(date.today())
    start_date, end_date = get_start_and_end_of_week(today_year, today_week)

    driver_data = {}
    missing_days = False
    anomalies_present = False

    drivers = get_active_drivers_for_period(start_date, end_date)
    print(drivers)

    # Query IncorrectMileage anomalies first (sorted)
    incorrect_mileage_anomalies = IncorrectMileage.query.filter_by(is_read=False).order_by(
        IncorrectMileage.year,
        IncorrectMileage.week_number
    ).all()

    for driver in drivers:

        driver_data[driver.id] = calculate_driver_metrics_week(
            driver, start_date, end_date)

        # Check no driver has less than 5 days
        if len(driver_data[driver.id]['days_summary']) < 5:
            missing_days = True

    # Query MissingEntryAnomaly anomalies (excluding table_name = 'day', sorted)
    missing_entry_anomalies = MissingEntryAnomaly.query.filter(
        MissingEntryAnomaly.is_read == False,
        MissingEntryAnomaly.table_name != TableName.DAY
    ).order_by(
        MissingEntryAnomaly.table_name,
        MissingEntryAnomaly.date,
    ).all()

    # Combine them in the order you want
    anomalies = missing_entry_anomalies + incorrect_mileage_anomalies

    if anomalies:
        anomalies_present = True

    return render_template("wages_calculator.html", 
                           driver_data=driver_data, 
                           drivers=drivers, 
                           start_date=start_date, 
                           end_date=end_date, 
                           missing_days=missing_days,
                           anomalies_present=anomalies_present,
                        )
