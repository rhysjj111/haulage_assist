from flask import render_template, request, url_for
from haulage_app import db, f
from haulage_app.models import Driver, Day, Job, Truck, Fuel
from datetime import timedelta, date, datetime
from haulage_app.analysis import analysis_bp
from pprint import pprint

def get_week_number_sat_to_fri(date):
    """Returns the week number with Saturday as the start of the week."""
    # Shift the day of the week so Saturday is 0, Sunday is 1, etc.
    shifted_date = date - timedelta(days=2)
    # Use the year and ISO week number of the week's start date
    return (shifted_date.year, shifted_date.isocalendar().week)


@analysis_bp.route("/weekly_analysis", methods=["GET"])
def weekly_analysis():
    # Get all days in the database
    all_days = Day.query.all()
    # Extract dates from the days
    dates = [day.date for day in all_days]
    # pprint(dates)
    # Calculate week numbers for each day
    week_numbers = [get_week_number_sat_to_fri(day.date) for day in all_days]
    # pprint(week_numbers)
    available_weeks = sorted(set(week_numbers), reverse=True)
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())
    driver_data = {}
    truck_data = {}
    start_date = date.today()

    if request.args.get('week_select'):
        selected_week = request.args.get('week_select')
        selected_year, selected_week_number = map(int, selected_week.split('-'))
        # Calculate start date (Saturday) of the selected week
        start_date = date(selected_year, 1, 1) + timedelta(
            days=(selected_week_number - 1) * 7 - (date(selected_year, 1, 1).weekday() + 2) % 7
        )
        end_date = start_date + timedelta(days=6)
        # print(start_date, end_date)

        
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

            total_fuel = sum(f.display_currency(fuel.fuel_volume) for fuel in fuel_entries)  
            print(total_fuel)         
            total_mileage = sum((f.display_currency(day.end_mileage)-f.display_currency(day.start_mileage)) for day in day_entries)
            print(total_mileage)
            
            truck_data[truck.id]={
                'truck': truck,
                'total_mileage': total_mileage,
                'start_date': start_date,
                'end_date': end_date,
            }


        



    return render_template(
        'analysis/weekly_analysis.html',
        available_weeks=available_weeks, 
        drivers=drivers, 
        driver_data=driver_data,
        truck_data=truck_data,
        start_date=start_date,
    )



