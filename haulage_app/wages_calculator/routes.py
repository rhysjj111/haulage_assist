from flask import render_template, request
from haulage_app import db, f
from haulage_app.models import Driver, Day
from datetime import timedelta, date, datetime
from haulage_app.wages_calculator import wages_calculator_bp


@wages_calculator_bp.route("/wages_calculator/reduncd", methods=["GET", "POST"])
def wages_calculator():
#     drivers = list(Driver.query.order_by(Driver.first_name).all())
#     if request.method == "POST":
#         # generate start and end date, from user submited date
#         date = request.form.get("search_date")
#         start_date = f.date_to_db(date)
#         end_date = start_date + timedelta(days=6)
#         # query day table based on user inputs of driver and date
#         driver_id = request.form.get("search_driver_id")
#         driver = Driver.query.get(driver_id)
#         day_entries = Day.query.filter(
#             Day.driver_id == driver_id, 
#             Day.date >= start_date, 
#             Day.date <= end_date).all()
#         # wages calculations
#         total_earned = 0
#         total_overnight = 0
#         total_bonus_wage = 0
#         total_wage = 0
#         weekly_bonus = 0
#         for day in day_entries:
#             total_bonus_wage += day.calculate_daily_bonus(driver)
#             total_earned += day.calculate_total_earned()
#             if day.overnight == True:
#                 total_overnight += 3000
#         if total_earned > driver.weekly_bonus_threshold:
#             weekly_bonus = (total_earned - driver.weekly_bonus_threshold) * driver.weekly_bonus_percentage
#             total_bonus_wage += weekly_bonus
#         total_wage = total_bonus_wage + total_overnight + driver.basic_wage     
        
#         return render_template("wages_calculator.html", date=start_date, driver=driver, 
#                                drivers=drivers, day_entries=day_entries, 
#                                total_earned=total_earned, total_overnight=total_overnight, 
#                                total_bonus_wage=total_bonus_wage, total_wage=total_wage, 
#                                weekly_bonus=weekly_bonus)
    return render_template("wages_calculator.html", drivers=drivers)

@wages_calculator_bp.route("/wages_calculator", methods=["GET"])
def wages_calculator_new():
    drivers = list(Driver.query.order_by(Driver.first_name).all())

    today = datetime.utcnow().date()
    start_date = today - timedelta(days=(today.weekday() + 2) % 7)
    end_date = start_date + timedelta(days=6)

    driver_data = {}

    for driver in drivers:
        day_entries = Day.query.filter(
            Day.driver_id == driver.id, 
            Day.date >= start_date, 
            Day.date <= end_date).all()

        # Calculate wages for each driver
        weekly_total_earned = 0
        total_overnight = 0
        total_bonus_wage = 0
        total_wage = 0
        weekly_bonus = 0
        for day in day_entries:
            day.daily_bonus = day.calculate_daily_bonus(driver)
            total_bonus_wage += day.daily_bonus
            weekly_total_earned += day.calculate_total_earned()
            if day.overnight == True:
                total_overnight += 3000
        if weekly_total_earned > driver.weekly_bonus_threshold:
            weekly_bonus = (total_earned - driver.weekly_bonus_threshold) * driver.weekly_bonus_percentage
            total_bonus_wage += weekly_bonus
        total_wage = total_bonus_wage + total_overnight + driver.basic_wage
        extras = total_bonus_wage 

        driver_data[driver.id]={
            'driver': driver,
            'day_entries': day_entries,
            'total_earned': total_earned,
            'total_overnight': total_overnight,
            'total_bonus_wage': total_bonus_wage,
            'total_wage': total_wage,
            'weekly_bonus': weekly_bonus
        }


    # if request.method == "POST":
    #     # generate start and end date, from user submited date
    #     date = request.form.get("search_date")
    #     start_date = f.date_to_db(date)
    #     end_date = start_date + timedelta(days=6)
    #     # query day table based on user inputs of driver and date
    #     driver_id = request.form.get("search_driver_id")
    #     driver = Driver.query.get(driver_id)
    #     day_entries = Day.query.filter(
    #         Day.driver_id == driver_id, 
    #         Day.date >= start_date, 
    #         Day.date <= end_date).all()
    #     # wages calculations
    #     total_earned = 0
    #     total_overnight = 0
    #     total_bonus_wage = 0
    #     total_wage = 0
    #     weekly_bonus = 0
    #     for day in day_entries:
    #         total_bonus_wage += day.calculate_daily_bonus(driver)
    #         total_earned += day.calculate_total_earned()
    #         if day.overnight == True:
    #             total_overnight += 3000
    #     if total_earned > driver.weekly_bonus_threshold:
    #         weekly_bonus = (total_earned - driver.weekly_bonus_threshold) * driver.weekly_bonus_percentage
    #         total_bonus_wage += weekly_bonus
    #     total_wage = total_bonus_wage + total_overnight + driver.basic_wage     
        
    #     return render_template("wages_calculator.html", date=start_date, driver=driver, 
    #                            drivers=drivers, day_entries=day_entries, 
    #                            total_earned=total_earned, total_overnight=total_overnight, 
    #                            total_bonus_wage=total_bonus_wage, total_wage=total_wage, 
    #                            weekly_bonus=weekly_bonus)
    return render_template("wages_calculator_new.html", driver_data=driver_data, drivers=drivers)
