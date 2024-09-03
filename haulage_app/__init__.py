
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
# from flask_migrate import Migrate




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

db = SQLAlchemy(app)
from haulage_app.api import api_bp
from haulage_app.drivers import drivers_bp
from haulage_app.days import days_bp
from haulage_app.trucks import trucks_bp
from haulage_app.jobs import jobs_bp
from haulage_app.fuel import fuel_bp
from haulage_app.payslips import payslips_bp
from haulage_app.wages_calculator import wages_calculator_bp

blueprints = [api_bp, drivers_bp, days_bp, trucks_bp, jobs_bp, fuel_bp, payslips_bp, wages_calculator_bp]

for blueprint in blueprints:
    app.register_blueprint(blueprint)


from haulage_app import routes 
