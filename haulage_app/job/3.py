from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Driver, Day, Job, Truck
from haulage_app.job import job_bp
from datetime import timedelta

def handle_job_dates(dates, driver_id, create_day_entries=False):
    """Handles validation and creation of Day entries for job dates.

    Args:
        dates (dict): A dictionary containing date strings, keyed by type 
                      (e.g., 'cd' for current date, 'nwd' for next working date).
        driver_id (int): The ID of the driver associated with the job.
        create_day_entries (bool): If True, create missing Day entries. 
                                   If False, only validate and return invalid dates.

    Returns:
        tuple: A tuple containing two dictionaries:
            - valid_dates (dict): Dates that are valid or have corresponding Day entries.
            - invalid_dates (dict): Dates that are invalid and require confirmation 
                                    for Day entry creation.
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

        if db_date < f.date_to_db(datetime.now().strftime('%Y-%m-%d')):
            flash(f"{date_type.upper()}: Date cannot be in the past.", "error-msg")
            invalid_dates[date_type] = date_str
            continue

        day = Day.query.filter(Day.date == db_date, Day.driver_id == driver_id).first()
        if day:
            valid_dates[date_type] = date_str
        else:
            if create_day_entries:
                # Create the Day entry here
                try:
                    new_entry = Day(
                        date=db_date,
                        driver_id=driver_id,
                        overnight=request.form.get(f"overnight_{date_type[5:]}"),
                        truck_id=request.form.get(f"truck_id_{date_type[5:]}")
                    )
                    db.session.add(new_entry)
                    db.session.commit()
                    valid_dates[date_type] = date_str
                except Exception as e:  # Consider catching specific exceptions
                    flash(f"Error creating Day entry: {e}", "error-msg")
                    invalid_dates[date_type] = date_str
            else:
                invalid_dates[date_type] = date_str

    return valid_dates, invalid_dates


@job_bp.route("/add_job/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_job(item_id, tab):
    # ... (Your existing code for fetching drivers, trucks, etc.)

    if request.method == "POST":
        driver_id = request.form.get('driver_id')
        current_date = request.form.get('date_cd')
        split_job = request.form.get('split') == 'True'  # Check if split is True

        dates = {'cd': current_date}
        if split_job:
            next_working_date = (f.date_to_db(current_date) + timedelta(days=1)).strftime('%Y-%m-%d')
            dates['nwd'] = next_working_date

        # Only validate dates initially
        valid_dates, invalid_dates = handle_job_dates(dates, driver_id)

        if invalid_dates:
            # If there are invalid dates, re-render the form with errors
            job = request.form
            return render_template(
                # ... your existing template rendering code ...
                invalid_dates=invalid_dates,
                # ... other variables ...
            )
        else:
            # If all dates are valid, create Day entries if needed and then create Job entries
            valid_dates, _ = handle_job_dates(dates, driver_id, create_day_entries=True)

            for date_type in valid_dates:
                # ... (Your existing code for creating Job entries)

                flash("Job entry added successfully!", "success-msg")
            return redirect(url_for("job.add_job", tab='entry', item_id=0))

    # ... (Your existing code for rendering the initial form)


# @job_bp.route("/delete_job/<int:item_id>")
# def delete_job(item_id):
    # ... (Your existing code for deleting job entries)
