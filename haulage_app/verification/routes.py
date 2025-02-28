from flask import (
    render_template, 
    request, 
    url_for,
    session, 
    redirect,
    flash
)
from haulage_app import db
from haulage_app.models import (
    Driver, Day, Job, Truck, Fuel, Expense, 
    ExpenseOccurrence, Payslip
)
from haulage_app.verification.models import (
    Anomaly, 
    UserFeedback, 
    TableName
)
from datetime import timedelta, date, datetime
from haulage_app.verification import verification_bp
from pprint import pprint
from haulage_app.config import *

@verification_bp.route('/verification/<anomaly_id>', methods=['POST'])
def handle_user_feedback(anomaly_id):
    # Redirect back to the previous page stored in the session
    previous_url = session.get('previous_url')
    if previous_url:
        redirect_url = previous_url
    else:
        redirect_url = url_for('home')

    print('as;dkfja;sdlfjalskdjfa;klsdjf')

    print(redirect_url)

    try:
        feedback_value = request.form['feedback']
        anomaly = Anomaly.query.get_or_404(anomaly_id)

        user_feedback = UserFeedback(
            anomaly_id=anomaly_id,
        )

        if feedback_value == 'no_fault_found':
            user_feedback.anomaly_invalid = True

        elif feedback_value == 'fault_rectified':
            user_feedback.anomaly_rectified = True

        else:
            flash('Invalid feedback value', 'error-msg')
            return redirect(redirect_url)

        anomaly.is_read = True

        db.session.add(user_feedback)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        flash(f'An error has occured: {str(e)}', 'error-msg')
        return redirect(redirect_url)
    else:
        flash('Feedback recorded successfully', 'success-msg')
        return redirect(redirect_url)

