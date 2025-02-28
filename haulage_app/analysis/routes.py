from flask import render_template, request, url_for
from haulage_app import db
from haulage_app.models import (
    Driver, Day, Job, Truck, Fuel, Expense, 
    ExpenseOccurrence, Payslip
)
from datetime import timedelta, date, datetime
from haulage_app.analysis import analysis_bp
from pprint import pprint
from haulage_app.config import *
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
from sqlalchemy import cast, Integer

@analysis_bp.route("/monthly_analysis", methods=["GET"])
def monthly_analysis():
    # Get all drivers and trucks
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration.desc()).all())

    # Initialize variables
    selected_year = None
    selected_month_number = None

    # Get week numbers (with year) from Payslip table
    available_weeks = get_formatted_payslip_weeks()
    # print(available_weeks)

    available_months = get_available_months(available_weeks)

    if request.args.get('month_select'):
        selected_month = request.args.get('month_select')
        selected_year, selected_month_number = map(int, selected_month.split("-"))
    else:
        selected_month_number = available_months[0]['month_number']
        selected_year = available_months[0]['year']

    # print(available_weeks)
    
    weeks_for_month = get_weeks_for_month(available_weeks, selected_year, selected_month_number)

    complete_month = is_complete_month(weeks_for_month, selected_year, selected_month_number)

    current_month = MONTH_NAMES[selected_month_number]

    monthly_metrics = calculate_monthly_metrics(weeks_for_month, drivers, trucks, selected_year, selected_month_number)

    expected_weeks_for_month = get_expected_weeks_in_month(selected_year, selected_month_number)
    
    return render_template(
        "analysis/monthly_analysis.html",
        expected_weeks = expected_weeks_for_month,
        month=current_month,
        weeks_for_month=weeks_for_month,
        available_months=available_months,
        monthly_metrics=monthly_metrics,
        drivers=drivers,
        trucks=trucks,
        available_weeks=available_weeks,
        selected_year=selected_year,
        selected_month_number=selected_month_number,
        truck_data = {}
    )


@analysis_bp.route("/weekly_analysis", methods=["GET"])
def weekly_analysis():

    # Get all drivers and trucks
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())

    # Initialize variables
    selected_year = None
    selected_week_number = None
    data_available = False

    # Get week numbers (with year) from Payslip table
    available_weeks = get_formatted_payslip_weeks()
    # print(available_weeks)

    if request.args.get('week_select'):
        # Convert selected week number to start and end date
        selected_week = request.args.get('week_select')
        selected_year, selected_week_number = get_week_number_sat_to_fri(
            date_to_db(selected_week)
        )
        start_date, end_date = get_start_and_end_of_week(
            selected_year, selected_week_number)        
        
    else:
        # Convert latest week number to start and end date
        selected_week_number = available_weeks[0]['week_number']
        selected_year = available_weeks[0]['year']
        start_date, end_date = get_start_and_end_of_week(selected_year, selected_week_number)
    
    data_available = any(week['year'] == selected_year and week['week_number'] == selected_week_number for week in available_weeks)
   
    weekly_metrics = calculate_weekly_metrics(
        drivers, trucks, start_date, end_date)

    month_number = get_month_from_week(selected_year, selected_week_number)
    month_name = MONTH_NAMES[month_number]

    return render_template(
        'analysis/weekly_analysis.html',
        data_available=data_available,
        month_name=month_name,
        weekly_metrics=weekly_metrics,
        selected_week_number=selected_week_number,
        selected_year=selected_year,
        available_weeks=available_weeks, 
        drivers=drivers, 
        start_date=start_date,
        end_date=end_date
    )


