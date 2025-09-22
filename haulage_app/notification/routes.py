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
from haulage_app.verification.models import Anomaly, IncorrectMileage, MissingEntryAnomaly, TableName
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
from haulage_app.analysis.functions import(
    get_start_and_end_of_week,
    get_start_of_week,
    find_previous_saturday,
    get_week_number_sat_to_fri,
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

        # Query IncorrectMileage anomalies first (sorted)
        incorrect_mileage_anomalies = IncorrectMileage.query.filter_by(is_read=False).order_by(
            IncorrectMileage.year,
            IncorrectMileage.week_number
        ).all()

        # Query MissingEntryAnomaly anomalies (excluding table_name = 'day', sorted)
        missing_entry_anomalies = MissingEntryAnomaly.query.filter(
            MissingEntryAnomaly.is_read == False,
            MissingEntryAnomaly.table_name != TableName.DAY
        ).order_by(
            MissingEntryAnomaly.table_name,
            MissingEntryAnomaly.date,
        ).all()

        # Combine them in the order you want
        anomalies = missing_entry_anomalies + incorrect_mileage_anomalies

        hacked_date_tuple = (2025, 38)

        for anomaly in anomalies:
            if anomaly.type == 'incorrect_mileage':
                entry_table = 'day'
                date_tuple = (anomaly.year, anomaly.week_number)
            else:
                entry_table = anomaly.table_name.value
                date_tuple = get_week_number_sat_to_fri(anomaly.date)

            if date_tuple > hacked_date_tuple:

                anomaly_info = {
                    "id": anomaly.id,
                    "date": date_tuple,
                    "details": anomaly.description,
                    "entry_table": entry_table
                }
                notifications.append(anomaly_info)

        return {'notifications': notifications}
    
    except Exception as e:
        return {'notifications': []}
