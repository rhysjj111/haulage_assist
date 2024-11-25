from flask import render_template, request, url_for
from haulage_app import db
from haulage_app.models import (
    Driver, Day, Job, Truck, Fuel, Expense, 
    ExpenseOccurrence, Payslip)
from datetime import timedelta, date, datetime
from haulage_app.analysis import analysis_bp
from pprint import pprint
from haulage_app.config import *
from haulage_app.calculations.driver_truck_metrics import (
    calculate_driver_metrics_week,
    calculate_truck_metrics_week,
    calculate_total_metric_list,
    calculate_total_metric_dict,)
from haulage_app.functions import(
    get_week_number_sat_to_fri,
    get_start_of_week,
    get_start_end_of_week,
    get_weeks_for_period,)

@analysis_bp.route("/weekly_analysis", methods=["GET"])
def weekly_analysis():

    # Get all days in the database
    all_days = Day.query.all()
    # Get all drivers and trucks
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())

    # Get a list of available weeks
    available_weeks = get_weeks_for_period(all_days)

    driver_data = {}
    truck_data = {}
    grand_total_data = {}
    selected_year = None
    selected_week_number = None

    # Get today's year and week number
    today_year, today_week = get_week_number_sat_to_fri(date.today())
    # Use these values to get the start and end dates of the week
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

    expenses = ExpenseOccurrence.query.filter(
        db.or_(
            ExpenseOccurrence.end_date >= start_date,
            #checks if there is no end date
            ExpenseOccurrence.end_date == None
        ),
        ExpenseOccurrence.start_date <= end_date).all()

    total_expenses = calculate_total_metric_list('cost', expenses)*3
    grand_total_earned = calculate_total_metric_dict('total_earned', driver_data)
    grand_total_wages = calculate_total_metric_dict('total_cost_to_employer', driver_data)
    grand_total_fuel_volume = calculate_total_metric_dict('total_fuel_volume', truck_data)
    grand_total_fuel_cost = calculate_total_metric_dict('total_fuel_cost', truck_data)
    profit = grand_total_earned - grand_total_wages - total_expenses - grand_total_fuel_cost


    grand_total_data = {
        'grand_total_earned': grand_total_earned,
        'total_expenses': total_expenses,
        'grand_total_fuel_volume': grand_total_fuel_volume,
        'grand_total_wages': grand_total_wages,
        'grand_total_fuel_cost': grand_total_fuel_cost,
        'profit': profit,
    }

    # drivers_ai = Driver.query.options(
    #     db.joinedload(Driver.days),
    #     db.joinedload(Driver.payslips)
    # ).all()

    # driver_list = []
    # for driver in drivers_ai:
    #     # Get all columns from the Driver model
    #     driver_dict = {column.name: getattr(driver, column.name) 
    #                 for column in Driver.__table__.columns}
        
    #     # Add related days
    #     driver_dict['days'] = [{column.name: getattr(day, column.name) 
    #                         for column in Day.__table__.columns}
    #                         for day in driver.days]
        
    #     # Add related payslips
    #     driver_dict['payslips'] = [{column.name: getattr(payslip, column.name) 
    #                             for column in Payslip.__table__.columns}
    #                             for payslip in driver.payslips]
        
    #     driver_list.append(driver_dict)

    # driver_analysis_prompt = f"""Find and list any possible missing payslips for the following data:
    # {driver_list}
    # Display the suspected missing payslip dates in a list. Only include this list in the answer"""

    # response = ai.generate_content(driver_analysis_prompt)

    # print(response.text)

    
    return render_template(
        'analysis/weekly_analysis.html',
        selected_week_number=selected_week_number,
        selected_year=selected_year,
        # airesponse=response.text,
        available_weeks=available_weeks, 
        drivers=drivers, 
        driver_data=driver_data,
        truck_data=truck_data,
        start_date=start_date,
        grand_total_data=grand_total_data,
    )



