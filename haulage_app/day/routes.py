from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Driver, Day, Truck
from haulage_app.verification.models import IncorrectMileage, Anomaly, MissingEntryAnomaly
from haulage_app.analysis.functions import get_start_and_end_of_week
from haulage_app.day import day_bp
from pprint import pprint
from sqlalchemy.exc import IntegrityError
from haulage_app.verification.checks.verification_functions import check_mileage_has_been_rectified
from datetime import timedelta

@day_bp.route("/add_day/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_day(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())
    components = {'drivers':drivers, 'trucks':trucks}

    anomaly_id = request.args.get('anomaly_id')
    search_term = None
    day = {}

    if anomaly_id:
        anomaly = Anomaly.query.get(anomaly_id)
        if anomaly.type == 'incorrect_mileage':
            anomaly = IncorrectMileage.query.filter(IncorrectMileage.id == anomaly_id).first()
            registration = anomaly.truck.registration
            previous_date = f.display_date(anomaly.previous_date)
            next_date = f.display_date(anomaly.next_date)

            # search_term = f"{registration}, {previous_date} + {registration}, {next_date}"
            search_term = ""
            day_entries = Day.query.filter(
                db.or_(
                    Day.date == anomaly.previous_date,
                    Day.date == anomaly.next_date
                ),
                Day.truck_id == anomaly.truck_id
            ).all()
        else:
            anomaly = MissingEntryAnomaly.query.filter(MissingEntryAnomaly.id == anomaly_id).first()
            day['date'] = anomaly.date
            day['driver_id'] = anomaly.driver_id
            start_week_date, end_week_date = get_start_and_end_of_week(anomaly.year, anomaly.week_number)
            start_week_date = start_week_date  - timedelta(days=5)
            end_week_date = end_week_date + timedelta(days=5)

            day_entries = Day.query.filter(
                Day.date.between(start_week_date, end_week_date),
                Day.driver_id == anomaly.driver_id
            ).all()
            search_term = ""

    else:
        day_entries = list(
            Day.query.join(Driver)
            .order_by(
                Day.date.desc()
            ).all()
        )
        search_term = ""

    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    template_data = {  # Create a dictionary for template data
        "components": components,
        "list": day_entries,
        "tab": tab,
        "item_id": item_id,
        "type": 'day',
        "search_term": search_term,
        "day": day       # Initially an empty dictionary for form data
    }

    if request.method == "POST":
        try:
            new_entry = Day(
                date = request.form.get("date"),
                driver_id = request.form.get("driver_id"),
                status = request.form.get("status"),
            )
            if request.form.get("status") == "working":
                new_entry.truck_id = request.form.get("truck_id")
                new_entry.overnight = request.form.get("overnight")
                new_entry.fuel = request.form.get("fuel")
                new_entry.start_mileage = request.form.get("start_mileage")
                new_entry.end_mileage = request.form.get("end_mileage")
                new_entry.additional_earned = request.form.get("additional_earned")
                new_entry.additional_wages = request.form.get("additional_wages")
            db.session.add(new_entry)
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            flash("Entry already exists with the same driver and date you dull pr*ck.", 'error-msg')
            template_data["day"].update(request.form)
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error-msg')
            #retrieve previous answers
            template_data["day"].update(request.form)
        else:
            flash(f"Entry Success: {new_entry.driver.full_name} - {f.display_date(new_entry.date)}", "success-msg")
            return redirect(url_for("day.add_day", item_id=0, tab='entry'))
    return render_template("add_day.html", **template_data)

@day_bp.route("/delete_day/<int:item_id>")
def delete_day(item_id):
    if item_id == 0:
        all = db.session.query(Day)
        all.delete()
        db.session.commit()
        flash("All entries deleted", "success-msg")
    else:
        entry = Day.query.get_or_404(item_id)
        try:
            db.session.delete(entry)
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            flash('Entry cannot be deleted as it is associated with Job entries.', "error-msg")

        else:
            flash("Entry deleted", "success-msg")
    return redirect(url_for("day.add_day", item_id=0, tab='history'))

@day_bp.route("/edit_day/<int:item_id>", methods=["POST"])
def edit_day(item_id):

    entry = Day.query.get_or_404(item_id)
    referrer = request.referrer
    is_week_page = '/week/' in referrer

    try:
        entry.date = request.form.get("date")
        entry.driver_id = request.form.get("driver_id")
        entry.overnight = request.form.get("overnight")
        entry.status = request.form.get("status")

        if request.form.get("status") == "working":
            entry.fuel = request.form.get("fuel")
            entry.start_mileage = request.form.get("start_mileage")
            entry.end_mileage = request.form.get("end_mileage")
            entry.additional_earned = request.form.get("additional_earned")
            entry.additional_wages = request.form.get("additional_wages")
            entry.truck_id = request.form.get("truck_id")
        else:
            entry.truck_id = None
            entry.overnight = None
            entry.fuel = None
            entry.start_mileage = None
            entry.end_mileage = None
            entry.additional_earned = None
            entry.additional_wages = None
        db.session.commit()
        
    except ValueError as e:
        if request.args.get('weekly'):
            flash(str(e), 'error-msg-modal')
            return redirect(url_for("day.add_day", item_id=item_id, tab='edit', weekly=True))
        elif is_week_page:
            flash(str(e), 'error-msg')
            return redirect(url_for("week.week", item_id=item_id, tab='edit'))
        else:
            flash(str(e), 'error-msg-modal')
            return redirect(url_for("day.add_day", item_id=item_id, tab='edit'))
    else:
        if request.args.get('weekly'):
            flash(f"Entry Updated: {entry.driver.full_name} - {f.display_date(entry.date)}", "success-msg-modal")
            return redirect(url_for("day.add_day", item_id=0, tab='edit', weekly=True))
        elif is_week_page:
                flash(f"Entry Updated: {entry.driver.full_name} - {f.display_date(entry.date)}", "success-msg")
                return redirect(url_for("week.week", item_id=item_id, tab='edit', success=True))
        else:
            check_mileage_has_been_rectified(item_id)
            flash(f"Entry Updated: {entry.driver.full_name} - {f.display_date(entry.date)}", "success-msg")
            return redirect(url_for("day.add_day", item_id=0, tab='edit'))

