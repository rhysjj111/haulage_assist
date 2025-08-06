from flask import render_template, request, redirect, url_for, flash, session
from haulage_app import db, f
from haulage_app.verification.models import MissingEntryAnomaly
from haulage_app.models import Truck, Fuel, Day
from haulage_app.fuel import fuel_bp
from haulage_app.verification.checks.verification_functions import(
    check_missing_fuel_has_been_rectified,
)
from haulage_app.functions import(
    date_to_db,
)
from sqlalchemy.exc import NoResultFound

@fuel_bp.route("/add_fuel/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_fuel(item_id, tab):
    trucks = list(Truck.query.order_by(Truck.registration).all())
    fuel_entries = list(Fuel.query.order_by(Fuel.date.desc()).all())
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    fuel = {}

    # --- On GET request, check the session for pre-fill data ---
    # We use .pop() to get the value and remove it, ensuring it's only used once.
    if 'last_fuel_card_name' in session:
        fuel['fuel_card_name'] = session.pop('last_fuel_card_name')

    anomaly_id = request.args.get('anomaly_id')
    if anomaly_id:
        anomaly = MissingEntryAnomaly.query.filter(MissingEntryAnomaly.id == anomaly_id).first()
        fuel['date'] = anomaly.date
        print(anomaly.truck_id)
        fuel['truck_id'] = anomaly.truck_id
        
    if request.method == "POST":
        try:
            date_str = request.form.get("date")
            date_obj = date_to_db(date_str)
            truck_id = int(request.form.get("truck_id"))
            day = Day.query.filter(Day.date == date_obj, Day.truck_id == truck_id).first()

            new_entry = Fuel(
                day_id = day.id if day else None,
                date = date_str,
                truck_id = truck_id,
                fuel_card_name = request.form.get("fuel_card_name"),
                fuel_volume = request.form.get("fuel_volume"),      
                fuel_cost = request.form.get("fuel_cost")      
            )
            db.session.add(new_entry)
            db.session.commit()

            check_missing_fuel_has_been_rectified(new_entry.id)
            flash(f"Entry Success: {new_entry.truck.registration} - {f.display_date(new_entry.date)}", "success-msg")

            # --- On Success, store the next form's data in the session ---
            session['last_fuel_card_name'] = new_entry.fuel_card_name

            # Now, redirect. The session data will persist.
            return redirect(url_for('fuel.add_fuel', item_id=item_id, tab=tab))

        except ValueError as e:
            flash(str(e), 'error-msg')
            # On error, we DON'T redirect. We preserve the user's form input.
            fuel = request.form
        except Exception as e:
            flash("An unexpected error occurred. Please notify the administrator. - "+str(e), 'error-msg')
            # Also preserve form input on other unexpected errors.
            fuel = request.form
    
    return render_template("add_fuel.html", trucks=trucks, list=fuel_entries, tab=tab, fuel=fuel, item_id=item_id, type='fuel')

@fuel_bp.route("/delete_fuel/<int:item_id>")
def delete_fuel(item_id):
    entry = Fuel.query.get_or_404(item_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted", "success-msg")
    return redirect(url_for("fuel.add_fuel", item_id=0, tab='history'))

@fuel_bp.route("/edit_fuel/<int:item_id>", methods=["POST"])
def edit_fuel(item_id):
    entry = Fuel.query.get_or_404(item_id)
    try:
        entry.date = request.form.get("date")
        entry.truck_id = request.form.get("truck_id")
        entry.fuel_card_name = request.form.get("fuel_card_name")
        entry.fuel_volume = request.form.get("fuel_volume")
        entry.fuel_cost = request.form.get("fuel_cost")
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("fuel.add_fuel", item_id=item_id, tab='edit'))
    else:
        db.session.commit()
        flash("Success", "success-msg")
        return redirect(url_for("fuel.add_fuel", item_id=0, tab='edit'))
