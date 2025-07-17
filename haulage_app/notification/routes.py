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

        anomalies = Anomaly.query.filter_by(is_read=False).order_by(
            Anomaly.type,
            Anomaly.year,
            Anomaly.week_number
        ).all()
        filtered_anomalies = []

        for anomaly in anomalies:
            # Include IncorrectMileage anomalies
            if anomaly.type == 'incorrect_mileage':
                filtered_anomalies.append(anomaly)
            # Include MissingEntryAnomaly but exclude those with table_name = 'day'
            elif anomaly.type == 'missing_entry':
                if hasattr(anomaly, 'table_name') and anomaly.table_name.value != 'day':
                    filtered_anomalies.append(anomaly)

        for anomaly in filtered_anomalies:
            if anomaly.type == 'incorrect_mileage':
                entry_type = 'day'
            else:
                entry_type = anomaly.table_name.value

            date_tuple = (anomaly.year, anomaly.week_number) if anomaly.year is not None and anomaly.week_number is not None else None
            
            anomaly_info = {
                "id": anomaly.id,
                "date": date_tuple,
                "details": anomaly.description,
                "entry_type": entry_type
            }
            notifications.append(anomaly_info)

        return {'notifications': notifications}
    
    except Exception as e:
        # Log the error or handle it appropriately
        print(f"Error in inject_notification: {e}")
        return {'notifications': []}


