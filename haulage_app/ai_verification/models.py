# from haulage_app import db
# from datetime import datetime
# from enum import Enum
# from haulage_app.functions import *


# class RawResponse(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     timestamp = db.Column(db.DateTime, default=datetime.utcnow)
#     raw_response = db.Column(db.Text, nullable=False)
#     historical_context = db.Column(db.Text)
#     processing_successful = db.Column(db.Boolean, default=True) ## This column will be ticked if formatting is successful, and user has verified each of the results as helpful.
#     all_suggestions_helpful = db.Column(db.Boolean, default=True)

#     ai_response_feedback = db.relationship(
#         'AiResponseUserFeedback', backref='raw_response', lazy=True
#     )
#     processed_response = db.relationship(
#         'ProcessedResponse', backref='raw_response', lazy=True
#     )

# class AiResponseUserFeedback(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     timestamp = db.Column(db.DateTime, default=datetime.utcnow)
#     directly_helpful = db.Column(db.Boolean) # The suggestion was spot on.
#     indirectly_helpful = db.Column(db.Boolean) # The suggestion wasn't correct but led to a correction.

#     ai_response_id = db.Column(db.Integer, db.ForeignKey('raw_response.id'), nullable=False)
#     processed_response_id = db.Column(db.Integer, db.ForeignKey('processed_response.id'), nullable=False)

# class ProcessedResponse(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
#     type = db.Column(db.String(50), nullable=False)

#     raw_response_id = db.Column(db.Integer, db.ForeignKey('raw_response.id'))
#     ai_response_feedback = db.relationship(
#         'AiResponseUserFeedback', backref='processed_response', uselist=False, lazy=True
#     )
#     __mapper_args__ = {'polymorphic_on': type}

# class TableName(Enum):
#     DRIVER = 'driver'
#     TRUCK = 'truck'
#     DAY = 'day'
#     JOB = 'job'
#     FUEL = 'fuel'
#     PAYSLIP = 'payslip'

#     # table_name_enum = db.Enum(TableName, name='table_name_enum')

# class MissingEntry(ProcessedResponse):
#     date = db.Column(db.Date)
#     driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True)
#     truck_id = db.Column(db.Integer, db.ForeignKey('truck.id'), nullable=True)
#     table_name = db.Column(db.Enum(TableName), nullable=False)
#     # table_name = db.Column(table_name_enum, nullable=False) 
#     suggestion_exists = db.Column(db.Boolean, default=False)
#     suggestion_repeated = db.Column(db.Boolean, default=False)

#     driver = db.relationship('Driver', uselist=False, lazy='joined')
#     truck = db.relationship('Truck', uselist=False, lazy='joined')

#     __mapper_args__ = {'polymorphic_identity': 'missing_entry'}


# class DayAnomaly(ProcessedResponse):
#     day_id = db.Column(db.Integer, db.ForeignKey('day.id'), nullable=False)
#     day = db.relationship('Day', backref='anomalies', lazy='joined')
#     explanation_message = db.Column(db.Text)  # Explanation moved here
#     __mapper_args__ = {'polymorphic_identity': 'day_anomaly'}


# class JobAnomaly(ProcessedResponse):
#     job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
#     job = db.relationship('Job', backref='anomalies', lazy='joined')
#     explanation_message = db.Column(db.Text)  # Explanation moved here
#     __mapper_args__ = {'polymorphic_identity': 'job_anomaly'}


# class FuelAnomaly(ProcessedResponse):
#     fuel_id = db.Column(db.Integer, db.ForeignKey('fuel.id'), nullable=False)
#     fuel = db.relationship('Fuel', backref='anomalies', lazy='joined')
#     explanation_message = db.Column(db.Text)  # Explanation moved here
#     __mapper_args__ = {'polymorphic_identity': 'fuel_anomaly'}


# class PayslipAnomaly(ProcessedResponse):
#     payslip_id = db.Column(db.Integer, db.ForeignKey('payslip.id'), nullable=False)
#     payslip = db.relationship('Payslip', backref='anomalies', lazy='joined')
#     explanation_message = db.Column(db.Text)  # Explanation moved here
#     __mapper_args__ = {'polymorphic_identity': 'payslip_anomaly'}
