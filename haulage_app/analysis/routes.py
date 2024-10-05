from flask import Blueprint, render_template, request, url_for
from haulage_app import db, f
from haulage_app.models import Driver, Day, Job, Truck
from datetime import timedelta, date, datetime
from pprint import pprint

analysis_bp = Blueprint('analysis', __name__, url_prefix='/analysis', template_folder='../analysis/templates/')
print(f"cunt {analysis_bp.template_folder}")

@analysis_bp.route("/weekly_analysis", methods=["GET"])
def weekly_analysis():
    return render_template('analysis/weekly_analysis.html')

