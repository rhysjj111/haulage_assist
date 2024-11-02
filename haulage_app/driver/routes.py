from flask import render_template, request, redirect, url_for, flash
from haulage_app import db
from haulage_app.models import Driver, Truck
from haulage_app.driver import driver_bp


@driver_bp.route("/add_driver/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_driver(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())
    #empty driver dictionary incase there are any errors in submitted data
    driver = {}
    if request.method == "POST":
        try:
            new_entry = Driver(
                first_name=request.form.get("first_name"),
                last_name=request.form.get("last_name"),
                basic_wage=request.form.get("basic_wage"),
                daily_bonus_threshold=request.form.get("daily_bonus_threshold"),
                daily_bonus_percentage=request.form.get("daily_bonus_percentage"),
                weekly_bonus_threshold=request.form.get("weekly_bonus_threshold"),
                weekly_bonus_percentage=request.form.get("weekly_bonus_percentage"),
                overnight_value=request.form.get("overnight_value"),
                truck_id=request.form.get("truck_id")
                )    
            db.session.add(new_entry)
            db.session.commit()
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error-msg')
            #retrieve previous answers
            driver = request.form
        else:
            flash(f"Entry Success: {new_entry.full_name}", "success-msg")
            return redirect(url_for("driver.add_driver", trucks=trucks, drivers=drivers, 
                            tab='entry', item_id=0))     
    return render_template("add_driver.html", trucks=trucks, list=drivers, tab=tab, driver=driver, 
                           item_id=item_id, type='driver')

@driver_bp.route("/delete_driver/<int:item_id>")
def delete_driver(item_id):
    # entry = db.get_or_404(Driver, item_id)
    # db.session.delete(entry)
    # db.session.commit()
    flash("Unable to delete driver, please contact administrator", "error-msg")
    return redirect(url_for("driver.add_driver", item_id=0, tab='history'))

@driver_bp.route("/edit_driver/<int:item_id>", methods=["POST"])
def edit_driver(item_id):
    entry = Driver.query.get_or_404(item_id)
    try:
        entry.first_name=request.form.get("first_name")
        entry.last_name=request.form.get("last_name")
        entry.basic_wage=request.form.get("basic_wage")
        entry.daily_bonus_threshold=request.form.get("daily_bonus_threshold")
        entry.daily_bonus_percentage=request.form.get("daily_bonus_percentage")
        entry.weekly_bonus_threshold=request.form.get("weekly_bonus_threshold")
        entry.weekly_bonus_percentage=request.form.get("weekly_bonus_percentage")
        entry.overnight_value=request.form.get("overnight_value")
        entry.truck_id=request.form.get("truck_id")
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("driver.add_driver", item_id=item_id, tab='history'))
    else: 
        db.session.commit()
        flash("Success", "success-msg")
        return redirect(url_for("driver.add_driver", item_id=0, tab='history'))
