from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Driver, Payslip 
from haulage_app.payslip import payslip_bp


@payslip_bp.route("/add_payslip/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_payslip(item_id, tab):
    drivers = list(Driver.query.order_by(Driver.first_name).all())
    payslips = list(Payslip.query.order_by(Payslip.date).all())
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    payslip = {}
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
        except ValueError as e:
            flash(str(e), 'error-msg')
            #retrieve previous answers
            payslip = request.form
        else:
            flash(f"Entry Success: {new_entry.driver.full_name} - {f.display_date(new_entry.date)}", "success-msg")
            return redirect(url_for("payslip.add_payslip", drivers=drivers, payslips=payslips, 
                            tab='entry', item_id=0))
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
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("payslip.add_payslip", item_id=item_id, tab='edit'))
    else:
        flash("Success", "success-msg")
        return redirect(url_for("payslip.add_payslip", item_id=0, tab='edit'))
