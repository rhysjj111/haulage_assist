from flask import render_template, request
from haulage_app import db, f
from haulage_app.models import Driver, Day, Job, Payslip
from datetime import timedelta, date, datetime
from haulage_app.wages_calculator import wages_calculator_bp
from haulage_app.calculations.driver_truck_metrics import (
    calculate_driver_metrics_week,
)
from haulage_app.analysis.functions import (
    get_week_number_sat_to_fri,
    get_start_and_end_of_week,
)
from pprint import pprint

@wages_calculator_bp.route("/wages_calculator", methods=["GET"])
def wages_calculator():
    drivers = list(Driver.query.order_by(Driver.first_name).all())

    today_year, today_week = get_week_number_sat_to_fri(date.today())
    start_date, end_date = get_start_and_end_of_week(today_year, today_week)

    driver_data = {}

    for driver in drivers:

        driver_data[driver.id] = calculate_driver_metrics_week(
            driver, start_date, end_date)

    return render_template("wages_calculator.html", driver_data=driver_data, drivers=drivers, start_date=start_date, end_date=end_date)
