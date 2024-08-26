import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

if os.path.exists("env.py"):
    import env

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")


# if os.environ.get("DEVELOPMENT") == "True":
#     app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DB_URL")
# else:
uri = os.environ.get("HEROKU_POSTGRESQL_CHARCOAL_URL")
if uri.startswith("postgres://"):
    print(uri)
    uri = uri.replace("postgres://", "postgresql://", 1)
    print(uri)
app.config["SQLALCHEMY_DATABASE_URI"] = uri

db = SQLAlchemy(app)

migrate = Migrate(app, db)

from wages_calculator import routes 
