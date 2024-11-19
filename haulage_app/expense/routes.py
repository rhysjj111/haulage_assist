from flask import render_template, request, redirect, url_for, flash
from haulage_app import db, f
from haulage_app.models import Expense, ExpenseOccurrence 
from haulage_app.expense import expense_bp


@expense_bp.route("/add_expense/<int:item_id>/<tab>", methods=["GET", "POST"])
def add_expense(item_id, tab):
    expenses = list(ExpenseOccurrence.query.all())
    #empty dictionary to be filled with users previous answers if there
    #are any issues with data submitted
    expense = {}
    if request.method == "POST":
        try:
            new_expense = Expense(
                name=request.form.get("name"),
                description=request.form.get("description")
            )
            db.session.add(new_expense)
            db.session.flush()  # This assigns an ID to new_expense before commit
            
            # Then create the ExpenseOccurrence linked to the Expense
            new_occurrence = ExpenseOccurrence(
                expense_id=new_expense.id,
                start_date=request.form.get("start_date"),
                cost=request.form.get("cost")
            )
            db.session.add(new_occurrence)
            db.session.commit()
        except ValueError as e:
            flash(str(e), 'error-msg')
            #retrieve previous answers
            expense = request.form
        else:
            flash(f"Entry Success: {new_expense.name} - {f.display_date(new_occurrence.start_date)}", "success-msg")
            return redirect(url_for("expense.add_expense", expenses=expenses, 
                            tab='entry', item_id=0))
    return render_template("expense/add_expense.html", tab=tab, list=expenses,
                           expense=expense, item_id=item_id, type='expense')

@expense_bp.route("/delete_expense/<int:item_id>")
def delete_expense(item_id):
    expense_occurrence = ExpenseOccurrence.query.get_or_404(item_id)
    expense = expense_occurrence.expense
    db.session.delete(expense)
    db.session.commit()
    flash("Entry deleted", "success-msg")
    return redirect(url_for("expense.add_expense", item_id=0, tab='history'))

@expense_bp.route("/edit_expense/<int:item_id>", methods=["POST"])
def edit_expense(item_id):
    entry = Expense.query.get_or_404(item_id)
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
