from haulage_app.config import *

def calculate_driver_wages(day_entries, driver):
    total_earned = 0
    total_overnight = 0
    total_daily_bonus = 0
    total_weekly_bonus = 0
    gross_pay = 0
    for day in day_entries:
        # Calculate total earned by driver for week
        total_earned += day.calculate_total_earned()
        # Calculate daily bonus accumilated by driver for week
        daily_bonus = day.calculate_daily_bonus(driver)
        total_daily_bonus += daily_bonus
        # Calculate total overnight for week
        if day.overnight == True:
            total_overnight += 3000
    # Calculate weekly bonus
    if total_earned > driver.weekly_bonus_threshold:
        total_weekly_bonus = (total_earned - driver.weekly_bonus_threshold) * driver.weekly_bonus_percentage
    
    weekly_extras = total_daily_bonus - (15000 - total_overnight)
    gross_pay = weekly_extras + driver.basic_wage

    return total_earned, weekly_extras, gross_pay

def calculate_driver_metrics_for_week(driver, Day, Job, Payslip, start_date, end_date):

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

    total_earned, weekly_extras, gross_pay = calculate_driver_wages(day_entries, driver)

    if payslip_entries:
        total_cost_to_employer = payslip_entries[0].total_wage
    elif gross_pay > 0: 
        estimated = True
        total_cost_to_employer = gross_pay * TAX_NI_MULTIPLIER
    else:
        total_cost_to_employer = 0

    return {
        'driver': driver,
        'day_entries': day_entries,
        'job_entries': job_entries,
        'total_earned': total_earned,
        'gross_pay': gross_pay,
        'total_cost_to_employer': total_cost_to_employer,
        'weekly_extras': weekly_extras,
        'start_date': start_date,
        'end_date': end_date,
        'estimated': estimated
    }