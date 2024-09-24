from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Driver, Day, Job, Truck
from haulage_app.job import job_bp


@job_bp.route("/add_job/<int:item_id>/<tab>/<user_confirm>", methods=["GET", "POST"])
def add_job(item_id, tab, user_confirm):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())
    days = list(Day.query.order_by(Day.date).all())
    jobs = list(Job.query.order_by(Job.id.desc()).all())
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    job = {}
    dates = {}
    invalid_dates = {}
    valid_dates = {}
    preferred_truck_id = None
  
    if request.method == "POST":        
        current_date = request.form.get('date_cd')
        next_working_date = request.form.get('date_nwd')
        dates = {'cd':current_date, 'nwd':next_working_date}
        driver_id = request.form.get('driver_id')

        if next_working_date and (current_date >= next_working_date):
            flash('"Next working date" must be in the future', "error-msg")
            job = request.form
        else:
            current_driver = Driver.query.filter(Driver.id == driver_id).first()
            if current_driver:
                preferred_truck_id = current_driver.truck_id

            for date in dates:
                try:
                    f.date_to_db(dates[date])
                    Day.query.filter(Day.date == f.date_to_db(dates[date]), Day.driver_id == driver_id).one()
                except:
                    if dates[date] == '' or dates[date] == None:
                        break
                    elif user_confirm == 'yes':
                        try:
                            new_entry = Day(
                                date = dates[date],
                                driver_id = request.form.get("driver_id"),
                                overnight = request.form.get("overnight_" + date),
                                truck_id = request.form.get("truck_id_" + date)            
                            )
                            db.session.add(new_entry)
                            db.session.commit()
                        except ValueError as e:
                            flash(str(e), "error-msg")
                            return redirect(url_for("job.add_job", tab='entry', item_id=0, user_confirm='no'))
                        else:
                            valid_dates[date] = dates[date]
                    else:
                        invalid_dates[date] = dates[date]
                        job = request.form
                        if date == 'cd':
                            continue                
                else:
                    valid_dates[date] = dates[date]

            if invalid_dates == {}:
                for date in valid_dates:
                    try:
                        day = Day.query.filter(Day.date == f.date_to_db(dates[date]), Day.driver_id == driver_id).first()
                        earned = float(request.form.get('earned'))
                        if len(valid_dates) > 1:
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
                        if date == 'cd' and 'nwd' in valid_dates:
                            continue
                        else:
                            flash(f"Entry Success: {new_entry.day.driver.full_name} - {f.display_date(new_entry.day.date)}", "success-msg")
                            return redirect(url_for("job.add_job", tab='entry', item_id=0, user_confirm=False))
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
    return redirect(url_for("job.add_job", item_id=0, tab='history', user_confirm=False))
