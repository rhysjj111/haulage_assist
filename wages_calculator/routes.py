from flask import render_template, request, redirect, url_for
from wages_calculator import app, db
from wages_calculator.models import Driver, DayEnd
from datetime import datetime, timedelta

def currency_to_db(value):
    return float(value)*100

def percentage_to_db(value):
    return float(value)/100


@app.route("/")
def home():
    return render_template("data_entry.html")

################## CRUD driver

@app.route("/add_driver/<tab>", methods=["GET", "POST"])
def add_driver(tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    if request.method == "POST":
        driver = Driver(
            start_date=request.form.get("start_date"),
            first_name=request.form.get("first_name"),
            second_name=request.form.get("second_name"),
            base_wage=currency_to_db(request.form.get("base_wage")),
            bonus_percentage=percentage_to_db(request.form.get("bonus_percentage"))
            )
        db.session.add(driver)
        db.session.commit()
        return redirect(url_for("add_driver", drivers=drivers))
    return render_template("add_driver.html", drivers=drivers, tab=tab)

@app.route("/delete_driver/<int:driver_id>")
def delete_driver(driver_id):
    entry = db.get_or_404(Driver, driver_id)
    db.session.delete(entry)
    db.session.commit()
    return redirect(url_for("add_driver", tab='history'))

@app.route("/edit_driver/<int:driver_id>", methods=["POST"])
def edit_driver(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    driver.start_date = request.form.get("start_date")
    driver.first_name = request.form.get("first_name")
    driver.second_name = request.form.get("second_name")
    driver.base_wage = currency_to_db(request.form.get("base_wage"))
    driver.bonus_percentage = percentage_to_db(request.form.get("bonus_percentage"))
    db.session.commit()
    return redirect(url_for("add_driver", tab='history'))

################## CRUD day_end

@app.route("/add_day_end/<tab>", methods=["GET", "POST"])
def add_day_end(tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    day_end_entries = list(DayEnd.query.order_by(DayEnd.date).all())
    if request.method == "POST":
        day_end_entry = DayEnd(
            date = request.form.get("date"),
            earned = currency_to_db(request.form.get("earned")),
            overnight = bool(True if request.form.get("overnight") else False),
            driver_id = request.form.get("driver_id")
        )
        db.session.add(day_end_entry)
        db.session.commit()
        return redirect(url_for("add_day_end", drivers=drivers, day_end_entries=day_end_entries))
    return render_template("add_day_end.html", drivers=drivers, day_end_entries=day_end_entries, tab=tab)

@app.route("/delete_day_end/<int:day_id>")
def delete_day_end(day_id):
    entry = DayEnd.query.get_or_404(day_id)
    db.session.delete(entry)
    db.session.commit()
    return redirect(url_for("add_day_end", tab='history'))

@app.route("/edit_day_end/<int:day_id>", methods=["POST"])
def edit_day_end(day_id):
    entry = DayEnd.query.get_or_404(day_id)
    entry.date = request.form.get("date")
    entry.earned = currency_to_db(request.form.get("earned"))
    entry.overnight = bool(True if request.form.get("overnight") else False)
    entry.driver_id = request.form.get("driver_id")
    db.session.commit()
    return redirect(url_for("add_day_end", tab='history'))

################## Wages calculator

@app.route("/wages_calculator", methods=["GET", "POST"])
def wages_calculator():
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    if request.method == "POST":
        # generate start and end date, from user submited date
        start_date = datetime.strptime(request.form.get("search_date"), '%d %B, %Y')
        end_date = start_date + timedelta(days=6)
        # query day_end table based on user inputs of driver and date
        driver_id = request.form.get("search_driver_id")
        driver = Driver.query.get(driver_id)
        day_end_entries = DayEnd.query.filter(
            DayEnd.driver_id == driver_id, DayEnd.date >= start_date, DayEnd.date <= end_date).all()
        # wages calculations
        total_earned = 0
        total_overnight = 0
        bonus_wage = 0
        total_wages = 0
        for day in day_end_entries:
            bonus_wage += day.earned * day.driver.bonus_percentage
            total_earned += int(day.earned)
            if day.overnight == True:
                total_overnight += 3000
        base_wage = driver.base_wage
        total_wages = bonus_wage + total_overnight + base_wage     
        
        return render_template("wages_calculator.html", drivers=drivers, day_end_entries=day_end_entries, total_earned=total_earned, total_overnight=total_overnight, base_wage=base_wage, bonus_wage=bonus_wage, total_wages=total_wages)
    return render_template("wages_calculator.html", drivers=drivers)


@app.context_processor
def context_processor():

    def format_currency(amount, currency="£"):
        return f"{currency}{amount:.2f}"

    def format_percentage(percentage):
        return f"{percentage:.0f}%"

    def currency_to_web(amount):
        return float(amount/100)

    def percentage_to_web(percentage):
        return float((percentage*100))

    return dict(format_currency=format_currency, format_percentage=format_percentage,
     currency_to_web=currency_to_web, percentage_to_web=percentage_to_web)




