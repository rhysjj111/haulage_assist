from haulage_app import app, db
from haulage_app.models import Expense, ExpenseOccurance
from haulage_app.functions import date_to_db, currency_to_db

def add_expense_and_occurrence():
    with app.app_context():
        new_expense = Expense(name="Truck Maintenance", description="Regular maintenance for trucks")
        db.session.add(new_expense)
        db.session.commit()

        # new_occurrence = ExpenseOccurance(
        #     expense_id=new_expense.id,
        #     date_start=date_to_db("01/01/2023"),
        #     date_end=date_to_db("31/12/2023"),
        #     cost=currency_to_db("500.00"),
        #     frequency="Monthly"
        # )
        # db.session.add(new_occurrence)
        # db.session.commit()

        print("Expense and occurrence added successfully!")

if __name__ == "__main__":
    add_expense_and_occurrence()

