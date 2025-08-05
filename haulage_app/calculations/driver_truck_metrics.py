from haulage_app.config import *
from haulage_app.functions import *
from haulage_app.models import (
    Driver, Day, Job, Truck, Fuel, Expense,
    ExpenseOccurrence, Payslip)
from collections import Counter

def calculate_fuel_economy(mileage, fuel_volume):
    # Calculate fuel economy based on the given mileage and fuel cost
    if mileage > 0 and fuel_volume > 0:
        return round((mileage / fuel_volume) * LITRE_TO_GALLON_MULTIPLIER, 2)
    return 0


def calculate_total_metric_list(metric_name, list_of_entries):
    """ Calculate the total of a metric for a list of entries from a query """
    return sum(getattr(item, metric_name) for item in list_of_entries)


def calculate_total_metric_dict(metric_name, dict):
    """ Calculate the total of a metric for a list of entries from a query """
    return sum(item[metric_name] for item in dict.values())


def calculate_total_mileage(day_entries):
    """ Calculate the total mileage for a list of day entries """
    return sum((day.end_mileage - day.start_mileage) for day in day_entries)

def most_frequent_truck_id(day_data):
  """
  Finds the truck_id that appears most often in a list of dictionaries.

  Args:
    truck_data: A list of dictionaries, where each dictionary 
                 has a 'truck_id' key.

  Returns:
    The truck_id that appears most frequently.
  """
  truck_ids = [day.truck_id for day in day_data]
  id_counts = Counter(truck_ids)

  return id_counts.most_common(1)[0][0]

def get_unique_truck_id(day_data):
    """
    Checks the truck_ids in the day_data and returns the unique truck_id if
    there is only one, otherwise returns None.

    Args:
        day_data: A list of dictionaries or objects with a 'truck_id' attribute.

    Returns:
        The unique truck_id if one exists, otherwise None.
    """
    truck_ids = {day.truck_id for day in day_data}
    if len(truck_ids) == 1:
        return truck_ids.pop()
    else:
        return None

# DRIVER METRICS

def calculate_driver_wages(day_entries, driver):
    """Calculate driver wages for a given week.

    Args:
        day_entries (list): List of Day objects for the week.
        driver (Driver): Driver object for the week.

    Returns:
        dict: Dictionary containing calculated metrics.
    """
    total_earned = 0
    total_overnight = 0
    total_daily_bonus = 0
    total_weekly_bonus = 0
    gross_pay = 0
    worked_days = 0
    recorded_days = 0
    total_mileage = 0
    overnight_count = 0
    days_summary = [] # Initialize the list for daily summaries
    for day in day_entries:
        daily_earned = day.calculate_total_earned()
        daily_bonus = day.calculate_daily_bonus(driver)
        daily_overnight = driver.overnight_value if day.overnight else 0
        day_mileage = day.end_mileage - day.start_mileage
        total_mileage += day_mileage
        
        # Aggregate totals
        total_earned += daily_earned
        recorded_days += 1
        total_daily_bonus += daily_bonus
        if day.status == 'working':
            worked_days += 1
        if day.overnight:
            overnight_count += 1
        total_overnight += daily_overnight

        jobs_summary = []
        for job in day.jobs:
            jobs_summary.append({
                'job_id': job.id,
                'collection': job.collection,
                'delivery': job.delivery,
                'earned': job.earned,
                'notes': job.notes,
                'split': job.split,
            })

        # Create daily summary dictionary
        days_summary.append({
            'day_id': day.id,
            'registration': day.truck.registration if day.truck else None,
            'driver_name': driver.full_name,
            'display_date': display_date(day.date),
            'date': day.date,
            'start_mileage': day.start_mileage,
            'end_mileage': day.end_mileage,
            'total_mileage': day_mileage,
            'total_earned': daily_earned,
            'daily_bonus': daily_bonus,
            'overnight_value': daily_overnight,
            'status': day.status,
            'jobs_summary': jobs_summary # Add the jobs summary to the daily summary
        })
        

    # Calculate weekly bonus
    if total_earned > driver.weekly_bonus_threshold:
        total_weekly_bonus = (total_earned - driver.weekly_bonus_threshold) * driver.weekly_bonus_percentage

    total_earned_threshold = 150000
    full_week_of_overnights = 15000
    # Calculate gross pay and weekly extras
    if worked_days <= 4 or total_earned < total_earned_threshold:
        # Calculate weekly extras normally
        weekly_extras = total_daily_bonus + total_weekly_bonus
    else:
        # Adjust for 5-day expense rule when applicable
        weekly_extras = total_daily_bonus + total_weekly_bonus - (full_week_of_overnights - total_overnight)
        total_overnight = full_week_of_overnights

    basic_wage = driver.basic_wage
    gross_pay = weekly_extras + driver.basic_wage + total_overnight
    metrics = {
        'basic_wage': basic_wage,
        'total_earned': total_earned,
        'total_daily_bonus': total_daily_bonus,
        'total_weekly_bonus': total_weekly_bonus,
        'total_overnight': total_overnight,
        'weekly_extras': weekly_extras,
        'calculated_gross_pay': gross_pay,
        'total_mileage': total_mileage,
        'days_summary': days_summary,
        'worked_days': worked_days,
        'recorded_days': recorded_days,
        'overnight_count': overnight_count
    }
    return metrics


def calculate_driver_metrics_week(driver, start_date, end_date):
    """ Calculate driver metrics for a given week.

    Args:
        driver (Driver): Driver object for the week.
        start_date (date): Start date of the week.
        end_date (date): End date of the week.

    Returns:
        dict: Dictionary containing calculated metrics.
    """

    day_entries = Day.query.filter(
        Day.driver_id == driver.id,
        Day.date >= start_date,
        Day.date <= end_date
    ).order_by(Day.date).all()

    job_entries = Job.query.join(Day).filter(
        Day.driver_id == driver.id,
        Day.date >= start_date,
        Day.date <= end_date
    ).order_by(Day.date, Job.id).all()
        
    payslip_entries = Payslip.query.filter(
        Payslip.driver_id == driver.id,
        Payslip.date >= start_date,
        Payslip.date <= end_date
    ).order_by(Payslip.date).all()
    
    metrics = calculate_driver_wages(day_entries, driver)

    calculated_gross_pay = metrics['calculated_gross_pay']
    estimated_total_cost_to_employer = calculated_gross_pay * TAX_NI_MULTIPLIER

    actual_total_gross_pay = None
    actual_total_cost_to_employer = None

    # Consolidated values, assume estimated by default
    total_gross_pay = calculated_gross_pay
    total_cost_to_employer = estimated_total_cost_to_employer

    # Flags, assume estimated by default
    wages_estimated = True

    if payslip_entries:
        actual_total_gross_pay = payslip_entries[0].total_wage
        actual_total_cost_to_employer = payslip_entries[0].total_cost_to_employer
        
        total_gross_pay = actual_total_gross_pay
        total_cost_to_employer = actual_total_cost_to_employer
        wages_estimated = False
        

    return {
        'driver_id': driver.id,
        'driver_name': driver.full_name,
        'driver_first_name': driver.first_name,
        'driver_wage_parameters': {
            'basic_wage': driver.basic_wage,
            'weekly_bonus_percentage': driver.weekly_bonus_percentage,
            'weekly_bonus_threshold': driver.weekly_bonus_threshold,
            'overnight_value': driver.overnight_value,
        },
        'total_earned': metrics['total_earned'],
        'total_overnight': metrics['total_overnight'],
        'total_daily_bonus': metrics['total_daily_bonus'],
        'total_weekly_bonus': metrics['total_weekly_bonus'],
        'weekly_extras': metrics['weekly_extras'],
        'overnight_count': metrics['overnight_count'],

        # Gross Pay related fields
        'calculated_gross_pay': metrics['calculated_gross_pay'],
        'actual_total_gross_pay': actual_total_gross_pay,
        'total_gross_pay': total_gross_pay,

        # Cost to Employer related fields
        'estimated_total_cost_to_employer': estimated_total_cost_to_employer,
        'actual_total_cost_to_employer': actual_total_cost_to_employer,
        'total_cost_to_employer': total_cost_to_employer,

        'days_summary': metrics['days_summary'],
        'total_mileage': metrics['total_mileage'],
        'wages_estimated': wages_estimated,
        'worked_days': metrics['worked_days'],
        'recorded_days': metrics['recorded_days'],
    }


# TRUCK METRICS


def calculate_truck_metrics_week(truck, start_date, end_date):

    # Query all necessary entries for the week
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
        
    # expense_entries = ExpenseOccurrence.query.filter(
    #     ExpenseOccurrence.truck_id == truck.id,
    #     ExpenseOccurrence.date >= start_date,
    #     ExpenseOccurrence.date <= end_date
    # ).all()

    # Calculate total metrics
    total_earned = sum(day.calculate_total_earned() for day in day_entries)
    # total_expenses = calculate_total_metric_list("cost", expense_entries)
    total_mileage = calculate_total_mileage(day_entries)

    # Calculate fuel metrics, handling estimation if no fuel entries exist
    fuel_estimated = True
    estimated_total_fuel_volume = round(total_mileage / MEDIAN_MILES_PER_LITRE) if total_mileage > 0 else 0
    estimated_total_fuel_cost = round(estimated_total_fuel_volume * MEDIAN_POUNDS_PER_LITRE)
    fuel_economy = 0 # Cannot calculate economy without actual fuel data
    actual_total_fuel_volume = 0
    actual_total_fuel_cost = 0

    total_fuel_volume = estimated_total_fuel_volume
    total_fuel_cost = estimated_total_fuel_cost

    if fuel_entries:
        fuel_estimated = False
        actual_total_fuel_volume = round(calculate_total_metric_list("fuel_volume", fuel_entries))
        actual_total_fuel_cost = calculate_total_metric_list("fuel_cost", fuel_entries)
        fuel_economy = calculate_fuel_economy(total_mileage, total_fuel_volume)

        total_fuel_volume = actual_total_fuel_volume
        total_fuel_cost = actual_total_fuel_cost


    # # Identify primary driver and calculate their cost
    # driver_cost = 0
    # driver_metrics = None
    # # This logic assumes one primary driver for the truck for the week.
    # # A more complex scenario might involve multiple drivers.
    # if day_entries:
    #     driver_ids = {day.driver_id for day in day_entries}
    #     if len(driver_ids) == 1:
    #         primary_driver_id = driver_ids.pop()
    #         driver = Driver.query.get(primary_driver_id)
    #         if driver:
    #             # Get the driver's metrics for the same period
    #             driver_metrics = calculate_driver_metrics_week(driver, start_date, end_date)
    #             driver_cost = driver_metrics['total_cost_to_employer']


    # # Calculate true profit
    # profit = total_earned - total_fuel_cost - total_expenses - driver_cost
    
    return {
        'truck': truck,
        'truck_id': truck.id,
        'total_earned': total_earned,
        'total_mileage': total_mileage,
        'actual_total_fuel_volume': actual_total_fuel_volume,
        'actual_total_fuel_cost': actual_total_fuel_cost,
        'estimated_total_fuel_volume': estimated_total_fuel_volume,
        'estimated_total_fuel_cost': estimated_total_fuel_cost,
        'total_fuel_volume': total_fuel_volume,
        'total_fuel_cost': total_fuel_cost,
        'fuel_estimated': fuel_estimated,
        'fuel_economy': fuel_economy,
        'fuel_estimated': fuel_estimated,
        'start_date': start_date,
        'end_date': end_date,
        # Return raw entries for potential downstream use
        # 'day_entries': day_entries,
        # 'fuel_entries': fuel_entries,
        # 'total_expenses': total_expenses,
        # 'driver_cost': driver_cost,
        # 'profit': profit,
        # 'expense_entries': expense_entries,
        # Return the full driver metrics dictionary for context
        # 'driver_metrics': driver_metrics 
    }
