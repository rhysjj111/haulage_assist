
from haulage_app.models import db
from datetime import datetime
from enum import Enum

class TimeframeEnum(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"

class ErrorTypeEnum(Enum):
    INFO = "info"
    MISSING_DATA = "missing_data" 
    INCORRECT_DATA = "incorrect_data"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"

class FaultAreaEnum(Enum):
    DAY_FUEL = "day_fuel"
    DAY_MILEAGE = "day_mileage"
    FUEL = "fuel"
    PAYSLIP = "payslip"
    JOB = "job"

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    verification_data = db.Column(db.JSON)
    timeframe = db.Column(db.Enum(TimeframeEnum))
    error_type = db.Column(db.Enum(ErrorTypeEnum), default=ErrorTypeEnum.INFO)
    primary_fault_area = db.Column(db.Enum(FaultAreaEnum))
    secondary_fault_area = db.Column(db.Enum(FaultAreaEnum))
    answer = db.Column(db.String(200), nullable=False)
    is_read = db.Column(db.Boolean, default=False)

    feedback = db.relationship('VerificationFeedback', backref='notification', lazy=True)