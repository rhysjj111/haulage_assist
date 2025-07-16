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
    mileage_check,
    )
from haulage_app.verification.checks.verification_functions import(
    check_all_missing_fuel_data,
    find_incorrect_mileage,
    check_all_incorrect_mileages,
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

    # find_incorrect_mileage(2, 2025, 3)
    # mileage_check()
    # day_check()
    # fuel_check()
    # payslip_check()

    # notifications = {}
    # notifications['mileage_notifications'] = []
    # mileage_anomalies = Anomaly.query.filter(Anomaly.type == 'incorrect_mileage').all()
    # for anomaly in mileage_anomalies:
    #     anomaly_info = {
    #         "id": anomaly.id,
    #         "details": anomaly.description,
    #         "json": {
    #             "truck_id": anomaly.truck_id,
    #             "previous_date": anomaly.previous_date,
    #             "next_date": anomaly.next_date,
    #         },
    #     }
    #     notifications['mileage_notifications'].append(anomaly_info)
    # return notifications
    
    try:
        notifications = []

        anomalies = Anomaly.query.filter_by(is_read=False).all()
        for anomaly in anomalies:
            if anomaly.type == 'incorrect_mileage':
                entry_type = 'day'
            else:
                entry_type = anomaly.table_name.value
            anomaly_info = {
                "id": anomaly.id,
                # "date": anomaly.date,
                "details": anomaly.description,
                # "table_name": anomaly.table_name,
                "entry_type": entry_type
            }
            # if anomaly.driver_id is not None:
            #     anomaly_info["driver_id"] = anomaly.driver_id
            # elif anomaly.truck_id is not None:
            #     anomaly_info["truck_id"] = anomaly.truck_id
            notifications.append(anomaly_info)

        return {'notifications': notifications}
    
    except Exception as e:
        # Log the error or handle it appropriately
        print(f"Error in inject_notification: {e}")
        return {'notifications': []}


