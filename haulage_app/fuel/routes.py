from flask import render_template, request, redirect, url_for, flash
from haulage_app import db
from haulage_app.models import Truck, Fuel
from haulage_app.fuel import fuel_bp


@fuel_bp.route("/add_fuel/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_fuel(item_id, tab):
    trucks = list(Truck.query.order_by(Truck.registration).all())
    fuel_entries = list(Fuel.query.order_by(Fuel.date).all())
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    fuel = {}
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
            flash("Success", "success-msg")
            return redirect(url_for("fuel.add_fuel", trucks=trucks, fuel_entries=fuel_entries, 
                            tab='entry', item_id=0))
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