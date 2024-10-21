from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Expense, ExpenseOccurance 
from haulage_app.expense import expense_bp


@expense_bp.route("/add_expense/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_expense(item_id, tab):
    # expenses = list(Expense.query.order_by(Expense.name).all())
    test='test'
    expenses = {test: 'test'}
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    expense = {}
    # if request.method == "POST":
    #     try:
    #         new_entry = expense(
    #             date = request.form.get("date"),
    #             driver_id = request.form.get("driver_id"),
    #             total_wage = request.form.get("total_wage"),
    #             total_cost_to_employer = request.form.get("total_cost_to_employer")    
    #         )
    #         db.session.add(new_entry)
    #         db.session.commit()
    #     except ValueError as e:
    #         flash(str(e), 'error-msg')
    #         #retrieve previous answers
    #         expense = request.form
    #     else:
    #         flash(f"Entry Success: {new_entry.driver.full_name} - {f.display_date(new_entry.date)}", "success-msg")
    #         return redirect(url_for("expense.add_expense", drivers=drivers, expenses=expenses, 
    #                         tab='entry', item_id=0))
    return render_template("add_expense.html", tab=tab, 
                           expense=expense, item_id=item_id, type='expense')

@expense_bp.route("/delete_expense/<int:item_id>")
def delete_expense(item_id):
    entry = expense.query.get_or_404(item_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted", "success-msg")
    return redirect(url_for("expense.add_expense", item_id=0, tab='history'))

@expense_bp.route("/edit_expense/<int:item_id>", methods=["POST"])
def edit_expense(item_id):
    entry = expense.query.get_or_404(item_id)
    try:
        entry.date = request.form.get("date")
        entry.driver_id = request.form.get("driver_id")
        entry.total_wage = request.form.get("total_wage")
        entry.total_cost_to_employer = request.form.get("total_cost_to_employer")
        db.session.commit()
    except ValueError as e:
        flash(str(e), 'error-msg-modal')
        return redirect(url_for("expense.add_expense", item_id=item_id, tab='edit'))
    else:
        flash("Success", "success-msg")
        return redirect(url_for("expense.add_expense", item_id=0, tab='edit'))
