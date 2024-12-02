from flask import render_template, request, url_for, jsonify
from haulage_app import db, app
from haulage_app.models import (
    Driver, Day, Job, Truck, Fuel, Expense, 
    ExpenseOccurrence, Payslip)
# from haulage_app.ai_verification.models import VerificationFeedback
from haulage_app.ai_verification.routes import GeminiVerifier
from datetime import timedelta, date, datetime
from haulage_app.notification import notification_bp
# from haulage_app.notification.models import TimeframeEnum, ErrorTypeEnum, FaultAreaEnum, Notification
from pprint import pprint

@app.context_processor
def inject_notification():
    # def get_notification():
    #     return Notification.query.filter_by(is_read=False).order_by(Notification.timestamp.desc()).all()
    # return dict(notifications=get_notifications())

    # test_notifications = [
    #     {
    #         'id': 1,
    #         'message': 'Driver John Smith has unusually high earnings of £2800',
    #         'timestamp': datetime.now(),
    #         'category': 'verification',
    #         'is_read': False
    #     },
    #     {
    #         'id': 2,
    #         'message': 'Multiple drivers showing earnings below base wage this week',
    #         'timestamp': datetime.now() - timedelta(hours=2),
    #         'category': 'alert',
    #         'is_read': False
    #     },
    #     {
    #         'id': 3,
    #         'message': 'New pattern detected: Weekend earnings 40% higher than weekday average',
    #         'timestamp': datetime.now() - timedelta(days=1),
    #         'category': 'insight',
    #         'is_read': False
    #     }
    # ]

    # test_notifications = []
    # print(type(Payslip.query.all()))
    verifier = GeminiVerifier()
    llm_response, historical_context, table = verifier.llm_check_missing_payslips()
    test_notifications = verifier.process_llm_missing_data_response(llm_response, historical_context, table)

    return {'notifications': [test_notifications]}

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

@notification_bp.route('/test-notification')
def test_notification():
    # Create a notification
    notification = Notification(
        timeframe=TimeframeEnum.DAILY,
        error_type=ErrorTypeEnum.MISSING_DATA,
        primary_fault_area=FaultAreaEnum.DAY_FUEL,
        answer="Test notification"
    )
    db.session.add(notification)
    db.session.commit()

    # Create feedback linked to the notification
    feedback = VerificationFeedback(
        notification_id=notification.id,
        acceptable_structure=False,
        notification_effective=True
    )
    db.session.add(feedback)
    db.session.commit()

    # Test the relationship and return results
    result = {
        "notification_id": notification.id,
        "notification_fault_area": notification.primary_fault_area.value,
        "notification_feedback": [{"id": f.id, "acceptable": f.acceptable_structure} for f in notification.feedback],
        "feedback_notification": {
            "id": feedback.notification.id,
            "answer": feedback.notification.answer
        }
    }

    return jsonify(result)

@notification_bp.route("/delete-test-notifications")
def delete_test_notifications():
    # Delete associated feedback first due to foreign key relationship
    ver = VerificationFeedback.query.all()
    VerificationFeedback.query.delete()
    # Delete all notifications
    notif = Notification.query.all()
    Notification.query.delete()
    db.session.commit()
    remaining_entries = []
    for i in notif:
        remaining_entries.append(i.id)
    for i in ver:
        remaining_entries.append(f"v- {i.id}")
    return jsonify(remaining_entries)