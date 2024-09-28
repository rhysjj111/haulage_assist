from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Driver, Day, Job, Truck
from haulage_app.job import job_bp

def handle_job_dates(dates, driver_id):
    """Handles validation and creation of Day entries for job dates.

    Args:
        dates (dict): A dictionary containing date strings, keyed by type (e.g., 'cd' for current date).
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
    drivers = Driver.query.order_by(Driver.last_name).all()
    trucks = Truck.query.order_by(Truck.registration).all()
    days = Day.query.order_by(Day.date.desc()).all()
    jobs = Job.query.order_by(Job.id.desc()).all()
    job = {}
    dates = {}
    invalid_dates = {}
    valid_dates = {}
    preferred_truck_id = None

    if request.method == "POST":
        driver_id = int(request.form["driver_id"])
        current_driver = Driver.query.get_or_404(driver_id)
        preferred_truck_id = current_driver.truck_id

        dates["cd"] = request.form.get("current_date")
        dates["nwd"] = request.form.get("next_working_date")

        valid_dates, invalid_dates = handle_job_dates(dates, driver_id)

        if not invalid_dates:
            for date_type in valid_dates:
                db_date = f.date_to_db(valid_dates[date_type])
                day = Day.query.filter(Day.date == db_date, Day.driver_id == driver_id).first()

                earned = float(request.form["earned"])
                if len(valid_dates) == 2:
                    earned /= 2

                new_entry = Job(
                    earned=earned,
                    collection=request.form["collection"],
                    delivery=request.form["delivery"],
                    notes=request.form["notes"],
                    split=bool(request.form.get("split")),
                    day_id=day.id,
                )
                db.session.add(new_entry)
                db.session.commit()

            flash("Job entry added successfully!", "success-msg")
            return redirect(url_for("job.add_job", item_id=0, tab="entry"))
        else:
            job = request.form  # Repopulate the form with submitted data

    return render_template(
        "add_job.html",
        drivers=drivers,
        trucks=trucks,
        days=days,
        jobs=jobs,
        tab=tab,
        job=job,
        item_id=item_id,
        invalid_dates=invalid_dates,
        valid_dates=valid_dates,
        preferred_truck_id=preferred_truck_id,
    )

@job_bp.route("/add_job/<int:item_id>/<tab>/confirm", methods=["POST"])
def confirm_add_job(item_id, tab):
    # ... (Your confirmation logic here)
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
    # ... (Your job creation logic, similar to the non-confirmation part of add_job)

    flash("Job entry added successfully!", "success-msg")
    return redirect(url_for("job.add_job", item_id=0, tab="entry"))

@job_bp.route("/delete_job/<int:item_id>")
def delete_job(item_id):
    job = Job.query.get_or_404(item_id)
    db.session.delete(job)
    db.session.commit()
    flash("Job entry deleted successfully!", "success-msg")
    return redirect(url_for("job.add_job", item_id=0, tab="history"))
