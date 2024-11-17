from flask import render_template, request, url_for
from haulage_app import db, ai
from haulage_app.models import (
    Driver, Day, Job, Truck, Fuel, Expense, 
    ExpenseOccurrence, Payslip)
from haulage_app.ai_verification.models import VerificationFeedback

from datetime import timedelta, date, datetime
from haulage_app.notification import notification_bp
from haulage_app.notification.models import TimeframeEnum, ErrorTypeEnum, FaultAreaEnum, Notification
from pprint import pprint
from haulage_app.config import *
from haulage_app.calculations.driver_truck_metrics import (
    calculate_driver_metrics_week,
    calculate_truck_metrics_week,
    calculate_total_metric_list,
    calculate_total_metric_dict,)
from haulage_app.functions import(
    get_week_number_sat_to_fri,
    get_start_of_week,
    get_start_end_of_week,
    get_weeks_for_period,)

@notification_bp.route("/", methods=["GET"])
def notification():
    return render_template("notification.html")

@notification_bp.route("/create_test")
def create_test_notification():
    test_notification = Notification(
        verification_data={'test': 'data'},
        timeframe=TimeframeEnum.DAILY,
        error_type=ErrorTypeEnum.INFO,
        primary_fault_area=FaultAreaEnum.FUEL,
        answer="This is a test notification"
    )
    db.session.add(test_notification)
    db.session.commit()
    return "Test notification created!"