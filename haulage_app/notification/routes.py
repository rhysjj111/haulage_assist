from flask import render_template, request, url_for, jsonify
from haulage_app import db, app
from haulage_app.models import (
    Driver, 
    Day, 
    Job, 
    Truck, 
    Fuel,
    Payslip,
    )
from haulage_app.verification.models import Anomaly
from haulage_app.utilities.verify_gemini_utils import GeminiVerifier
from haulage_app.verification.checks.verification_functions import(
    get_all_missing_payslip_weeks,
    )
from haulage_app.verification.checks.verification_manager import(
    payslip_check,
    fuel_check,
    day_check,
    )
from haulage_app.verification.checks.verification_functions import(
    check_all_missing_fuel_data,
)
from datetime import timedelta, date, datetime
from haulage_app.notification import notification_bp
# from haulage_app.notification.models import TimeframeEnum, ErrorTypeEnum, FaultAreaEnum, Notification
from pprint import pprint
from haulage_app.config import DATA_BEGIN_DATE as start_date

@app.context_processor
def inject_notification():
    # def get_notification():
    #     return Notification.query.filter_by(is_read=False).order_by(Notification.timestamp.desc()).all()
    # return dict(notifications=get_notifications())

    test_notifications = []

    anomalies = Anomaly.query.filter_by(is_read=False).limit(5).all()
    for anomaly in anomalies:
        anomaly_info = {
            "id": anomaly.id,
            "date": anomaly.date,
            "details": anomaly.description,
            "table_name": anomaly.table_name,
        }
        if anomaly.driver_id is not None:
            anomaly_info["driver_id"] = anomaly.driver_id
        elif anomaly.truck_id is not None:
            anomaly_info["truck_id"] = anomaly.truck_id
        test_notifications.append(anomaly_info)

    return {'notifications': test_notifications}

