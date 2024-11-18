from haulage_app.models import db
from datetime import datetime
from enum import Enum
# from haulage_app.ai_verification.models import VerificationFeedback


class TimeframeEnum(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"

class ErrorTypeEnum(Enum):
    MISSING_DATA = "Missing data" 
    INCORRECT_DATA = "Incorrect data"
    SUSPICIOUS_ACTIVITY = "Suspicious activity"

class FaultAreaEnum(Enum):
    DAY_FUEL = "Day - fuel"
    DAY_MILEAGE = "Day - mileage"
    DAY_EARNED = "Day - earned"
    FUEL = "Fuel"
    PAYSLIP = "Payslip"
    JOB = "Job"

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    verification_data = db.Column(db.JSON)
    timeframe = db.Column(db.Enum(TimeframeEnum))
    error_type = db.Column(db.Enum(ErrorTypeEnum))
    primary_fault_area = db.Column(db.Enum(FaultAreaEnum))
    secondary_fault_area = db.Column(db.Enum(FaultAreaEnum))
    answer = db.Column(db.String(200), nullable=False)
    is_read = db.Column(db.Boolean, default=False)

    feedback = db.relationship('VerificationFeedback', backref='notification', lazy=True)