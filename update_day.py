from haulage_app.models import Day
from haulage_app import db, app
from pprint import pprint


with app.app_context():

    days = Day.query.filter(Day.status == 'working').all()
    for day in days:
        if day.driver_id == 1:
            print(day.truck_id)
            day.truck_id = 3
            print(day.truck_id)
    # db.session.commit()

