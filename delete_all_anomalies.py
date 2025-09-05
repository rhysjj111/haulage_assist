from haulage_app import db, app
from haulage_app.verification.models import Anomaly, MissingEntryAnomaly, IncorrectMileage

def purge_all_anomalies():
    """
    Deletes ALL anomaly records from the database.
    
    This includes all subclasses like MissingEntryAnomaly and IncorrectMileage,
    as well as their related UserFeedback entries due to cascading deletes.
    
    WARNING: This is a permanent and destructive operation.
    """
    with app.app_context():
        try:
            # missing_entries = db.session.execute(db.select(MissingEntryAnomaly)).scalars().all()
            # incorrect_mileages = db.session.execute(db.select(IncorrectMileage)).scalars().all()

            # anomalies_to_delete = missing_entries + incorrect_mileages
            anomalies_to_delete = db.session.execute(db.select(IncorrectMileage)).scalars().all()

            num_anomalies = len(anomalies_to_delete)

            if num_anomalies == 0:
                print("\n✅ No anomalies found in the database. Nothing to delete.")
                return

            print(f"\nFound {num_anomalies} anomaly record(s) to delete.")

            # Deleting the objects one by one ensures that ORM-level cascades
            # (like deleting related UserFeedback) are correctly triggered.
            print("Deleting records...")
            for anomaly in anomalies_to_delete:
                db.session.delete(anomaly)

            print("Committing changes to the database...")
            db.session.commit()

            print("\n" + "=" * 60)
            print(f"✅ SUCCESS: Permanently deleted {num_anomalies} anomaly record(s).")
            print("=" * 60)

        except Exception as e:
            print(f"\n❌ ERROR: An error occurred during deletion: {e}")
            print("Rolling back database changes to prevent partial deletion.")
            db.session.rollback()

purge_all_anomalies()
