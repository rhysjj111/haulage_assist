from sqlalchemy import cast, Integer
from haulage_app.config import *
from haulage_app.models import ExpenseOccurrence, Payslip, db, Driver, Truck, Day, Fuel
from datetime import datetime, timedelta, date
from haulage_app.functions import(
    find_previous_saturday,
    get_week_number_sat_to_fri,
    display_date,
    date_to_db,
)
from haulage_app.calculations.driver_truck_metrics import (
    calculate_driver_metrics_week,
    calculate_truck_metrics_week,
    calculate_total_metric_list,
    calculate_total_metric_dict,
)
from pprint import pprint
from collections import defaultdict

def get_formatted_payslip_weeks():
    """
    Retrieves all unique week numbers and years from Payslip table and formats them
    into a list of dictionaries. Each dictionary contains the week number and year,
    sorted in descending order by year and week number.
    
    Returns:
        list: List of dicts with format [{'week_number': int, 'year': int}, ...]
    """
    formatted_weeks = []
    unique_week_year = set()
    payslips = Payslip.query.all()
    for payslip in payslips:
        week_number_and_year = payslip.get_week_number
        unique_week_year.add(week_number_and_year)
    
    for year, week_number in unique_week_year:
        week_start_date, week_end_date = get_start_and_end_of_week(year, week_number)
        month = get_month_from_week(year, week_number)
        formatted_weeks.append({
            'year': year,
            'week_number': week_number,
            'week_start_date': week_start_date,
            'week_end_date': week_end_date,
            'month': month,
        })

    formatted_weeks.sort(key=lambda x: (x['year'], x['week_number']), reverse=True)
    
    return formatted_weeks

def get_start_of_week(year, week_number):
    """Calculates the date (Saturday) corresponding to a given week number.
       Simplified logic to find the start of week 1.
    """
    first_tuesday = date(year, 1, 1)
    while first_tuesday.weekday() != 1:  # 1 represents Tuesday
        first_tuesday += timedelta(days=1)
    # Find the previous Saturday from Jan 1st
    first_sat = find_previous_saturday(first_tuesday)
    # Calculate the start date of the target week
    week_start_date = first_sat + timedelta(weeks=(week_number - 1))
    return week_start_date

def get_month_from_week(year: int, week_number: int) -> int:
    """
    Returns the month number (1-12) for a given week number and year.
    Uses the date 4 days after the start of the week (Wednesday) to determine the month.

    Args:
        year (int): The year
        week_number (int): The week number

    Returns:
        int: Month number (1-12)
    """
    start_date = get_start_of_week(year, week_number)
    target_date = start_date + timedelta(days=3) # Tuesday
    return target_date.month

def get_available_months(available_weeks):
    """
    Returns a list of dictionaries with the year and month number for each week in the available_weeks list.
    """
    return list(
        {f"{week['year']}-{week['month']}": {'year': week['year'], 
        'month_number': week['month']} for week in available_weeks}.values()
    )

def get_start_and_end_of_week(year, week_number):
    """Returns the start and end dates of the week."""
    # Calculate the start date of the week
    start_date = get_start_of_week(year, week_number)
    # Calculate the end date of the week
    end_date = start_date + timedelta(days=6)
    return start_date, end_date

def get_start_and_end_of_month(year, month_number):
    month_start_date = date(year, month_number, 1)
    if month_number == 12:
        month_end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end_date = date(year, month_number + 1, 1) - timedelta(days=1)
    return month_start_date, month_end_date

def get_expected_weeks_in_month(year: int, month: int) -> dict:
    """
    Returns the total number of Saturday-Friday weeks and their week numbers 
    that fall within a given month. A week is considered to be in the month
    if its Wednesday falls within the month.

    Args:
        year (int): Year to calculate weeks for
        month (int): Month number (1-12) to calculate weeks for

    Returns:
        dict: Contains total_weeks (int) and week_numbers (list)
    """
    # Get first day of target month and next month
    first_day_of_month = date(year, month, 1)
    if month == 12:
        first_day_of_next_month = date(year + 1, 1, 1)
    else:
        first_day_of_next_month = date(year, month + 1, 1)
    
    # Find the first Saturday before or on the first of the month
    first_saturday = find_previous_saturday(first_day_of_month)
    
    total_weeks = 0
    week_numbers = []
    current_sat = first_saturday

    while True:
        tuesday = current_sat + timedelta(days=3)
        if tuesday >= first_day_of_next_month:
            break
            
        if tuesday >= first_day_of_month:
            adjusted_date = current_sat + timedelta(days=2)
            week_number = adjusted_date.isocalendar().week
            week_numbers.append(week_number)
            total_weeks += 1
            
        current_sat += timedelta(days=7)

    return {
        'total_weeks': total_weeks,
        'week_numbers': week_numbers
    }

def get_expenses_for_period(start_date: date, end_date: date) -> list[ExpenseOccurrence]:
    return ExpenseOccurrence.query.filter(
        db.or_(
            ExpenseOccurrence.end_date >= start_date,
            ExpenseOccurrence.end_date == None
        ),
        ExpenseOccurrence.start_date <= end_date).all()

def classify_entities(drivers, trucks, day_entries):
    """
    Classifies drivers and trucks as mutually exclusive, non-mutually exclusive, or on holiday.

    Returns:
        A dictionary containing classified sets of drivers and trucks.
    """
    driver_to_trucks = defaultdict(set)
    truck_to_drivers = defaultdict(set)
    
    for day in day_entries:
        if day.truck is not None:
            driver_to_trucks[day.driver].add(day.truck)
            truck_to_drivers[day.truck].add(day.driver)

    exclusive_pairs = {}
    non_exclusive_drivers = set()
    holiday_drivers = set()

    for driver in drivers:
        trucks_driven = driver_to_trucks.get(driver)
        
        if not trucks_driven:
            holiday_drivers.add(driver)
        elif len(trucks_driven) == 1:
            truck = next(iter(trucks_driven))
            if len(truck_to_drivers.get(truck, [])) == 1:
                exclusive_pairs[driver] = truck
            else:
                non_exclusive_drivers.add(driver)
        else:
            non_exclusive_drivers.add(driver)

    exclusive_trucks = set(exclusive_pairs.values())
    non_exclusive_trucks = set(trucks) - exclusive_trucks

    return {
        'exclusive_pairs': exclusive_pairs,
        'non_exclusive_drivers': non_exclusive_drivers,
        'non_exclusive_trucks': non_exclusive_trucks,
        'holiday_drivers': holiday_drivers,
    }

def calculate_weekly_metrics(
    drivers: list[Driver], 
    trucks: list[Truck], 
    start_date: date, 
    end_date: date
) -> dict:
    waiting_on_mileage_data = False
    estimated = False
    driver_data = {}
    truck_data = {}
    grand_total_data = {}

    days = Day.query.filter(
        Day.date >= start_date,
        Day.date <= end_date
    ).all()

    expenses = get_expenses_for_period(start_date, end_date) # This gets expenses for *one* truck

    week_estimated = False

    classified_sets = classify_entities(drivers, trucks, days)

    for driver in drivers:
        
        driver_data[driver.id] = calculate_driver_metrics_week(
            driver, start_date, end_date)

        if driver_data[driver.id]['wages_estimated'] == True:
            week_estimated = True

        driver_data[driver.id].setdefault('total_fuel_cost', 0)
        driver_data[driver.id].setdefault('total_fuel_volume', 0)
        driver_data[driver.id]['fuel_estimated'] = False
        driver_data[driver.id].setdefault('profit', 0)
        driver_data[driver.id].setdefault('expenses', 0)
        driver_data[driver.id]['truck_reg'] = None


        #Determine whether driver is mutually exclusive
        if driver in classified_sets['exclusive_pairs']:

            truck = classified_sets['exclusive_pairs'][driver]

            #Calculate truck metrics for mutually exclusive driver
            truck_data = calculate_truck_metrics_week(
                truck, start_date, end_date
            )
            fuel_cost = truck_data['total_fuel_cost']
            fuel_volume = truck_data['total_fuel_volume']
            fuel_estimated = truck_data['fuel_estimated']

            driver_data[driver.id]['total_fuel_cost'] = fuel_cost
            driver_data[driver.id]['total_fuel_volume'] = fuel_volume
            driver_data[driver.id]['fuel_estimated'] = fuel_estimated
            driver_data[driver.id]['truck_reg'] = truck.registration
            if fuel_estimated == True:
                week_estimated = True
        elif driver in classified_sets['holiday_drivers']:
            driver_data[driver.id]['truck_reg'] = '**Holiday'
            week_estimated = True
            #Remove wages from holiday drivers as holiday pay is included in expenses
            driver_data[driver.id]['total_cost_to_employer'] = 0
        else:
            total_mileage = driver_data[driver.id]['total_mileage']
            estimated_fuel_volume = round(total_mileage / MEDIAN_MILES_PER_LITRE)
            estimated_fuel_cost = round(estimated_fuel_volume * MEDIAN_POUNDS_PER_LITRE)

            driver_data[driver.id]['total_fuel_volume'] = estimated_fuel_volume
            driver_data[driver.id]['total_fuel_cost'] = estimated_fuel_cost
            driver_data[driver.id]['fuel_estimated'] = True
            driver_data[driver.id]['truck_reg'] = '**Multiple'
            week_estimated = True

        # for truck in trucks:
        #     if driver_data[driver.id]['truck'] is not None and driver_data[driver.id]['truck'].id == truck.id:
        #         driver_data[driver.id]['truck_data'] = calculate_truck_metrics_week(
        #             truck, start_date, end_date
        #         )
        #         # print(driver_data[driver.id]['truck_data']['truck'].id, driver_data[driver.id]['truck_data']['estimated'])
        #         if driver_data[driver.id]['truck_data']['total_fuel_cost'] == 0:
        #             waiting_on_mileage_data = True
        #         if driver_data[driver.id]['estimated'] == True or driver_data[driver.id]['truck_data']['estimated'] == True:
        #             estimated = True

        #     truck_data[truck.id] = calculate_truck_metrics_week(
        #         truck, start_date, end_date
        #     )

        # if driver_data[driver.id]['truck_data'] is not None:
        #     total_fuel_cost = driver_data[driver.id]['truck_data']['total_fuel_cost']
        # else:
        #     total_fuel_cost = 0
        total_earned = driver_data[driver.id]['total_earned']
        total_cost_to_employer = driver_data[driver.id]['total_cost_to_employer']
        total_fuel_cost = driver_data[driver.id]['total_fuel_cost']
        driver_overhead_allocation = calculate_total_metric_list('cost', expenses) # Calculate total expense from the list for *that one truck*
        profit = total_earned - total_fuel_cost - total_cost_to_employer - driver_overhead_allocation

        driver_data[driver.id]['total_expenses'] = driver_overhead_allocation
        driver_data[driver.id]['total_profit'] = profit

    total_fuel_cost_by_truck = 0

    for truck in trucks:

        truck_data[truck.id] = calculate_truck_metrics_week(
            truck, start_date, end_date
        )
        total_fuel_cost_by_truck += truck_data[truck.id]['total_fuel_cost']

    print(total_fuel_cost_by_truck)

    #Calculate expenses for all drivers
    number_of_drivers = len(drivers)
    total_expenses_for_week = driver_overhead_allocation * number_of_drivers

    #Aggregate totals for the week
    grand_total_earned = calculate_total_metric_dict('total_earned', driver_data)
    grand_total_wages = calculate_total_metric_dict('total_cost_to_employer', driver_data)
    grand_total_fuel_volume = calculate_total_metric_dict('total_fuel_volume', driver_data)
    grand_total_fuel_cost = total_fuel_cost_by_truck
    grand_total_profit = grand_total_earned - grand_total_wages - total_expenses_for_week - grand_total_fuel_cost

    grand_total_data = {
        'grand_total_earned': grand_total_earned,
        'grand_total_expenses': total_expenses_for_week,
        'grand_total_fuel_volume': grand_total_fuel_volume,
        'grand_total_wages': grand_total_wages,
        'grand_total_fuel_cost': grand_total_fuel_cost,
        'grand_total_profit': grand_total_profit,
    }

    return {
        # 'waiting_on_mileage_data': waiting_on_mileage_data,
        # 'truck_data': truck_data,
        'driver_data': driver_data,
        'grand_total_data': grand_total_data,
        'week_estimated': week_estimated,
    }

def get_weeks_for_month(weeks_data: list, target_year: int, target_month: int) -> list:
    return [week for week in weeks_data if week['year'] == target_year and week['month'] == target_month]

def calculate_monthly_metrics(weeks_data: list, drivers: list, trucks: list, target_year: int, target_month: int) -> dict: 
    month_weeks = get_weeks_for_month(weeks_data, target_year, target_month)
    
    # Initialize the main dictionary to hold all monthly data
    monthly_totals = {
        'weeks_count': len(month_weeks),
        'grand_total_data': {
            'month_estimated': False,
            'month_total_earned': 0,
            'month_total_expenses': 0,
            'month_total_fuel_volume': 0,
            'month_total_wages': 0,
            'month_total_fuel_cost': 0,
            'month_total_profit': 0,
        },
        'week_data': {
            (week['year'], week['week_number']): {
                'week_estimated': False,
                'week_total_earned': 0,
                'week_total_wages': 0,
                'week_total_expenses': 0,
                'week_total_fuel_volume': 0,
                'week_total_fuel_cost': 0,
                'week_total_profit': 0,
                'week_start_date': week['week_start_date'],
                'week_end_date': week['week_end_date'],
            } for week in month_weeks
        },
        # NOT INCLUDING THE DRIVER TOTALS FOR NOW # 
        # 'driver_data': {driver.id: {
        #     'estimated': False,
        #     'driver': driver,
        #     'total_earned': 0,
        #     'total_daily_bonus': 0,
        #     'total_weekly_bonus': 0,
        #     'total_overnight': 0,
        #     'total_cost_to_employer': 0,
        #     'total_expenses': 0,
        #     'total_profit': 0,
        #     'truck_assignments': [],
        #     'truck_used': None,
        #     'truck_data':{
        #         'estimated': False,
        #         'total_fuel_volume': 0,
        #         'total_fuel_cost': 0,
        #         'total_mileage': 0,
        #     }
        # } for driver in drivers},
    }

    # Loop through each week that has data for the selected month
    for week in month_weeks:
        # Calculate all metrics for the current week
        weekly_metrics = calculate_weekly_metrics(
            drivers, 
            trucks, 
            week['week_start_date'], 
            week['week_end_date']
        )

        weekly_grand_totals = weekly_metrics['grand_total_data']
        week_key = (week['year'], week['week_number'])

        # --- Populate the data for the specific week ---
        week_data = monthly_totals['week_data'][week_key]
        week_data['week_total_earned'] = weekly_grand_totals['grand_total_earned']
        week_data['week_total_wages'] = weekly_grand_totals['grand_total_wages']
        week_data['week_total_expenses'] = weekly_grand_totals['grand_total_expenses']
        week_data['week_total_fuel_volume'] = weekly_grand_totals['grand_total_fuel_volume']
        week_data['week_total_fuel_cost'] = weekly_grand_totals['grand_total_fuel_cost']
        week_data['week_total_profit'] = weekly_grand_totals['grand_total_profit']
        
        # Mark if the week's data is estimated
        if weekly_metrics.get('week_estimated', False):
            week_data['week_estimated'] = True
            monthly_totals['grand_total_data']['month_estimated'] = True
        
        # --- Aggregate the weekly totals into the month's grand totals ---
        grand_total_data = monthly_totals['grand_total_data']
        grand_total_data['month_total_earned'] += weekly_grand_totals['grand_total_earned']
        grand_total_data['month_total_wages'] += weekly_grand_totals['grand_total_wages']
        grand_total_data['month_total_expenses'] += weekly_grand_totals['grand_total_expenses']
        grand_total_data['month_total_fuel_volume'] += weekly_grand_totals['grand_total_fuel_volume']
        grand_total_data['month_total_fuel_cost'] += weekly_grand_totals['grand_total_fuel_cost']
        grand_total_data['month_total_profit'] += weekly_grand_totals['grand_total_profit']

        # NOT INCLUDING THE DRIVER TOTALS FOR NOW #
        # # Aggregate driver data
        # for driver_id, data in driver_data.items():
        #     driver_data = monthly_totals['driver_data'][driver_id]
        #     driver_data['total_earned'] += data['total_earned']
        #     driver_data['total_overnight'] += data['total_overnight']
        #     driver_data['total_cost_to_employer'] += data['total_cost_to_employer']
        #     driver_data['total_profit'] += data['total_profit']
        #     driver_data['total_expenses'] = driver_overhead_allocation

        #     if data['truck_data'] is not None:
        #         truck_data = monthly_totals['driver_data'][driver_id]['truck_data']
        #         truck_data['total_fuel_cost'] += data['truck_data']['total_fuel_cost']
        #         truck_data['total_fuel_volume'] += data['truck_data']['total_fuel_volume']
        #         truck_data['total_mileage'] += data['truck_data']['total_mileage']
            
        #     if data['truck']:
        #         driver_data['truck_assignments'].append(data['truck'].id)
            
        #     if data.get('estimated', False):
        #         driver_data['estimated'] = True

    return monthly_totals

def is_complete_month(month_weeks: list, year: int, month: int) -> bool:
    """
    Check if all weeks for a given month are present.
    A complete month has all Saturdays that fall within it.
    """
    # Get first day of month
    first_day = date(year, month, 1)
    
    # Get last day of month
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = next_month - timedelta(days=1)
    
    # Find first Saturday of month
    days_until_saturday = (5 - first_day.weekday()) % 7
    first_saturday = first_day + timedelta(days=days_until_saturday)
    
    # Count expected Saturdays in month
    expected_weeks = 0
    current_saturday = first_saturday
    while current_saturday <= last_day:
        expected_weeks += 1
        current_saturday += timedelta(days=7)
        
    return len(month_weeks) == expected_weeks

def validate_month_data(weeks_data: list, year: int, month: int) -> tuple[bool, str]:
    month_weeks = get_weeks_for_month(weeks_data, year, month)
    if not month_weeks:
        return False, f"No data available for {month}/{year}"
    
    if not is_complete_month(month_weeks, year, month):
        return False, f"Incomplete data for {month}/{year}"
        
    return True, "Month data is complete"

# Then in your route:
# is_valid, message = validate_month_data(weeks_data, target_year, target_month)
# if is_valid:
#     monthly_metrics = calculate_monthly_metrics(weeks_data, drivers, trucks, target_year, target_month)

def get_weekly_report_data_agg(year, week_number):
    """
    Returns the aggregated weekly report data for a given week.
    """
    # Get the start and end dates of the week
    start_date, end_date = get_start_and_end_of_week(year, week_number)

    # Determine the overall status for the week
    overall_period_status = "Complete" # Default for past week
    if end_of_week >= date.today(): # If week ends today or in future, it's partial
        overall_period_status = "Partial/Estimated"

    # 1. Query Days with Mileage (for estimated fuel)
    days_in_period_query = db.session.query(Day).\
        filter(Day.date >= start_of_week, Day.date <= end_of_week).\
        all()
    days_lookup = {display_date(d.date): d for d in days_in_period_query}

    # 2. Query Jobs
    jobs_for_period = db.session.query(Job, Driver).\
        join(Driver).\
        filter(Job.date >= start_of_week, Job.date <= end_of_week).\
        order_by(Driver.id, Job.date).\
        all()

    # 3. Query Fuel Entries (Actuals)
    fuel_entries_for_period = db.session.query(FuelEntry, Truck).\
        outerjoin(Truck).\
        filter(FuelEntry.date >= start_of_week, FuelEntry.date <= end_of_week).\
        all()

    # 4. Query Wage Entries (Actuals)
    wage_entries_for_period = db.session.query(WageEntry, Driver).\
        join(Driver).\
        filter(WageEntry.date >= start_of_week, WageEntry.date <= end_of_week).\
        all()

    # --- Initialize Aggregation Structure ---
    # defaultdicts are used for dynamic aggregation
    drivers_data = defaultdict(lambda: {
        "driver_id": None, 
        "driver_name": None,
        "truck_id": None,
        "weekly_earned": 0.0, 
        "weekly_estimated_fuel_sum": 0.0, 
        "weekly_actual_fuel_sum": 0.0,
        "weekly_calculated_wage_sum": 0.0,
        "weekly_estimated_cost_to_employer": 0.0,
        "weekly_actual_cost_to_employer": 0.0,
        "weekly_total_costs_best_available": 0.0,
        "weekly_net_profit_best_available": 0.0,
        "weekly_fuel_status": "Estimated/Actual",
        "weekly_cost_to_employer_status": "Estimated/Actual",
        "days_worked": 0,
        "days_absent": 0,
        "days_holiday": 0,
        "daily_breakdown": defaultdict(lambda: { # Will hold data only for days with activity
            "day_id": None,
            "date": None,
            "status": "working",
            "day_start_mileage": 0.0,
            "day_end_mileage": 0.0,
            "day_mileage_diff": 0.0,
            "daily_earned": 0.0, 
            "overnight": False,
            "fuel_flag": False,
            "daily_bonus": 0.0,
            "daily_estimated_fuel_sum": 0.0,
            "jobs": [], 
            "fuel_entries_details": [],
            "wage_entries_details": [],
            "status": "No data" # Initial status, updated if data is found
        })
    })