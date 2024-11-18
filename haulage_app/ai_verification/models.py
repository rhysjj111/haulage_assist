from haulage_app import db
from datetime import datetime
# from haulage_app.notification.models import Notification

class VerificationFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    notification_id = db.Column(db.Integer, db.ForeignKey('notification.id'))
    acceptable_structure = db.Column(db.Boolean, nullable=False)
    notification_effective = db.Column(db.Boolean, nullable=False)

