from flask import render_template, request
from haulage_app import db, f
from haulage_app.models import Driver, Day, Job
from datetime import timedelta, date, datetime
from haulage_app.wages_calculator import wages_calculator_bp

@wages_calculator_bp.route("/wages_calculator", methods=["GET"])
def wages_calculator():
    drivers = list(Driver.query.order_by(Driver.first_name).all())

    today = datetime.utcnow().date()
    start_date = today - timedelta(days=(today.weekday() + 2) % 7)
    end_date = start_date + timedelta(days=6)

    driver_data = {}

    for driver in drivers:
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

        # Calculate wages for each driver
        weekly_total_earned = 0
        weekly_total_overnight = 0
        weekly_total_bonus_wage = 0
        weekly_total_wage = 0
        weekly_bonus = 0
        for day in day_entries:
            day.daily_bonus = day.calculate_daily_bonus(driver)
            weekly_total_bonus_wage += day.daily_bonus
            weekly_total_earned += day.calculate_total_earned()
            if day.overnight == True:
                weekly_total_overnight += 3000
        if weekly_total_earned > driver.weekly_bonus_threshold:
            weekly_bonus = (weekly_total_earned - driver.weekly_bonus_threshold) * driver.weekly_bonus_percentage
            weekly_total_bonus_wage += weekly_bonus
        weekly_extras = weekly_total_bonus_wage - (15000 - weekly_total_overnight)
        weekly_total_wage = weekly_extras + driver.basic_wage

        driver_data[driver.id]={
            'driver': driver,
            'day_entries': day_entries,
            'weekly_total_earned': weekly_total_earned,
            'weekly_total_overnight': weekly_total_overnight,
            'weekly_total_bonus_wage': weekly_total_bonus_wage,
            'weekly_total_wage': weekly_total_wage,
            'weekly_bonus': weekly_bonus,
            'weekly_extras': weekly_extras,
            'start_date': start_date,
            'end_date': end_date,
            'job_entries': job_entries
        }

    return render_template("wages_calculator.html", driver_data=driver_data, drivers=drivers, start_date=start_date, end_date=end_date)
