from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Driver, Day, Job, Truck
from haulage_app.job import job_bp
from datetime import datetime, timedelta

def handle_job_dates(dates, driver_id):
    """Handles validation and creation of Day entries for job dates.

    Args:
        dates (dict): A dictionary containing date strings, keyed by type (e.g., 'cd' for current date, 'nwd' for next working date).
        driver_id (int): The ID of the driver associated with the job.

    Returns:
        tuple: A tuple containing two dictionaries:
            - valid_dates (dict): Dates that are valid or have corresponding Day entries.
            - invalid_dates (dict): Dates that are invalid and require confirmation for Day entry creation.
    """
    invalid_dates = {}
    valid_dates = {}

    for date_type, date_str in dates.items():
        if not date_str:  # Skip if date is empty
            continue

        try:
            db_date = f.date_to_db(date_str)
        except ValueError as e:
            flash(f"Invalid date format: {e}", "error-msg")
            invalid_dates[date_type] = date_str
            continue

        if db_date < datetime.date.today():
            flash(f"{date_type.upper()}: Date cannot be in the past.", "error-msg")
            invalid_dates[date_type] = date_str
            continue

        day = Day.query.filter(Day.date == db_date, Day.driver_id == driver_id).first()
        if day:
            valid_dates[date_type] = date_str
        else:
            invalid_dates[date_type] = date_str

    return valid_dates, invalid_dates

@job_bp.route("/add_job/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_job(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())
    days = list(Day.query.order_by(Day.date).all())
    jobs = list(Job.query.order_by(Job.id.desc()).all())
    job = {}
    dates = {}
    invalid_dates = {}
    valid_dates = {}
    preferred_truck_id = None

    if request.method == "POST":
        current_date_str = request.form.get('date_cd')  # Get current_date from form

        try:
            current_date = datetime.strptime(current_date_str, '%Y-%m-%d')
            next_working_date = current_date + timedelta(days=1)
            next_working_date_str = next_working_date.strftime('%Y-%m-%d')
            dates = {'cd': current_date_str, 'nwd': next_working_date_str}
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", "error-msg")
            return redirect(url_for("job.add_job", tab='entry', item_id=0))

        driver_id = request.form.get('driver_id')

        current_driver = Driver.query.filter(Driver.id == driver_id).first()
        if current_driver:
            preferred_truck_id = current_driver.truck_id

        valid_dates, invalid_dates = handle_job_dates(dates, driver_id)

        if not invalid_dates:
            # If no invalid dates, create job entries
            for date_type in valid_dates:
                db_date = f.date_to_db(valid_dates[date_type])
                day = Day.query.filter(Day.date == db_date, Day.driver_id == driver_id).first()

                earned = float(request.form.get('earned'))
                if len(valid_dates) > 1:
                    earned /= 2
                    round(earned, 2)

                new_entry = Job(
                    day_id=day.id,
                    earned=earned,
                    collection=request.form.get('collection'),
                    delivery=request.form.get('delivery'),
                    notes=request.form.get('notes'),
                    split=request.form.get('split')
                )
                db.session.add(new_entry)
                db.session.commit()

            flash(f"Entry Success: {new_entry.day.driver.full_name} - {f.display_date(new_entry.day.date)}", "success-msg")
            return redirect(url_for("job.add_job", tab='entry', item_id=0))
        else:
            job = request.form  # Repopulate the form with submitted data

    return render_template(
        "add_job.html",
        drivers=drivers,
        trucks=trucks,
        list=jobs,
        tab=tab,
        job=job,
        item_id=item_id,
        type='job',
        invalid_dates=invalid_dates,
        valid_dates=valid_dates,
        preferred_truck=preferred_truck_id)


@job_bp.route("/add_job/<int:item_id>/<tab>/confirm", methods=["POST"])
def confirm_add_job(item_id, tab):
    driver_id = int(request.form["driver_id"])
    for date_type in request.form:
        if date_type.startswith("date_"):
            date_str = request.form[date_type]
            try:
                db_date = f.date_to_db(date_str)
            except ValueError as e:
                flash(f"Invalid date format: {e}", "error-msg")
                return redirect(url_for("job.add_job", item_id=item_id, tab=tab))

            overnight = bool(request.form.get(f"overnight_{date_type[5:]}"))
            truck_id = int(request.form.get(f"truck_id_{date_type[5:]}"))

            new_day_entry = Day(
                date=db_date,
                driver_id=driver_id,
                overnight=overnight,
                truck_id=truck_id,
            )
            db.session.add(new_day_entry)

    db.session.commit()

    # Now that Day entries are created, proceed with job creation
    current_date_str = request.form.get('date_cd')  # Get current_date from form

    try:
        current_date = datetime.strptime(current_date_str, '%Y-%m-%d')
        next_working_date = current_date + timedelta(days=1)
        next_working_date_str = next_working_date.strftime('%Y-%m-%d')
        dates = {'cd': current_date_str, 'nwd': next_working_date_str}
    except ValueError:
        flash("Invalid date format. Please use YYYY-MM-DD.", "error-msg")
        return redirect(url_for("job.add_job", tab='entry', item_id=0))

    driver_id = request.form.get('driver_id')

    valid_dates, invalid_dates = handle_job_dates(dates, driver_id)

    for date_type in valid_dates:
        db_date = f.date_to_db(valid_dates[date_type])
        day = Day.query.filter(Day.date == db_date, Day.driver_id == driver_id).first()

        earned = float(request.form.get('earned'))
        if len(valid_dates) > 1:
            earned /= 2
            round(earned, 2)

        new_entry = Job(
            day_id=day.id,
            earned=earned,
            collection=request.form.get('collection'),
            delivery=request.form.get('delivery'),
            notes=request.form.get('notes'),
            split=request.form.get('split')
        )
        db.session.add(new_entry)
        db.session.commit()

    flash(f"Entry Success: {new_entry.day.driver.full_name} - {f.display_date(new_entry.day.date)}", "success-msg")
    return redirect(url_for("job.add_job", tab='entry', item_id=0))


@job_bp.route("/delete_job/<int:item_id>")
def delete_job(item_id):
    if item_id == 0:
        all = db.session.query(Job)
        all.delete()
        db.session.commit()
        flash("All entries deleted", "success-msg")
    else:
        entry = Job.query.get_or_404(item_id)
        db.session.delete(entry)
        db.session.commit()
        flash("Entry deleted", "success-msg")
    return redirect(url_for("job.add_job", item_id=0, tab='history'))
