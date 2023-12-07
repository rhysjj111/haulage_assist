from flask import render_template, request, redirect, url_for
from wages_calculator import app, db
from wages_calculator.models import Driver, Day_end


@app.route("/")
def home():
    return render_template("data_entry.html")

@app.route("/add_driver", methods=["GET", "POST"])
def add_driver():
    drivers = list(Driver.query.all())
    if request.method == "POST":
        driver = Driver(
            start_date=request.form.get("start_date"),
            first_name=request.form.get("first_name"),
            second_name=request.form.get("second_name"),
            base_wage=request.form.get("base_wage"),
            bonus_percentage=request.form.get("bonus_percentage")
            )
        db.session.add(driver)
        db.session.commit()
    return render_template("add_driver.html", drivers=drivers)

