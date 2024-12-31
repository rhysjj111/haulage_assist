from haulage_app import app
from haulage_app import db
from haulage_app.verification.models import (
    AiRawResponse,
    AiProcessedResponse,
    MissingEntrySuggestion,
    DayAnomalySuggestion,
    JobAnomalySuggestion,
    FuelAnomalySuggestion,
    PayslipAnomalySuggestion,
    AiResponseUserFeedback,
)

def drop_tables():
    """
    Drops the specified tables from the database.
    """
    try:
        # Drop the tables in the correct order to avoid foreign key constraint issues
        AiResponseUserFeedback.__table__.drop(db.engine)
        MissingEntrySuggestion.__table__.drop(db.engine)
        DayAnomalySuggestion.__table__.drop(db.engine)
        JobAnomalySuggestion.__table__.drop(db.engine)
        FuelAnomalySuggestion.__table__.drop(db.engine)
        PayslipAnomalySuggestion.__table__.drop(db.engine)
        AiProcessedResponse.__table__.drop(db.engine)
        AiRawResponse.__table__.drop(db.engine)

        db.session.commit()
        print("Tables dropped successfully.")
    except Exception as e:
        db.session.rollback()
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    # Create an application context 
    # An application context is required for Flask-SQLAlchemy to work correctly.
    # It sets up the environment for the application and provides access to the database.
    with app.app_context():
        drop_tables()