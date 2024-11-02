from haulage_app.models import Day
from haulage_app import db, app
from pprint import pprint


with app.app_context():

    days = Day.query.filter(Day.status != 'working').all()
    for day in days:
        pprint(day.truck_id)
        day.truck_id = None
        pprint(day.truck_id)
    db.session.commit()

