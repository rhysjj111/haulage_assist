from flask import render_template, request, url_for
from haulage_app import db
from haulage_app.models import (
    Driver, Day, Job, Truck, Fuel, Expense, 
    ExpenseOccurrence, Payslip, DriverEmploymentHistory, EmploymentStatus
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
    get_start_and_end_of_month
)
from sqlalchemy import cast, Integer, and_, or_

########################## HELPER FUNCTIONS
def get_active_drivers_for_period(start_date, end_date):
    """
    Get drivers who were actively employed during the specified period.
    
    Args:
        start_date: Start date of the period
        end_date: End date of the period
    
    Returns:
        List of Driver objects who were active during the period
    """
    # Query for drivers who have employment records that overlap with the specified period
    active_driver_ids = db.session.query(DriverEmploymentHistory.driver_id).filter(
        and_(
            DriverEmploymentHistory.start_date <= end_date,
            or_(
                DriverEmploymentHistory.end_date.is_(None),  # Current employment (no end date)
                DriverEmploymentHistory.end_date >= start_date  # Employment ended after period start
            )
        )
    ).distinct().subquery()
    
    # Get the actual Driver objects
    active_drivers = Driver.query.filter(
        Driver.id.in_(active_driver_ids)
    ).order_by(Driver.first_name).all()
    
    return active_drivers

def get_active_drivers_for_date(check_date):
    """
    Get drivers who were actively employed on a specific date.
    
    Args:
        check_date: The specific date to check
    
    Returns:
        List of Driver objects who were active on that date
    """
    # Query for drivers who have employment records active on the specific date
    active_driver_ids = db.session.query(DriverEmploymentHistory.driver_id).filter(
        and_(
            DriverEmploymentHistory.start_date <= check_date,
            or_(
                DriverEmploymentHistory.end_date.is_(None),  # Current employment (no end date)
                DriverEmploymentHistory.end_date >= check_date  # Employment ended after the check date
            )
        )
    ).distinct().subquery()
    
    # Get the actual Driver objects
    active_drivers = Driver.query.filter(
        Driver.id.in_(active_driver_ids)
    ).order_by(Driver.first_name).all()
    
    return active_drivers


################################## ANALYSIS

@analysis_bp.route("/monthly_analysis", methods=["GET"])
def monthly_analysis():
    # Get all trucks
    trucks = list(Truck.query.order_by(Truck.registration.desc()).all())

    # Initialize variables
    selected_year = None
    selected_month_number = None

    # Get week numbers (with year) from Payslip table
    available_weeks = get_formatted_payslip_weeks()

    available_months = get_available_months(available_weeks)

    if request.args.get('month_select'):
        selected_month = request.args.get('month_select')
        selected_year, selected_month_number = map(int, selected_month.split("-"))
    else:
        selected_month_number = available_months[0]['month_number']
        selected_year = available_months[0]['year']
    
    weeks_for_month = get_weeks_for_month(available_weeks, selected_year, selected_month_number)
    complete_month = is_complete_month(weeks_for_month, selected_year, selected_month_number)
    current_month = MONTH_NAMES[selected_month_number]

    month_start_date, month_end_date = get_start_and_end_of_month(selected_year, selected_month_number)

    # Get only drivers who were active during the selected month
    drivers = get_active_drivers_for_period(month_start_date, month_end_date)

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

    today = date.today() # Get today's date within the request context
    year = int(request.args.get('year', get_week_number_sat_to_fri(today)[0]))
    week_num = int(request.args.get('week_num', get_week_number_sat_to_fri(today)[1]))

    # Get all trucks
    trucks = list(Truck.query.order_by(Truck.registration).all())

    # Initialize variables
    selected_year = None
    selected_week_number = None
    data_available = False

    # Get week numbers (with year) from Payslip table
    available_weeks = get_formatted_payslip_weeks()

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
   
    # Get only drivers who were active during the selected week
    drivers = get_active_drivers_for_period(start_date, end_date)

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
