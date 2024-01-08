from flask import render_template, request, redirect, url_for, flash
from wages_calculator import app, db
import wages_calculator.functions as f
from wages_calculator.models import Driver, DayEnd
from datetime import datetime, timedelta


################### Routes 

@app.route("/")
def home():
    return render_template("data_entry.html")

################## CRUD driver

@app.route("/add_driver/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_driver(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    #empty driver dictionary incase there are any errors in submitted data
    driver = {}
    if request.method == "POST":
        try:
            new_driver = Driver(
                start_date=request.form.get("start_date"),
                first_name=request.form.get("first_name"),
                second_name=request.form.get("second_name"),
                base_wage=request.form.get("base_wage"),
                bonus_percentage=request.form.get("bonus_percentage"),
                )    
            db.session.add(new_driver)
            db.session.commit()
        except ValueError as e:
            flash(str(e), 'error-msg')
            #retrieve previous answers
            driver = request.form

        else:

            flash("Success", "success-msg")
            return redirect(url_for("add_driver", tab='entry', item_id=0))     
    return render_template("add_driver.html", list=drivers, tab=tab, driver=driver, item_id=item_id, type='driver')

@app.route("/delete_driver/<int:item_id>")
def delete_driver(item_id):
    if item_id == 0:
        all = db.session.query(Driver)
        all.delete()
        db.session.commit()
        flash("All entries deleted", "success-msg")
    else:
        entry = db.get_or_404(Driver, item_id)
        db.session.delete(entry)
        db.session.commit()
        flash("Entry deleted", "success-msg")
    return redirect(url_for("add_driver", item_id=0, tab='history'))

@app.route("/edit_driver/<int:item_id>", methods=["POST"])
def edit_driver(item_id):
    driver = Driver.query.get_or_404(item_id)
    try:
        #checks if driver full_name has not been edited by the user to avoid validation which checks if full_name is already in database
        if driver.full_name != (f.name_to_db(request.form.get("first_name")) + " " + f.name_to_db(request.form.get("second_name"))):
            driver.full_name = (f.name_to_db(request.form.get("first_name")) + " " + f.name_to_db(request.form.get("second_name")))
        driver.start_date = request.form.get("start_date")
        driver.first_name = request.form.get("first_name")
        driver.second_name = request.form.get("second_name")
        driver.base_wage = request.form.get("base_wage")
        driver.bonus_percentage = request.form.get("bonus_percentage")
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("add_driver", item_id=item_id, tab='history'))
    else: 
        db.session.commit()
        flash("Success", "success-msg")
        return redirect(url_for("add_driver", item_id=0, tab='history'))


################## CRUD day_end

@app.route("/add_day_end/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_day_end(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    day_end_entries = list(DayEnd.query.order_by(DayEnd.date).all())
    day = {}
    if request.method == "POST":
        try:
            day_end_entry = DayEnd(
                date = request.form.get("date"),
                earned = request.form.get("earned"),
                overnight = request.form.get("overnight"),
                driver_id = request.form.get("driver_id")
            )
            db.session.add(day_end_entry)
            db.session.commit()
        except ValueError as e:
            flash(str(e), 'error-msg')
            #retrieve previous answers
            day = request.form
        else:
            flash("Success", "success-msg")
            return redirect(url_for("add_day_end", drivers=drivers, day_end_entries=day_end_entries, tab='entry', item_id=0))
    return render_template("add_day_end.html", drivers=drivers, list=day_end_entries, tab=tab, day=day, item_id=item_id, type='day_end')

@app.route("/delete_day_end/<int:item_id>")
def delete_day_end(item_id):
    entry = DayEnd.query.get_or_404(item_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted", "success-msg")
    return redirect(url_for("add_day_end", item_id=0, tab='history'))

@app.route("/edit_day_end/<int:item_id>", methods=["POST"])
def edit_day_end(item_id):
    entry = DayEnd.query.get_or_404(item_id)
    try:
        entry.date = request.form.get("date")
        entry.earned = request.form.get("earned")
        entry.overnight = request.form.get("overnight")
        entry.driver_id = request.form.get("driver_id")
        db.session.commit()
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("add_day_end", item_id=item_id, tab='edit'))
    else:
        flash("Success", "success-msg")
        return redirect(url_for("add_day_end", item_id=0, tab='edit'))

################## Wages calculator

@app.route("/wages_calculator", methods=["GET", "POST"])
def wages_calculator():
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    if request.method == "POST":
        # generate start and end date, from user submited date
        date = request.form.get("search_date")
        start_date = f.date_to_db(date)
        end_date = start_date + timedelta(days=6)
        # query day_end table based on user inputs of driver and date
        driver_id = request.form.get("search_driver_id")
        driver = Driver.query.get(driver_id)
        day_end_entries = DayEnd.query.filter(
            DayEnd.driver_id == driver_id, 
            DayEnd.date >= start_date, 
            DayEnd.date <= end_date).all()
        # wages calculations
        total_earned = 0
        total_overnight = 0
        total_bonus_wage = 0
        total_wages = 0
        for day in day_end_entries:
            total_bonus_wage += day.earned * day.driver.bonus_percentage
            total_earned += int(day.earned)
            if day.overnight == True:
                total_overnight += 3000
        total_wages = total_bonus_wage + total_overnight + driver.base_wage     
        
        return render_template("wages_calculator.html", date=start_date, sel_driver=driver, drivers=drivers, day_end_entries=day_end_entries, total_earned=total_earned, total_overnight=total_overnight, total_bonus_wage=total_bonus_wage, total_wages=total_wages)
    return render_template("wages_calculator.html", drivers=drivers)

#makes functions available globally
@app.context_processor
def context_processor():
    return dict(f=f)




