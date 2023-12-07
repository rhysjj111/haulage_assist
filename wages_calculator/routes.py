from flask import render_template, request, redirect, url_for
from wages_calculator import app, db
from wages_calculator.models import Driver, Day_end


@app.route("/")
def home():
    return render_template("driver_entry.html")
