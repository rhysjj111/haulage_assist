from haulage_app import db
from datetime import datetime

class AiResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    raw_response = db.Column(db.Text, nullable=False)
    historical_context = db.Column(db.Text)
    format_successful = db.Column(db.Boolean) ## This column will be ticked if formatting is successful, and user has verified each of the results as helpful.
    contains_repeat_suggestion = db.Column(db.Boolean)
    all_helpful = db.Column(db.Boolean)

    verification = db.relationship('Verification', backref='ai_response', lazy=True)
    formatted_anomaly = db.relationship('FormattedAnomaly', backref='ai_response', lazy=True)

class AiResponseFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_confirmed_anomaly = db.Column(db.Boolean)

    ai_response_id = db.Column(db.Integer, db.ForeignKey('ai_response.id'), nullable=False)
    formatted_anomaly_id = db.Column(db.Integer, db.ForeignKey('formatted_anomaly.id'))

class FormattedAnomaly(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ai_response_id = db.Column(db.Integer, db.ForeignKey('ai_response.id'))
    
    anomaly_type = db.Column(db.string(50), nullable=False)

    verification = db.relationship('Verification', backref='formatted_anomaly', uselist=False, lazy=True)

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

class MissingAnomaly(FormattedAnomaly):
    anomaly_date = db.Column(db.Date)
    anomaly_driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'))
    anomaly_truck_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    table_name = db.Column(db.Enum(TableName), nullable=False)

    driver = db.relationship('Driver', lazy='joined', uselist=False)
    truck = db.relationship('Truck', lazy='joined', uselist=False)


    __mapper_args__ = {'polymorphic_identity': 'missing_anomaly'}

class IncorrectAnomaly(FormattedAnomaly):
    record_id = db.Column(db.Integer(30))
    table_name = db.Column(db.String(64))
    explanation_message = db.Column(db.String(255))

    __mapper_args__ = {
        'polymorphic_identity': 'incorrect_anomaly',
        'polymorphic_on': table_name
        }

class DayAnomoly(IncorrectAnomaly):
    day = db.relationship('Day', foreign_keys=[FormattedAnomaly.record_id])

    def get_display_data(self):
        return {
            'title': f"Day Entry Anoomaly",
            'details': f"Anomaly detected in day record for {self.day.driver.full_name} on {self.day.date}.",
        }

    __mapper_args__ = {'polymorphic_identity': 'day_anomaly'}

class JobAnomaly(IncorrectAnomaly):
    job = db.relationship('Job', foreign_keys=[FormattedAnomaly.record_id])

    def get_display_data(self):
        return {
            'title': f"Job Entry Anomaly",
            'details': f"Anomaly detected in job record for {self.job.driver.full_name} on {self.job.date}.",
        }

    __mapper_args__ = {'polymorphic_identity': 'job'}

class FuelAnomaly(IncorrectAnomaly):
    fuel = db.relationship('Fuel', foreign_keys=[FormattedAnomaly.record_id])

    def get_display_data(self):
        return {
            'title': f"Fuel Entry Anomaly",
            'details': f"Anomaly detected in fuel record for {self.fuel.truck.registration} on {self.fuel.date}.",
        }

    __mapper_args__ = {'polymorphic_identity': 'fuel'}

class PayslipAnomaly(IncorrectAnomaly):
    payslip = db.relationship('Payslip', foreign_keys=[FormattedAnomaly.record_id])

    def get_display_data(self):
        return {
            'title': f"Payslip Entry Anomaly",
            'details': f"Anomaly detected in payslip record for {self.payslip.driver.full_name} on {self.payslip.date}.",
        }

    __mapper_args__ = {'polymorphic_identity': 'payslip'}
