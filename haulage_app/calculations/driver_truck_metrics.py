from haulage_app.config import *
from haulage_app.functions import *

# DRIVER METRICS

def calculate_driver_wages(day_entries, driver):
    total_earned = 0
    total_overnight = 0
    total_daily_bonus = 0
    total_weekly_bonus = 0
    gross_pay = 0
    worked_days = 0
    for day in day_entries:
        # Calculate total earned by driver for week
        total_earned += day.calculate_total_earned()
        # Calculate daily bonus accumilated by driver for week
        daily_bonus = day.calculate_daily_bonus(driver)
        total_daily_bonus += daily_bonus
        # Calculate total overnight for week
        if day.status == 'working':
            worked_days += 1
        if day.overnight == True:
            total_overnight += 3000

    # Calculate weekly bonus
    if total_earned > driver.weekly_bonus_threshold:
        total_weekly_bonus = (total_earned - driver.weekly_bonus_threshold) * driver.weekly_bonus_percentage

    # Calculate gross pay and weekly extras
    if worked_days <= 3 or total_earned < 150000:
        weekly_extras = total_daily_bonus + total_weekly_bonus
        gross_pay = weekly_extras + driver.basic_wage
    else:
        weekly_extras = total_daily_bonus + total_weekly_bonus - (15000 - total_overnight)
        gross_pay = weekly_extras + driver.basic_wage
        total_overnight = 15000

    return total_earned, weekly_extras, gross_pay, total_overnight


def calculate_driver_metrics_week(driver, Day, Job, Payslip, start_date, end_date):

    estimated = False
    
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
    
    

    total_earned, weekly_extras, gross_pay, total_overnight = calculate_driver_wages(day_entries, driver)

    if payslip_entries:
        gross_pay = payslip_entries[0].total_wage
        total_cost_to_employer = payslip_entries[0].total_cost_to_employer
    elif gross_pay > 0: 
        estimated = True
        total_cost_to_employer = gross_pay * TAX_NI_MULTIPLIER
    else:
        total_cost_to_employer = 0

    return {
        'estimated': estimated,
        'driver': driver,
        'day_entries': day_entries,
        'job_entries': job_entries,
        'total_earned': total_earned,
        'gross_pay': gross_pay,
        'total_overnight': total_overnight,
        'total_cost_to_employer': total_cost_to_employer,
        'weekly_extras': weekly_extras,
        'start_date': start_date,
        'end_date': end_date
    }


# TRUCK METRICS
def calculate_fuel_economy(mileage, fuel_volume):
    # Calculate fuel economy based on the given mileage and fuel cost
    return round((mileage / fuel_volume) * LITRE_TO_GALLON_MULTIPLIER, 2)


def calculate_total_metric_list(metric_name, list_of_entries):
    """ Calculate the total of a metric for a list of entries from a query """
    return sum(getattr(item, metric_name) for item in list_of_entries)


def calculate_total_metric_dict(metric_name, dict):
    """ Calculate the total of a metric for a list of entries from a query """
    return sum(item[metric_name] for item in dict.values())


def calculate_total_mileage(day_entries):
    """ Calculate the total mileage for a list of day entries """
    return sum((day.end_mileage - day.start_mileage) for day in day_entries)


def calculate_truck_metrics_week(truck, Day, Fuel, start_date, end_date):

    estimated = False

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

    total_mileage = calculate_total_mileage(day_entries)
    if fuel_entries:
        total_fuel_volume = round(calculate_total_metric_list("fuel_volume", fuel_entries))
        total_fuel_cost = calculate_total_metric_list("fuel_cost", fuel_entries)
        fuel_economy = calculate_fuel_economy(total_mileage, total_fuel_volume)
    else:
        estimated = True
        total_fuel_volume = round(total_mileage / MEDIAN_MILES_PER_LITRE)
        total_fuel_cost = round(total_fuel_volume * MEDIAN_POUNDS_PER_LITRE)
        fuel_economy = 0


    return {
        'estimated': estimated,
        'truck': truck,
        'total_mileage': total_mileage,
        'total_fuel_volume': total_fuel_volume,
        'total_fuel_cost': total_fuel_cost,
        'fuel_economy': fuel_economy,
        'start_date': start_date,
        'end_date': end_date,
    }
