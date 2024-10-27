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
    calculate_driver_metrics_for_week,)

def get_week_number_sat_to_fri(date):
    """Returns the week number with Saturday as the start of the week."""
    """Returns a tuple of (year, week_number) with Saturday as week start."""
    adjusted_date = date - timedelta(days=2)
    year = adjusted_date.year
    week = adjusted_date.isocalendar().week
    return (year, week)

def get_start_end_of_week(year, week_number):
    """Returns the start and end dates of the week."""
    # Get January 1st of selected year
    year_start = date(year, 1, 1)
    # Calculate offset to previous Saturday
    saturday_offset = (year_start.weekday() + 2) % 7
    # Calculate days to add for desired week
    week_offset = (week_number - 1) * 7
    # Calculate final start date
    start_date = year_start + timedelta(days=week_offset - saturday_offset)
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

def calculate_fuel_economy(mileage, fuel_volume):
    # Calculate fuel economy based on the given mileage and fuel cost
    return round((mileage / fuel_volume) * LITRE_TO_GALLON_MULTIPLIER)

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
    start_date = date.today()

    if request.args.get('week_select'):
        selected_week = request.args.get('week_select')
        selected_year, selected_week_number = map(int, selected_week.split('-'))
        start_date, end_date = get_start_end_of_week(
            selected_year, selected_week_number)

        for driver in drivers:

            driver_data[driver.id] = calculate_driver_metrics_for_week(
                driver, Day, Job, Payslip, start_date, end_date)

        for truck in trucks:
            day_entries = Day.query.filter(
                Day.truck_id == truck.id,
                Day.date >= start_date,
                Day.date <= end_date
                ).order_by(Day.date).all()
            fuel_entries = Fuel.query.filter(
                Fuel.truck_id == truck.id,
                Fuel.date >= start_date,
                Fuel.date <= end_date
                ).order_by(Fuel.date).all()

            total_fuel_volume = sum(f.display_float(fuel.fuel_volume) for fuel in fuel_entries)
            total_fuel_cost = sum(f.display_float(fuel.fuel_cost) for fuel in fuel_entries)        
            total_mileage = sum((f.display_float(day.end_mileage)-f.display_float(day.start_mileage)) for day in day_entries)
            est_fuel_volume = round(total_mileage / MEDIAN_MILES_PER_LITRE)
            est_fuel_cost = round(est_fuel_volume * MEDIAN_POUNDS_PER_LITRE)
            fuel_economy = (total_mileage / total_fuel_volume) if total_fuel_volume else 0
            est_fuel_economy = calculate_fuel_economy(total_mileage, est_fuel_volume) if est_fuel_volume else 0

            truck_data[truck.id]={
                'truck': truck,
                'total_mileage': total_mileage,
                'total_fuel_volume': total_fuel_volume,
                'total_fuel_cost': total_fuel_cost,
                'est_fuel_volume': est_fuel_volume,
                'est_fuel_cost': est_fuel_cost,
                'fuel_economy': fuel_economy,
                'start_date': start_date,
                'end_date': end_date,
                'est_fuel_economy': est_fuel_economy,
            }

        total_expenses = calculate_expenses_for_period(start_date, end_date)

        grand_total_data = {
            'total_expenses': total_expenses,
        }

        pprint(grand_total_data)


        



    return render_template(
        'analysis/weekly_analysis.html',
        available_weeks=available_weeks, 
        drivers=drivers, 
        driver_data=driver_data,
        truck_data=truck_data,
        start_date=start_date,
        grand_total_data=grand_total_data,
    )



