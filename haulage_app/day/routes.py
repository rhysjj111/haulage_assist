from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Driver, Day, Truck
from haulage_app.day import day_bp


@day_bp.route("/add_day/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_day(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())
    components = {'drivers':drivers, 'trucks':trucks}
    day_entries = list(Day.query.order_by(Day.date).all())
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    day = {}
    if request.method == "POST":
        try:
            new_entry = Day(
                date = request.form.get("date"),
                driver_id = request.form.get("driver_id"),
                truck_id = request.form.get("truck_id"),
                status = request.form.get("status"),
                overnight = request.form.get("overnight"),
                start_mileage = request.form.get("start_mileage"),
                end_mileage = request.form.get("end_mileage"),
                additional_earned = request.form.get("additional_earned"),
                additional_wages = request.form.get("additional_wages")              
            )
            db.session.add(new_entry)
            db.session.commit()
        except ValueError as e:
            flash(str(e), 'error-msg')
            #retrieve previous answers
            day = request.form
        else:
            flash("Success", "success-msg")
            return redirect(url_for("day.add_day", drivers=drivers, day_entries=day_entries, 
                            tab='entry', item_id=0))
    return render_template("add_day.html", components=components, list=day_entries, tab=tab, 
                           day=day, item_id=item_id, type='day')

@day_bp.route("/delete_day/<int:item_id>")
def delete_day(item_id):
    if item_id == 0:
        start_date = f.week_start(f.today())
        end_date = start_date + timedelta(days=6)
        all = db.session.query(Day).filter(Day.date >= start_date, Day.date <= end_date)
        all.delete()
        db.session.commit()
        flash("Week deleted", "success-msg")
    else:
        entry = Day.query.get_or_404(item_id)
        db.session.delete(entry)
        db.session.commit()
        flash("Entry deleted", "success-msg")
    return redirect(url_for("day.add_day", item_id=0, tab='history'))

@day_bp.route("/edit_day/<int:item_id>", methods=["POST"])
def edit_day(item_id):
    entry = Day.query.get_or_404(item_id)
    try:
        entry.date = request.form.get("date")
        entry.driver_id = request.form.get("driver_id")
        entry.overnight = request.form.get("overnight")
        entry.truck_id = request.form.get("truck_id")
        db.session.commit()
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("day.add_day", item_id=item_id, tab='edit'))
    else:
        flash("Success", "success-msg")
        return redirect(url_for("day.add_day", item_id=0, tab='edit'))
