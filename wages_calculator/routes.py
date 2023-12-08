from flask import render_template, request, redirect, url_for
from wages_calculator import app, db
from wages_calculator.models import Driver, DayEnd


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

@app.route("/delete_driver/<int:driver_id>")
def delete_driver(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    db.session.delete(driver)
    db.session.commit()
    return render_template("add_driver.html")

@app.route("/edit_driver/<int:driver_id>", methods=["GET", "POST"])
def edit_driver(driver_id):
    drivers = list(Driver.query.all())
    driver = Driver.query.get_or_404(driver_id)
    driver.start_date = request.form.get("start_date")
    driver.first_name = request.form.get("first_name")
    db.session.add(driver)
    db.session.commit()
    return render_template("add_driver.html", drivers=drivers)




