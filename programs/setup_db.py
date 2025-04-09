# haulage_app/setup_db.py
from haulage_app import app, db

with app.app_context():
    db.create_all()
    print("Database tables created!")

# Run from the command line: 
# python setup_db.py
