from haulage_app import db, app
from haulage_app.verification.models import Anomaly

def delete_all_anomalies():
    Anomaly.query.delete()
    db.session.commit()

with app.app_context():
    delete_all_anomalies()
