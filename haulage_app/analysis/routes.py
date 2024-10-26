from flask import render_template, request, url_for
from haulage_app import db, f
from haulage_app.models import Driver, Day, Job, Truck, Fuel, Expense, ExpenseOccurrence
from datetime import timedelta, date, datetime
from haulage_app.analysis import analysis_bp
from pprint import pprint

def get_week_number_sat_to_fri(date):
    """Returns the week number with Saturday as the start of the week."""
    # Shift the day of the week so Saturday is 0, Sunday is 1, etc.
    shifted_date = date - timedelta(days=2)
    # Use the year and ISO week number of the week's start date
    return (shifted_date.year, shifted_date.isocalendar().week)

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

    print(total_cost)
    return total_cost

def calculate_fuel_economy(mileage, fuel_volume):
    # Calculate fuel economy based on the given mileage and fuel cost
    # You can use your own formula or logic here
    # For example, you can divide the mileage by the fuel cost
    return round(mileage / fuel_volume * 3.78541)

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

            average_miles_per_litre = 2.9
            average_pound_per_litre = 1.19

            total_fuel_volume = sum(f.display_float(fuel.fuel_volume) for fuel in fuel_entries)
            total_fuel_cost = sum(f.display_float(fuel.fuel_cost) for fuel in fuel_entries)        
            total_mileage = sum((f.display_float(day.end_mileage)-f.display_float(day.start_mileage)) for day in day_entries)
            est_fuel_volume = round(total_mileage / average_miles_per_litre)
            est_fuel_cost = round(est_fuel_volume * average_pound_per_litre)
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



