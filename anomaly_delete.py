from haulage_app import db, app
from haulage_app.verification.models import Anomaly, MissingEntryAnomaly, TableName

def delete_all_anomalies():
    Anomaly.query.delete()
    db.session.commit()

def delete_all_missing_payslip_anomalies():
    MissingEntryAnomaly.query.filter(MissingEntryAnomaly.table_name == TableName.PAYSLIP).delete()
    db.session.commit()

with app.app_context():
    delete_all_missing_payslip_anomalies()
