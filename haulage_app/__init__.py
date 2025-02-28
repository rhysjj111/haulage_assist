import os
from flask import Flask, render_template, request, session
from flask_sqlalchemy import SQLAlchemy
from haulage_app.base import Base
from haulage_app import functions as f
from flask_migrate import Migrate

if os.path.exists("env.py"):
    import env

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")

if os.environ.get("DEVELOPMENT") == "True":
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DB_URL")
else:
    uri = os.environ.get("HEROKU_POSTGRESQL_CHARCOAL_URL")
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = uri

db = SQLAlchemy(app, model_class=Base)

migrate = Migrate(app, db)

from haulage_app.api import api_bp
from haulage_app.driver import driver_bp
from haulage_app.day import day_bp
from haulage_app.truck import truck_bp
from haulage_app.job import job_bp
from haulage_app.fuel import fuel_bp
from haulage_app.payslip import payslip_bp
from haulage_app.wages_calculator import wages_calculator_bp
from haulage_app.analysis import analysis_bp
from haulage_app.expense import expense_bp
from haulage_app.week import week_bp
from haulage_app.notification import notification_bp
from haulage_app.verification import verification_bp

blueprints = [expense_bp, api_bp, driver_bp, day_bp, truck_bp, 
              job_bp, fuel_bp, payslip_bp, wages_calculator_bp,
              analysis_bp, week_bp, notification_bp, verification_bp]

for blueprint in blueprints:
    app.register_blueprint(blueprint)

from haulage_app.verification.scheduler import init_scheduler

init_scheduler(app)

from haulage_app.verification import models

# with app.app_context():
#     db.create_all()
#     print("Database tables created!")

@app.route("/")
def home():
    return render_template("entry_menu.html")

#makes functions available globally
@app.context_processor
def context_processor():
    return dict(f=f)

# stores the previous url in the session before each request
@app.before_request
def before_request():
    if not request.path.startswith('/static/') and request.endpoint != 'verification.handle_user_feedback':
        session['previous_url'] = request.url


