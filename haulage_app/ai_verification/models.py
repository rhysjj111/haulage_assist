from haulage_app import db
from datetime import datetime

class RawResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    raw_response = db.Column(db.Text, nullable=False)
    historical_context = db.Column(db.Text)
    processing_successful = db.Column(db.Boolean, default=True) ## This column will be ticked if formatting is successful, and user has verified each of the results as helpful.
    all_suggestions_helpful = db.Column(db.Boolean, default=True)

    ai_response_feedback = db.relationship('AiResponseFeedback', backref='raw_response', lazy=True)
    processed_response = db.relationship('ProcessedResponse', backref='raw_response', lazy=True)

class AiResponseFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_confirmed_anomaly = db.Column(db.Boolean)

    ai_response_id = db.Column(db.Integer, db.ForeignKey('raw_response.id'), nullable=False)
    processed_response_id = db.Column(db.Integer, db.ForeignKey('processed_response.id'))

class ProcessedResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ai_response_id = db.Column(db.Integer, db.ForeignKey('ai_response.id'))
    
    type = db.Column(db.string(50), nullable=False)

    ai_response_feedback = db.relationship(
        'AiResponseFeedback', backref='processed_response', uselist=False, lazy=True
    )

    __mapper_args__ = {
        'polymorphic_on': anomaly_type
    }

class TableName(Enum):
    DRIVER = 'driver'
    TRUCK = 'truck'
    DAY = 'day'
    JOB = 'job'
    FUEL = 'fuel'
    PAYSLIP = 'payslip'

class MissingEntry(ProcessedResponse):
    date = db.Column(db.Date)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'))
    truck_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    table_name = db.Column(db.Enum(TableName), nullable=False)
    suggestion_exists = db.Column(db.Boolean, default=False)
    suggestion_repeated = db.Column(db.Boolean, default=False)

    driver = db.relationship('Driver', lazy='joined', uselist=False)
    truck = db.relationship('Truck', lazy='joined', uselist=False)

    __mapper_args__ = {'polymorphic_identity': 'missing_anomaly'}

class Anomaly(ProcessedResponse):
    record_id = db.Column(db.Integer(30))
    table_name = db.Column(db.String(64))
    explanation_message = db.Column(db.String(255))

    __mapper_args__ = {
        'polymorphic_identity': 'anomaly',
        'polymorphic_on': table_name
        }

class DayAnomoly(Anomaly):
    day = db.relationship('Day', foreign_keys=[ProcessedResponse.record_id])

    def get_display_data(self):
        return {
            'title': f"Day Entry Anoomaly",
            'details': f"Anomaly detected in day record for {self.day.driver.full_name} on {self.day.date}.",
        }

    __mapper_args__ = {'polymorphic_identity': 'day_anomaly'}

class JobAnomaly(Anomaly):
    job = db.relationship('Job', foreign_keys=[ProcessedResponse.record_id])

    def get_display_data(self):
        return {
            'title': f"Job Entry Anomaly",
            'details': f"Anomaly detected in job record for {self.job.driver.full_name} on {self.job.date}.",
        }

    __mapper_args__ = {'polymorphic_identity': 'job'}

class FuelAnomaly(Anomaly):
    fuel = db.relationship('Fuel', foreign_keys=[ProcessedResponse.record_id])

    def get_display_data(self):
        return {
            'title': f"Fuel Entry Anomaly",
            'details': f"Anomaly detected in fuel record for {self.fuel.truck.registration} on {self.fuel.date}.",
        }

    __mapper_args__ = {'polymorphic_identity': 'fuel'}

class PayslipAnomaly(Anomaly):
    payslip = db.relationship('Payslip', foreign_keys=[ProcessedResponse.record_id])

    def get_display_data(self):
        return {
            'title': f"Payslip Entry Anomaly",
            'details': f"Anomaly detected in payslip record for {self.payslip.driver.full_name} on {self.payslip.date}.",
        }

    __mapper_args__ = {'polymorphic_identity': 'payslip'}
