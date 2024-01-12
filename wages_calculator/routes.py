from flask import render_template, request, redirect, url_for, flash
from wages_calculator import app, db
import wages_calculator.functions as f
from wages_calculator.models import Driver, DayEnd
from datetime import datetime, timedelta


################### Routes 

@app.route("/")
def home():
    return render_template("entry_menu.html")


######################################################### DRIVER ROUTES

@app.route("/add_driver/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_driver(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    #empty driver dictionary incase there are any errors in submitted data
    driver = {}
    if request.method == "POST":
        try:
            new_entry = Driver(
                first_name=request.form.get("first_name"),
                last_name=request.form.get("last_name"),
                basic_wage=request.form.get("basic_wage"),
                daily_bonus_threshold = request.form.get("daily_bonus_threshold"),
                daily_bonus_percentage = request.form.get("daily_bonus_percentage"),
                weekly_bonus_threshold = request.form.get("weekly_bonus_threshold"),
                weekly_bonus_percentage = request.form.get("weekly_bonus_percentage"),
                overnight_value = request.form.get("overnight_value")
                )    
            db.session.add(new_entry)
            db.session.commit()
        except ValueError as e:
            flash(str(e), 'error-msg')
            #retrieve previous answers
            driver = request.form
        else:
            flash("Success", "success-msg")
            return redirect(url_for("add_driver", tab='entry', item_id=0))     
    return render_template("add_driver.html", list=drivers, tab=tab, driver=driver, 
                           item_id=item_id, type='driver')

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
    entry = Driver.query.get_or_404(item_id)
    try:
        #checks if driver full_name has not been edited by the user to avoid validation which checks if full_name is already in database
        if entry.full_name != (f.name_to_db(request.form.get("first_name")) + " " 
                                + f.name_to_db(request.form.get("last_name"))):
            entry.full_name = (f.name_to_db(request.form.get("first_name")) + " " 
                                + f.name_to_db(request.form.get("last_name")))
        entry.start_date = request.form.get("start_date")
        entry.first_name = request.form.get("first_name")
        entry.last_name = request.form.get("last_name")
        entry.basic_wage = request.form.get("basic_wage")
        entry.daily_bonus_threshold = request.form.get("daily_bonus_threshold")
        entry.daily_bonus_percentage = request.form.get("daily_bonus_percentage")
        entry.weekly_bonus_threshold = request.form.get("weekly_bonus_threshold")
        entry.weekly_bonus_percentage = request.form.get("weekly_bonus_percentage")
        entry.overnight_value = request.form.get("overnight_value")
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("add_driver", item_id=item_id, tab='history'))
    else: 
        db.session.commit()
        flash("Success", "success-msg")
        return redirect(url_for("add_driver", item_id=0, tab='history'))


############################################################# TRUCK ROUTES

@app.route("/add_truck/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_truck(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    #empty driver dictionary incase there are any errors in submitted data
    truck = {}
    if request.method == "POST":
        try:
            new_entry = Truck(
                registration=request.form.get("registration"),
                make=request.form.get("make"),
                model=request.form.get("model")
                )    
            db.session.add(new_entry)
            db.session.commit()
        except ValueError as e:
            flash(str(e), 'error-msg')
            #retrieve previous answers
            truck = request.form
        else:
            flash("Success", "success-msg")
            return redirect(url_for("add_truck", tab='entry', item_id=0))     
    return render_template("add_truck.html", list=drivers, tab=tab, truck=truck, 
                           item_id=item_id, type='truck')

@app.route("/delete_truck/<int:item_id>")
def delete_truck(item_id):
    entry = db.get_or_404(Truck, item_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted", "success-msg")
return redirect(url_for("add_truck", item_id=0, tab='history'))

@app.route("/edit_truck/<int:item_id>", methods=["POST"])
def edit_truck(item_id):
    entry = Truck.query.get_or_404(item_id)
    try:
        entry.registration=request.form.get("registration")
        entry.make=request.form.get("make")
        entry.model=request.form.get("model")        
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("add_truck", item_id=item_id, tab='history'))
    else: 
        db.session.commit()
        flash("Success", "success-msg")
        return redirect(url_for("add_truck", item_id=0, tab='history'))


###################################################### DAY ROUTES

@app.route("/add_day/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_day(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())
    components = {'drivers':drivers, 'trucks':trucks}
    day_entries = list(DayEnd.query.order_by(Day.date).all())
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    day = {}
    if request.method == "POST":
        try:
            new_entry = Day(
                date = request.form.get("date"),
                driver_id = request.form.get("driver_id"),
                status = request.form.get("status"),
                additional_earned = request.form.get("additional_earned"),
                additional_wages = request.form.get("additional_wages"),
                overnight = request.form.get("overnight"),
                truck_id = request.form.get("truck_id"),
                start_mileage = request.form.get("start_mileage"),
                end_mileage = request.form.get("end_mileage"),                
            )
            db.session.add(new_entry)
            db.session.commit()
        except ValueError as e:
            flash(str(e), 'error-msg')
            #retrieve previous answers
            day = request.form
        else:
            flash("Success", "success-msg")
            return redirect(url_for("add_day", drivers=drivers, day_end_entries=day_end_entries, 
                            tab='entry', item_id=0))
    return render_template("add_day.html", components=components, list=day_end_entries, tab=tab, 
                           day=day, item_id=item_id, type='day_end')

@app.route("/delete_day/<int:item_id>")
def delete_day_end(item_id):
    if item_id == 0:
        all = db.session.query(Day)
        all.delete()
        db.session.commit()
        flash("All entries deleted", "success-msg")
    else:
        entry = DayEnd.query.get_or_404(item_id)
        db.session.delete(entry)
        db.session.commit()
        flash("Entry deleted", "success-msg")
    return redirect(url_for("add_day", item_id=0, tab='history'))

@app.route("/edit_day/<int:item_id>", methods=["POST"])
def edit_day_end(item_id):
    entry = DayEnd.query.get_or_404(item_id)
    try:
        entry.date = request.form.get("date")
        entry.driver_id = request.form.get("driver_id")
        entry.status = request.form.get("status")
        entry.additional_earned = request.form.get("additional_earned")
        entry.additional_wages = request.form.get("additional_wages")
        entry.overnight = request.form.get("overnight")
        entry.truck_id = request.form.get("truck_id")
        entry.start_mileage = request.form.get("start_mileage")
        entry.end_mileage = request.form.get("end_mileage")
        db.session.commit()
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("add_day", item_id=item_id, tab='edit'))
    else:
        flash("Success", "success-msg")
        return redirect(url_for("add_day", item_id=0, tab='edit'))


#################################################### JOB ROUTES

@app.route("/add_job/<int:item_id>/<tab>/<invalid_dates>", methods=["GET", "POST"])
def add_job(item_id, tab, invalid_dates):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    day_entries = list(DayEnd.query.order_by(Day.date).all())
    job_entries = list(DayEnd.query.oreder_by(Job.date).all())
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    job = {}
    if request.method == "POST":
        current_date = form.get('date')
        next_working_date = form.get('date')
        dates = {'nwd':next_working_date,'cd':current_date}
        driver_id = form.get('driver_id')
        for date in dates:
                if (date is not None) and (Day.query.filter(Day.date == dates[date], Day.driver_id == driver_id).first() is None):
                    dates[date] = 'invalid'
                elif date is None: 
                    del dates[date]
        try:
            'invalid' not in dates
        except:
            flash("Invalid dates selected", "error-msg")
            job = request.form
        else: 
            try:  
                for date in dates:
                    day = Day.query.filter(Day.date == dates[date], Day.driver_id == driver_id).first()
                    earned = form.get('earned')
                    if len(dates)>1:
                        earned /= 2 
                    new_entry = Job(
                        day_id = day.id,
                        earned = earned,
                        collection = form.get('collection'),
                        delivery = form.get('delivery'),
                        notes = form.get('notes'),
                        split = form.get('split')
                    )
                    db.session.add(new_entry)
                db.session.commit()
            except ValueError as e:
                flash(str(e), 'error-msg')
                #retrieve previous answers
                job = request.form
            else:
                flash("Success", "success-msg")
                return redirect(url_for("add_job", drivers=drivers,
                                tab='entry', item_id=0))
    return render_template("add_job.html", trucks=trucks, list=job_entries, tab=tab, 
                           job=job, item_id=item_id, type='job', invalid_dates=invalid_dates)

@app.route("/delete_fuel_entry/<int:item_id>")
def delete_fuel_entry(item_id):
    entry = Fuel.query.get_or_404(item_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted", "success-msg")
return redirect(url_for("add_job", item_id=0, tab='history'))

@app.route("/edit_add_job/<int:item_id>", methods=["POST"])
def edit_add_job(item_id):
    entry = Fuel.query.get_or_404(item_id)
    try:
        entry.date = request.form.get("date")
        entry.truck_id = request.form.get("truck_id")
        entry.fuel_card_name = request.form.get("fuel_card_name")
        entry.fuel_volume = request.form.get("fuel_volume")
        entry.fuel_cost = request.form.get("fuel_cost")
        db.session.commit()
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("add_job", item_id=item_id, tab='edit'))
    else:
        flash("Success", "success-msg")
        return redirect(url_for("add_job", item_id=0, tab='edit'))


#################################################### FUEL ROUTES

@app.route("/add_fuel_entry/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_fuel_entry(item_id, tab):
    trucks = list(Truck.query.order_by(Truck.registration).all())
    fuel_entries = list(Fuel.query.order_by(Fuel.date).all())
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    fuel_entry = {}
    if request.method == "POST":
        try:
            new_entry = Fuel(
                date = request.form.get("date"),
                truck_id = request.form.get("truck_id"),
                fuel_card_name = request.form.get("fuel_card_name"),
                fuel_volume = request.form.get("fuel_volume"),      
                fuel_cost = request.form.get("fuel_cost")      
            )
            db.session.add(new_entry)
            db.session.commit()
        except ValueError as e:
            flash(str(e), 'error-msg')
            #retrieve previous answers
            fuel_entry = request.form
        else:
            flash("Success", "success-msg")
            return redirect(url_for("add_fuel_entry", trucks=trucks, fuel_entries=fuel_entries, 
                            tab='entry', item_id=0))
    return render_template("add_fuel_entry.html", trucks=trucks, list=fuel_entries, tab=tab, 
                           fuel_entry=fuel_entry, item_id=item_id, type='fuel_entry')

@app.route("/delete_fuel_entry/<int:item_id>")
def delete_fuel_entry(item_id):
    entry = Fuel.query.get_or_404(item_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted", "success-msg")
return redirect(url_for("add_fuel_entry", item_id=0, tab='history'))

@app.route("/edit_fuel_entry/<int:item_id>", methods=["POST"])
def edit_fuel_entries(item_id):
    entry = Fuel.query.get_or_404(item_id)
    try:
        entry.date = request.form.get("date")
        entry.truck_id = request.form.get("truck_id")
        entry.fuel_card_name = request.form.get("fuel_card_name")
        entry.fuel_volume = request.form.get("fuel_volume")
        entry.fuel_cost = request.form.get("fuel_cost")
        db.session.commit()
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("add_fuel_entry", item_id=item_id, tab='edit'))
    else:
        flash("Success", "success-msg")
        return redirect(url_for("add_fuel_entry", item_id=0, tab='edit'))


#################################################### PAYSLIP ROUTES

@app.route("/add_payslip/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_payslip(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    payslips = list(Payslip.query.order_by(Payslip.date).all())
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    payslip = {}
    if request.method == "POST":
        try:
            new_entry = Payslip(
                date = request.form.get("date"),
                driver_id = request.form.get("driver_id"),
                total_wage = request.form.get("total_wage"),
                total_cost_to_employer = request.form.get("total_cost_to_employer")    
            )
            db.session.add(new_entry)
            db.session.commit()
        except ValueError as e:
            flash(str(e), 'error-msg')
            #retrieve previous answers
            payslip = request.form
        else:
            flash("Success", "success-msg")
            return redirect(url_for("add_payslip", drivers=drivers, payslips=payslips, 
                            tab='entry', item_id=0))
    return render_template("add_payslip.html", drivers=drivers, list=payslips, tab=tab, 
                           payslip=payslip, item_id=item_id, type='payslip')

@app.route("/delete_payslip/<int:item_id>")
def delete_payslip(item_id):
    entry = Payslip.query.get_or_404(item_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted", "success-msg")
return redirect(url_for("add_payslip", item_id=0, tab='history'))

@app.route("/edit_payslip/<int:item_id>", methods=["POST"])
def edit_payslip(item_id):
    entry = Payslip.query.get_or_404(item_id)
    try:
        entry.date = request.form.get("date")
        entry.driver_id = request.form.get("driver_id")
        entry.total_wage = request.form.get("total_wage")
        entry.total_cost_to_employer = request.form.get("total_cost_to_employer")
        db.session.commit()
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("add_payslip", item_id=item_id, tab='edit'))
    else:
        flash("Success", "success-msg")
        return redirect(url_for("add_payslip", item_id=0, tab='edit'))





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
        total_wages = total_bonus_wage + total_overnight + driver.basic_wage     
        
        return render_template("wages_calculator.html", date=start_date, sel_driver=driver, 
                               drivers=drivers, day_end_entries=day_end_entries, 
                               total_earned=total_earned, total_overnight=total_overnight, 
                               total_bonus_wage=total_bonus_wage, total_wages=total_wages)
    return render_template("wages_calculator.html", drivers=drivers)

#makes functions available globally
@app.context_processor
def context_processor():
    return dict(f=f)




