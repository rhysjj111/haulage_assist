from flask import render_template, request, url_for
from haulage_app import db, f
from haulage_app.models import (
    Driver, Day, Job, Truck, Fuel, Expense, 
    ExpenseOccurrence, Payslip)
from datetime import timedelta, date, datetime
from haulage_app.analysis import analysis_bp
from pprint import pprint
from haulage_app.config import *
from haulage_app.calculations.driver_truck_metrics import (
    calculate_driver_metrics_week,
    calculate_truck_metrics_week,)

def get_week_number_sat_to_fri(date):
    """Returns the week number with Saturday as the start of the week."""
    """Returns a tuple of (year, week_number) with Saturday as week start."""
    adjusted_date = date - timedelta(days=2)
    year = adjusted_date.year
    week = adjusted_date.isocalendar().week
    return (year, week)

def get_start_of_week(year, week_number):
    """Returns the start date of the week."""
    # Get January 1st of selected year
    year_start = date(year, 1, 1)
    # Calculate offset to previous Saturday
    saturday_offset = (year_start.weekday() + 2) % 7
    # Calculate days to add for desired week
    week_offset = (week_number - 1) * 7
    # Calculate final start date
    start_date = year_start + timedelta(days=week_offset - saturday_offset)
    return start_date

def get_start_end_of_week(year, week_number):
    """Returns the start and end dates of the week."""
    # Calculate the start date of the week
    start_date = get_start_of_week(year, week_number)
    # Calculate the end date of the week
    end_date = start_date + timedelta(days=6)
    return start_date, end_date

def calculate_expenses_for_period(start_date, end_date):
    expenses = ExpenseOccurrence.query.filter(
        db.or_(
            ExpenseOccurrence.end_date >= start_date,
            #checks if there is no end date
            ExpenseOccurrence.end_date == None
        ),
        # makes sure an expense 
        ExpenseOccurrence.start_date <= end_date
    # returns only the first occurrence if two fall within the dates
    ).all()
    
    total_cost = sum(expense.cost for expense in expenses)

    return total_cost

@analysis_bp.route("/weekly_analysis", methods=["GET"])
def weekly_analysis():
    # Get all days in the database
    all_days = Day.query.all()
    # Extract dates from the days
    dates = [day.date for day in all_days]
    # Calculate week numbers for each day
    week_numbers = [get_week_number_sat_to_fri(day.date) for day in all_days]
    # Get unique week numbers
    available_weeks = sorted(set(week_numbers), reverse=True)
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())
    driver_data = {}
    truck_data = {}
    grand_total_data = {}
    # Get today's year and week number
    today_year, today_week = get_week_number_sat_to_fri(date.today())
    # Use these values to get the start date
    start_date, end_date = get_start_end_of_week(today_year, today_week)

    if request.args.get('week_select'):
        selected_week = request.args.get('week_select')
        selected_year, selected_week_number = map(int, selected_week.split('-'))
        start_date, end_date = get_start_end_of_week(
            selected_year, selected_week_number)

    for driver in drivers:

        driver_data[driver.id] = calculate_driver_metrics_week(
            driver, Day, Job, Payslip, start_date, end_date)

    for truck in trucks:

        truck_data[truck.id] = calculate_truck_metrics_week(
            truck, Day, Fuel, start_date, end_date)

    total_expenses = calculate_expenses_for_period(start_date, end_date)

    grand_total_data = {
        'total_expenses': total_expenses,
    }

    return render_template(
        'analysis/weekly_analysis.html',
        available_weeks=available_weeks, 
        drivers=drivers, 
        driver_data=driver_data,
        truck_data=truck_data,
        start_date=start_date,
        grand_total_data=grand_total_data,
    )



