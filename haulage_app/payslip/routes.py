from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Driver, Payslip 
from haulage_app.verification.models import MissingEntryAnomaly
from haulage_app.payslip import payslip_bp
from sqlalchemy.exc import IntegrityError
from haulage_app.verification.checks.verification_functions import(
    check_missing_payslip_has_been_rectified,
)

@payslip_bp.route("/add_payslip/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_payslip(item_id, tab):

    anomaly_id = request.args.get('anomaly_id')
    search_term = None

    drivers = list(Driver.query.order_by(Driver.first_name).all())
    payslips = list(Payslip.query.order_by(Payslip.date.desc()).all())
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    payslip = {}
    if anomaly_id:
        anomaly = MissingEntryAnomaly.query.filter(MissingEntryAnomaly.id == anomaly_id).first()
        date = anomaly.date

        # search_term = f"{registration}, {previous_date} + {registration}, {next_date}"
        # print(search_term)
        payslip['date'] = anomaly.date
        payslip['driver_id'] = anomaly.driver_id

    if request.method == "POST":
        try:
            new_entry = Payslip(
                date = request.form.get("date"),
                driver_id = request.form.get("driver_id"),
                total_wage = request.form.get("total_wage"),
                total_cost_to_employer = request.form.get("total_cost_to_employer")    
            )
            db.session.add(new_entry)
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            flash("Payslip entry already exists for this week(Sat to Fri), edit or delete current one.", 'error-msg')
            payslip = request.form
        except ValueError as e:
            flash(str(e), 'error-msg')
            #retrieve previous answers
            payslip = request.form
        else:
            flash(f"Entry Success: {new_entry.driver.full_name} - {f.display_date(new_entry.date)}", "success-msg")
            payslip['date'] = new_entry.date
            check_missing_payslip_has_been_rectified(new_entry.id)
    return render_template("add_payslip.html", drivers=drivers, list=payslips, tab=tab, 
                           payslip=payslip, item_id=item_id, type='payslip')

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
