from haulage_app.models import Day
from haulage_app import db, app
from pprint import pprint


with app.app_context():

    days = Day.query.filter(Day.status != 'working').all()
    for day in days:
        day.truck_id = None
    db.session.commit()

