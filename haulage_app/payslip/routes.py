from flask import render_template, request, redirect, url_for, flash, session
from haulage_app import db, f
from haulage_app.models import Driver, Payslip, Day
from haulage_app.verification.models import MissingEntryAnomaly
from haulage_app.payslip import payslip_bp
from sqlalchemy.exc import IntegrityError, NoResultFound
from haulage_app.verification.checks.verification_functions import(
    check_missing_payslip_has_been_rectified,
)
from haulage_app.functions import(
    date_to_db,
    display_date,
)

@payslip_bp.route("/add_payslip/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_payslip(item_id, tab):

    drivers = list(Driver.query.order_by(Driver.first_name).all())
    payslips = list(Payslip.query.order_by(Payslip.date.desc()).all())
    payslip = {}

    # On GET request, check session for data from a previous successful submission
    # We use .pop() to get the value and remove it, ensuring it's only used once.
    if 'last_payslip_date' in session:
        payslip['date'] = session.pop('last_payslip_date')

    anomaly_id = request.args.get('anomaly_id')
    if anomaly_id:
        anomaly = MissingEntryAnomaly.query.filter(MissingEntryAnomaly.id == anomaly_id).first()
        payslip['date'] = anomaly.date
        payslip['driver_id'] = anomaly.driver_id

    if request.method == "POST":
        try:
            date_str = request.form.get("date")
            date_obj = date_to_db(date_str)
            driver_id = int(request.form.get("driver_id"))
            # Using .one() is good, it will raise NoResultFound if no day exists
            day = Day.query.filter(Day.date == date_obj, Day.driver_id == driver_id).one()

            # The creation logic is now inside the same `try` block
            new_entry = Payslip(
                day_id = day.id,
                date = date_str,
                driver_id = driver_id,
                total_wage = request.form.get("total_wage"),
                total_cost_to_employer = request.form.get("total_cost_to_employer")
            )
            db.session.add(new_entry)
            db.session.commit()
            
            # --- This is the SUCCESS PATH ---
            flash(f"Entry Success: {new_entry.driver.full_name} - {f.display_date(new_entry.date)}", "success-msg")
            check_missing_payslip_has_been_rectified(new_entry.id)
            
            # Store the date in the session for the next form load
            session['last_payslip_date'] = display_date(new_entry.date)
            
            # Redirect to the GET endpoint
            return redirect(url_for('payslip.add_payslip', item_id=item_id, tab=tab))

        # --- ERROR PATHS below ---
        # They do NOT redirect. They preserve user data and re-render the template.
        except NoResultFound:
            driver_name = Driver.query.filter(Driver.id == request.form.get("driver_id")).first().first_name
            flash(f"Error adding payslip. No day entry found for {driver_name} on {request.form.get('date')}. Please add a day entry first.", 'error-msg')
            payslip = request.form
        except IntegrityError:
            db.session.rollback()
            flash("Payslip entry already exists for this week(Sat to Fri), edit or delete current one.", 'error-msg')
            payslip = request.form
        except ValueError as e:
            flash(str(e), 'error-msg')
            payslip = request.form
        except Exception as e:
            flash("An unexpected error occurred. Please notify the administrator. - " + str(e), 'error-msg')
            payslip = request.form

    # This is the destination for all GET requests and any failed POST requests
    return render_template("add_payslip.html", drivers=drivers, list=payslips, tab=tab, 
                           payslip=payslip, item_id=item_id, type='payslip')


#### OLD ROUTE. KEPT AS NEW ONE NOT TESTED YET.
# @payslip_bp.route("/add_payslip/<int:item_id>/<tab>", methods=["GET", "POST"])
# def add_payslip(item_id, tab):

#     anomaly_id = request.args.get('anomaly_id')
#     search_term = None

#     drivers = list(Driver.query.order_by(Driver.first_name).all())
#     payslips = list(Payslip.query.order_by(Payslip.date.desc()).all())
#     #empty dictionary to be filled with users previous answers if there
#     #are any issues with data submitted
#     payslip = {}
#     if anomaly_id:
#         anomaly = MissingEntryAnomaly.query.filter(MissingEntryAnomaly.id == anomaly_id).first()
#         date = anomaly.date

#         # search_term = f"{registration}, {previous_date} + {registration}, {next_date}"
#         # print(search_term)
#         payslip['date'] = anomaly.date
#         payslip['driver_id'] = anomaly.driver_id

#     if request.method == "POST":
#         try:
#             date_str = request.form.get("date")
#             date_obj = date_to_db(date_str)
#             driver_id = int(request.form.get("driver_id"))
#             day = Day.query.filter(Day.date == date_obj, Day.driver_id == driver_id).one()
#         except NoResultFound:
#             driver_name = Driver.query.filter(Driver.id == driver_id).first().first_name
#             flash(f"Error adding payslip. No day entry found for {driver_name} on {date_str}. Please add a day entry for this driver and date, and re-add the payslip.", 'error-msg')
#             payslip = request.form
#         except Exception as e:
#             flash("An unexpected error occurred. Please notify the administrator. - "+str(e), 'error-msg')
#             payslip = request.form
#         else:
#             try:
#                 new_entry = Payslip(
#                     day_id = day.id,
#                     date = date_str,
#                     driver_id = driver_id,
#                     total_wage = request.form.get("total_wage"),
#                     total_cost_to_employer = request.form.get("total_cost_to_employer")    
#                 )
#                 db.session.add(new_entry)
#                 db.session.commit()
#             except IntegrityError as e:
#                 db.session.rollback()
#                 flash("Payslip entry already exists for this week(Sat to Fri), edit or delete current one.", 'error-msg')
#                 payslip = request.form
#             except ValueError as e:
#                 flash(str(e), 'error-msg')
#                 #retrieve previous answers
#                 payslip = request.form
#             else:
#                 flash(f"Entry Success: {new_entry.driver.full_name} - {f.display_date(new_entry.date)}", "success-msg")
#                 payslip['date'] = new_entry.date
#                 check_missing_payslip_has_been_rectified(new_entry.id)
#     return render_template("add_payslip.html", drivers=drivers, list=payslips, tab=tab, 
#                            payslip=payslip, item_id=item_id, type='payslip')

@payslip_bp.route("/delete_payslip/<int:item_id>")
def delete_payslip(item_id):
    entry = Payslip.query.get_or_404(item_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted", "success-msg")
    return redirect(url_for("payslip.add_payslip", item_id=0, tab='history'))

@payslip_bp.route("/edit_payslip/<int:item_id>", methods=["POST"])
def edit_payslip(item_id):
    entry = Payslip.query.get_or_404(item_id)
    try:
        entry.date = request.form.get("date")
        entry.driver_id = request.form.get("driver_id")
        entry.total_wage = request.form.get("total_wage")
        entry.total_cost_to_employer = request.form.get("total_cost_to_employer")
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        flash("Payslip entry already exists for this week(Sat to Fri), edit or delete current one.", 'error-msg-modal')
        return redirect(url_for("payslip.add_payslip", item_id=item_id, tab='edit'))
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("payslip.add_payslip", item_id=item_id, tab='edit'))
    else:
        flash(f"Entry Success: {entry.driver.full_name} - {f.display_date(entry.date)}", "success-msg")
        return redirect(url_for("payslip.add_payslip", item_id=0, tab='edit'))
