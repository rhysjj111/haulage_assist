from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Driver, Day, Job, Truck
from haulage_app.job import job_bp
from datetime import datetime, timedelta
from sqlalchemy.exc import NoResultFound


@job_bp.route("/add_job/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_job(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())
    days = list(Day.query.order_by(Day.date).all())
    jobs = list(Job.query.join(Day).join(Driver).order_by(
        Job.id.desc(),
        Day.date.desc(),
        Driver.first_name,
        Driver.last_name).limit(50).all()
    )
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    components = {'drivers': drivers, 'days': days, 'jobs': jobs}
    job = {}
    dates = {}
    day_not_present = {}
    day_present = {}
    preferred_truck_id = None
  
    if request.method == "POST":        
        current_date_str = request.form.get('date_cd')
        # next_working_date = request.form.get('date_nwd')
        # dates = {'cd':current_date, 'nwd':next_working_date}
        driver_id = request.form.get('driver_id')
        split_job = request.form.get('split') == 'on'
        add_day = request.form.get('add_day')

        current_driver = Driver.query.filter(Driver.id == driver_id).first()
        if current_driver:
            preferred_truck_id = current_driver.truck_id
        try:
            current_date = f.date_to_db(current_date_str)
            if split_job:
                next_working_date_str = f.display_date(current_date + timedelta(days=1))
                dates = {'cd':current_date_str, 'nwd':next_working_date_str}
            else:
                dates = {'cd':current_date_str}
        except ValueError as e:
            flash(f"Invalid date format: {e}", "error-msg")
            job = request.form


        for date in dates:
            # Create new day entry, or add date to valid date dictionary
            try:
                Day.query.filter(Day.date == f.date_to_db(dates[date]), Day.driver_id == driver_id).one()
            except:
                if dates[date] == '' or dates[date] == None:
                    break
                elif add_day == 'True':
                    try:
                        new_entry = Day(
                            date = dates[date],
                            driver_id = request.form.get("driver_id"),
                            status = "working",
                            truck_id = request.form.get("truck_id_" + date),          
                            overnight = request.form.get("overnight_" + date)
                        )
                        db.session.add(new_entry)
                        db.session.commit()
                    except ValueError as e:
                        flash(str(e), "error-msg")
                        job = request.form
                    else:
                        day_present[date] = dates[date]
                else:
                    day_not_present[date] = dates[date]
                    #retrieve previous answers
                    job = request.form
                    if date == 'cd':
                        continue                
            else:
                day_present[date] = dates[date]

        if day_not_present == {}:
            # If no invalid dates, create job entries
            for date in day_present:
                try:
                    day = Day.query.filter(Day.date == f.date_to_db(dates[date]), Day.driver_id == driver_id).first()
                    earned = float(request.form.get('earned'))
                    if len(day_present) > 1:
                        earned /= 2
                        round(earned, 2)
                    new_entry = Job(
                        day_id = day.id,
                        earned = earned,
                        collection = request.form.get('collection'),
                        delivery = request.form.get('delivery'),
                        notes = request.form.get('notes'),
                        split = request.form.get('split')
                    )
                    db.session.add(new_entry)
                    db.session.commit()
                except ValueError as e:
                    flash(str(e), 'error-msg')
                    #retrieve previous answers
                    job = request.form
                else:
                    if date == 'cd' and 'nwd' in day_present:
                        continue
                    else:
                        flash(f"Entry Success: {new_entry.day.driver.full_name} - {f.display_date(new_entry.day.date)}", "success-msg")
                        job['driver_id'] = str(new_entry.day.driver_id)
                        job['date_cd'] = new_entry.day.date
                            
    return render_template(
        "add_job.html",
        drivers=drivers,
        trucks=trucks,
        list=jobs,
        components=components,
        tab=tab,
        job=job,
        item_id=item_id,
        type='job',
        day_not_present=day_not_present,
        day_present=day_present,
        preferred_truck=preferred_truck_id)

@job_bp.route("/edit_job/<int:item_id>", methods=["POST"])
def edit_job(item_id):
    entry = Job.query.get_or_404(item_id)
    try:
        date = request.form.get("date_cd")
        driver_id = request.form.get("driver_id")
        day = Day.query.filter(Day.date == f.date_to_db(date), Day.driver_id == driver_id).one()

        entry.day_id = day.id
        entry.earned = request.form.get("earned")
        entry.collection = request.form.get("collection")
        entry.delivery = request.form.get("delivery")
        entry.notes = request.form.get("notes")
        entry.split = request.form.get("split")
        db.session.commit()
    except NoResultFound as e:
        flash(f"Entry not updated: Day entry for the date and driver selected not found. Please create a Day entry.", 'error-msg-modal')
        return redirect(url_for("job.add_job", item_id=item_id, tab='history'))
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("job.add_job", item_id=item_id, tab='history'))
    else:
        flash(f"Entry Updated: {entry.day.driver.full_name} - {f.display_date(entry.day.date)}", "success-msg")
        return redirect(url_for("job.add_job", item_id=0, tab='history'))


@job_bp.route("/delete_job/<int:item_id>", methods=['POST'])
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
    return redirect(url_for("job.add_job", item_id=0, tab='history', user_confirm=False))
