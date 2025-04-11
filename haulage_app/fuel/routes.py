from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.verification.models import MissingEntryAnomaly
from haulage_app.models import Truck, Fuel
from haulage_app.fuel import fuel_bp
from haulage_app.verification.checks.verification_functions import(
    check_missing_fuel_has_been_rectified,
)


@fuel_bp.route("/add_fuel/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_fuel(item_id, tab):
    trucks = list(Truck.query.order_by(Truck.registration).all())
    fuel_entries = list(Fuel.query.order_by(Fuel.date.desc()).all())
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    fuel = {}

    anomaly_id = request.args.get('anomaly_id')
    search_term = None

    if anomaly_id:
        anomaly = MissingEntryAnomaly.query.filter(MissingEntryAnomaly.id == anomaly_id).first()
        fuel['date'] = anomaly.date
        fuel['truck_id'] = anomaly.truck_id
        

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
            fuel = request.form
        else:
            flash(f"Entry Success: {new_entry.truck.registration} - {f.display_date(new_entry.date)}", "success-msg")
            fuel['fuel_card_name'] = new_entry.fuel_card_name
            check_missing_fuel_has_been_rectified(new_entry.id)
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
