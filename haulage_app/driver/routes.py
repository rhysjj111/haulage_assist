from flask import render_template, request, redirect, url_for, flash
from haulage_app import db
from haulage_app.models import Driver, Truck, DriverEmploymentHistory, EmploymentStatus
from haulage_app.driver import driver_bp
from sqlalchemy.exc import IntegrityError
import datetime


@driver_bp.route("/add_driver/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_driver(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    trucks = list(Truck.query.order_by(Truck.registration).all())
    #empty driver dictionary incase there are any errors in submitted data
    driver = {}
    if request.method == "POST":
        try:
            new_entry = Driver(
                first_name=request.form.get("first_name"),
                last_name=request.form.get("last_name"),
                basic_wage=request.form.get("basic_wage"),
                daily_bonus_threshold=request.form.get("daily_bonus_threshold"),
                daily_bonus_percentage=request.form.get("daily_bonus_percentage"),
                weekly_bonus_threshold=request.form.get("weekly_bonus_threshold"),
                weekly_bonus_percentage=request.form.get("weekly_bonus_percentage"),
                overnight_value=request.form.get("overnight_value"),
                truck_id=request.form.get("truck_id")
                )
            db.session.add(new_entry)
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            flash("Driver already exists in the database, please choose another name or edit/delete current driver to replace.", 'error-msg')
            driver = request.form
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error-msg')
            #retrieve previous answers
            driver = request.form
        else:
            flash(f"Entry Success: {new_entry.full_name}", "success-msg")
            return redirect(url_for("driver.add_driver", trucks=trucks, drivers=drivers, 
                            tab='entry', item_id=0))     
    return render_template("add_driver.html", trucks=trucks, list=drivers, tab=tab, driver=driver, 
                           item_id=item_id, type='driver')

@driver_bp.route("/delete_driver/<int:item_id>", methods=['POST'])
def delete_driver(item_id):
    # entry = db.get_or_404(Driver, item_id)
    # db.session.delete(entry)
    # db.session.commit()
    flash("Unable to delete driver, please contact administrator", "error-msg")
    return redirect(url_for("driver.add_driver", item_id=0, tab='history'))

@driver_bp.route("/edit_driver/<int:item_id>", methods=["POST"])
def edit_driver(item_id):
    entry = Driver.query.get_or_404(item_id)
    try:
        entry.first_name=request.form.get("first_name")
        entry.last_name=request.form.get("last_name")
        entry.basic_wage=request.form.get("basic_wage")
        entry.daily_bonus_threshold=request.form.get("daily_bonus_threshold")
        entry.daily_bonus_percentage=request.form.get("daily_bonus_percentage")
        entry.weekly_bonus_threshold=request.form.get("weekly_bonus_threshold")
        entry.weekly_bonus_percentage=request.form.get("weekly_bonus_percentage")
        entry.overnight_value=request.form.get("overnight_value")
        entry.truck_id=request.form.get("truck_id")
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("driver.add_driver", item_id=item_id, tab='history'))
    else: 
        db.session.commit()
        flash("Success", "success-msg")
        return redirect(url_for("driver.add_driver", item_id=0, tab='history'))

# New Employment History Routes
@driver_bp.route("/<int:driver_id>/employment_history")
def driver_employment_history(driver_id):
    """Display employment history management page for a specific driver"""
    driver = Driver.query.get_or_404(driver_id)
    employment_history = DriverEmploymentHistory.query.filter_by(
        driver_id=driver_id
    ).order_by(DriverEmploymentHistory.start_date.desc()).all()
    
    return render_template("driver_employment_history.html", 
                         driver=driver, 
                         employment_history=employment_history)

@driver_bp.route("/<int:driver_id>/employment_history/add", methods=["POST"])
def add_employment_history(driver_id):
    """Add a new employment history record"""
    driver = Driver.query.get_or_404(driver_id)
    
    try:
        # Get form data
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        employment_status = request.form.get("employment_status")
        
        # Convert empty end_date to None
        if end_date == "":
            end_date = None
            
        # Convert employment_status string to enum
        if employment_status == "ACTIVE":
            status_enum = EmploymentStatus.ACTIVE
        elif employment_status == "INACTIVE":
            status_enum = EmploymentStatus.INACTIVE
        else:
            raise ValueError("Invalid employment status")
        
        new_record = DriverEmploymentHistory(
            driver_id=driver_id,
            start_date=start_date,
            end_date=end_date,
            employment_status=status_enum
        )
        
        db.session.add(new_record)
        db.session.commit()
        flash(f"Employment record added successfully for {driver.full_name}", "success-msg")
        
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error-msg')
    except Exception as e:
        db.session.rollback()
        flash("An error occurred while adding the employment record", 'error-msg')
    
    return redirect(url_for("driver.driver_employment_history", driver_id=driver_id))

@driver_bp.route("/<int:driver_id>/employment_history/<int:record_id>/edit", methods=["POST"])
def edit_employment_history(driver_id, record_id):
    """Edit an existing employment history record"""
    driver = Driver.query.get_or_404(driver_id)
    record = DriverEmploymentHistory.query.get_or_404(record_id)
    
    # Verify the record belongs to the driver
    if record.driver_id != driver_id:
        flash("Invalid employment record", 'error-msg')
        return redirect(url_for("driver.driver_employment_history", driver_id=driver_id))
    
    try:
        # Get form data
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        employment_status = request.form.get("employment_status")
        
        # Convert empty end_date to None
        if end_date == "":
            end_date = None
            
        # Convert employment_status string to enum
        if employment_status == "ACTIVE":
            status_enum = EmploymentStatus.ACTIVE
        elif employment_status == "INACTIVE":
            status_enum = EmploymentStatus.INACTIVE
        else:
            raise ValueError("Invalid employment status")
        
        # Update the record
        record.start_date = start_date
        record.end_date = end_date
        record.employment_status = status_enum
        
        db.session.commit()
        flash(f"Employment record updated successfully for {driver.full_name}", "success-msg")
        
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error-msg')
    except Exception as e:
        db.session.rollback()
        flash("An error occurred while updating the employment record", 'error-msg')
    
    return redirect(url_for("driver.driver_employment_history", driver_id=driver_id))

@driver_bp.route("/<int:driver_id>/employment_history/<int:record_id>/delete", methods=["POST"])
def delete_employment_history(driver_id, record_id):
    """Delete an employment history record"""
    driver = Driver.query.get_or_404(driver_id)
    record = DriverEmploymentHistory.query.get_or_404(record_id)
    
    # Verify the record belongs to the driver
    if record.driver_id != driver_id:
        flash("Invalid employment record", 'error-msg')
        return redirect(url_for("driver.driver_employment_history", driver_id=driver_id))
    
    try:
        db.session.delete(record)
        db.session.commit()
        flash(f"Employment record deleted successfully for {driver.full_name}", "success-msg")
    except Exception as e:
        db.session.rollback()
        flash("An error occurred while deleting the employment record", 'error-msg')
    
    return redirect(url_for("driver.driver_employment_history", driver_id=driver_id))
