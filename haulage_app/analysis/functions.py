from sqlalchemy import cast, Integer
from haulage_app.models import ExpenseOccurrence, Payslip, db, Driver, Truck, Day, Fuel
from datetime import datetime, timedelta, date
from haulage_app.calculations.driver_truck_metrics import (
    calculate_driver_metrics_week,
    calculate_truck_metrics_week,
    calculate_total_metric_list,
    calculate_total_metric_dict,
)
from pprint import pprint

def get_formatted_payslip_weeks():
    """
    Retrieves all unique week numbers and years from Payslip table and formats them
    into a list of dictionaries. Each dictionary contains the week number and year,
    sorted in descending order by year and week number.
    
    Returns:
        list: List of dicts with format [{'week_number': int, 'year': int}, ...]
    """
    week_numbers = Payslip.query.with_entities(
        cast(db.extract('year', Payslip.date), Integer).label('year'),
        Payslip.week_number
    ).distinct().order_by(
        db.desc('year'), 
        db.desc(Payslip.week_number)
    ).all()
    # query = Fuel.query.order_by(Fuel.date).all()
    # for qu in query:
    #     print(qu.date, qu.week_number)

    formatted_weeks = []
    for year, week_number in week_numbers:
        week_start_date, week_end_date = get_start_and_end_of_week(year, week_number)
        year, month = get_year_and_month_of_week(year, week_number)
        formatted_weeks.append({
            'year': year,
            'week_number': week_number,
            'week_start_date': week_start_date,
            'week_end_date': week_end_date,
            'month': month,
        })
    
    return formatted_weeks

def find_previous_saturday(date):
    """
    Finds the previous Saturday before a given date.
    """
    days_to_subtract = (date.weekday() + 2) % 7  # 0 for Saturday, 1 for Sunday, ...
    return date - timedelta(days=days_to_subtract)

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

def get_week_number_sat_to_fri(date_obj):
    """
    Returns the week number for a given date, using Saturday to Friday as the week period,
    with week 1 starting from the first Tuesday of the year.
    
    Args:
        date: datetime.date object
    Returns:
        tuple: (year, week_number)
    """
    year = date_obj.year
    first_tuesday = date(year, 1, 1)
    
    # Find first Tuesday of the year
    while first_tuesday.weekday() != 1:  # 1 represents Tuesday
        first_tuesday += timedelta(days=1)

    first_saturday = first_tuesday - timedelta(days=3) 
        
    # Adjust date back to the Saturday that starts its week
    adjusted_date = find_previous_saturday(date_obj)
    
    # Calculate days between first Tuesday and adjusted date
    days_since_first_saturday = (adjusted_date - first_saturday).days
    
    # Calculate week number, accounting for partial first week
    if days_since_first_saturday < 0:
        # Date falls in previous year's last week
        return get_week_number_sat_to_fri(date(year-1, 12, 31))
    
    week_number = (days_since_first_saturday // 7) + 1
    return (year, week_number)

def get_year_and_month_of_week(year: int, week_number: int) -> int:
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
    # print(year, week_number)
    target_date = start_date + timedelta(days=3) # Tuesday
    return target_date.year, target_date.month

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

    expenses = get_expenses_for_period(start_date, end_date)

    for driver in drivers:
        driver_data[driver.id] = calculate_driver_metrics_week(
            driver, start_date, end_date)
        
        driver_data[driver.id]['truck_data'] = None
        driver_data[driver.id].setdefault('profit', 0)
        driver_data[driver.id].setdefault('expenses', 0)

        for truck in trucks:
            if driver_data[driver.id]['truck'] is not None and driver_data[driver.id]['truck'].id == truck.id:
                driver_data[driver.id]['truck_data'] = calculate_truck_metrics_week(
                    truck, start_date, end_date
                )
                if driver_data[driver.id]['truck_data']['total_fuel_cost'] == 0:
                    waiting_on_mileage_data = True
                if driver_data[driver.id]['estimated'] == True or driver_data[driver.id]['truck_data']['estimated'] == True:
                    estimated = True

            truck_data[truck.id] = calculate_truck_metrics_week(
                truck, start_date, end_date
            )

        total_earned = driver_data[driver.id]['total_earned']
        if driver_data[driver.id]['truck_data'] is not None:
            total_fuel_cost = driver_data[driver.id]['truck_data']['total_fuel_cost']
        else:
            total_fuel_cost = 0
        total_cost_to_employer = driver_data[driver.id]['total_cost_to_employer']
        total_expense = calculate_total_metric_list('cost', expenses)

        profit = total_earned - total_fuel_cost - total_cost_to_employer - total_expense
        print(total_expense)
        driver_data[driver.id]['expense'] = total_expense
        driver_data[driver.id]['profit'] = profit

    total_expenses = total_expense * 3
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

    return {
        'waiting_on_mileage_data': waiting_on_mileage_data,
        'estimated': estimated,
        'driver_data': driver_data,
        'truck_data': truck_data,
        'grand_total_data': grand_total_data
    }

def get_weeks_for_month(weeks_data: list, target_year: int, target_month: int) -> list:
    return [week for week in weeks_data if week['year'] == target_year and week['month'] == target_month]


def calculate_monthly_metrics(weeks_data: list, drivers: list, trucks: list, target_year: int, target_month: int) -> dict:
    month_weeks = get_weeks_for_month(weeks_data, target_year, target_month)
    
    monthly_totals = {
        'weeks_count': len(month_weeks),
        'grand_total_data': {
            'estimated': False,
            'grand_total_earned': 0,
            'grand_total_expenses': 0,
            'grand_total_fuel_volume': 0,
            'grand_total_wages': 0,
            'grand_total_fuel_cost': 0,
            'profit': 0,
        },
        'driver_data': {driver.id: {
            'estimated': False,
            'driver': driver,
            'total_earned': 0,
            'total_overnight': 0,
            'total_cost_to_employer': 0,
            'expenses': 0,
            'profit': 0,
            'truck_assignments': [],
            'truck_used': None,
            'truck_data':{
                'estimated': False,
                'total_fuel_volume': 0,
                'total_fuel_cost': 0,
                'total_mileage': 0,
            }
        } for driver in drivers},
    }

    expected_weeks = get_expected_weeks_in_month(target_year, target_month)
    start_date, end_date = get_start_and_end_of_week(target_year, expected_weeks['week_numbers'][0])
    one_week_expenses = calculate_total_metric_list('cost', get_expenses_for_period(start_date, end_date))

    expenses_for_one_truck = one_week_expenses * expected_weeks['total_weeks']

    total_expenses = expenses_for_one_truck * 3 # The number of current trucks (3).

    monthly_totals['grand_total_data']['grand_total_expenses'] = one_week_expenses * expected_weeks['total_weeks'] * 3

    for week in month_weeks:
        weekly_metrics = calculate_weekly_metrics(drivers, trucks, 
                                            week['week_start_date'], 
                                            week['week_end_date'])

        # if month_weeks[0]:
        #     pprint(weekly_metrics)

        # pprint(weekly_metrics)
        grand_total_data = weekly_metrics['grand_total_data']
        driver_data = weekly_metrics['driver_data']
        truck_data = weekly_metrics['truck_data']
        estimated = weekly_metrics['estimated']
        
        # Standard totals aggregation
        monthly_totals['grand_total_data']['grand_total_earned'] += grand_total_data['grand_total_earned']
        monthly_totals['grand_total_data']['grand_total_fuel_volume'] += grand_total_data['grand_total_fuel_volume']
        monthly_totals['grand_total_data']['grand_total_wages'] += grand_total_data['grand_total_wages']
        monthly_totals['grand_total_data']['grand_total_fuel_cost'] += grand_total_data['grand_total_fuel_cost']
        monthly_totals['grand_total_data']['profit'] += grand_total_data['profit']
        
        if estimated:
            monthly_totals['grand_total_data']['estimated'] = True
        
        # Aggregate driver data
        for driver_id, data in driver_data.items():
            driver_data = monthly_totals['driver_data'][driver_id]
            driver_data['total_earned'] += data['total_earned']
            driver_data['total_overnight'] += data['total_overnight']
            driver_data['total_cost_to_employer'] += data['total_cost_to_employer']
            driver_data['profit'] += data['profit']
            driver_data['expenses'] = expenses_for_one_truck

            if data['truck_data'] is not None:
                truck_data = monthly_totals['driver_data'][driver_id]['truck_data']
                truck_data['total_fuel_cost'] += data['truck_data']['total_fuel_cost']
                truck_data['total_fuel_volume'] += data['truck_data']['total_fuel_volume']
                truck_data['total_mileage'] += data['truck_data']['total_mileage']
            
            if data['truck']:
                driver_data['truck_assignments'].append(data['truck'].id)
            
            if data.get('estimated', False):
                driver_data['estimated'] = True


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