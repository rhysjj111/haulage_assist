from flask import render_template, request, redirect, url_for, flash
from haulage_app import db
from haulage_app.models import Truck
from haulage_app.truck import truck_bp


@truck_bp.route("/add_truck/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_truck(item_id, tab):
    trucks = list(Truck.query.order_by(Truck.registration).all())
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
            return redirect(url_for("truck.add_truck", tab='entry', item_id=0))     
    return render_template("add_truck.html", list=trucks, tab=tab, truck=truck, 
                           item_id=item_id, type='truck')

@truck_bp.route("/delete_truck/<int:item_id>")
def delete_truck(item_id):
    entry = db.get_or_404(Truck, item_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted", "success-msg")
    return redirect(url_for("truck.add_truck", item_id=0, tab='history'))

@truck_bp.route("/edit_truck/<int:item_id>", methods=["POST"])
def edit_truck(item_id):
    entry = Truck.query.get_or_404(item_id)
    try:
        entry.registration=request.form.get("registration")
        entry.make=request.form.get("make")
        entry.model=request.form.get("model")        
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("truck.add_truck", item_id=item_id, tab='history'))
    else: 
        db.session.commit()
        flash("Success", "success-msg")
        return redirect(url_for("truck.add_truck", item_id=0, tab='history'))
