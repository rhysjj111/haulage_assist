from haulage_app.models import Day
from haulage_app import db, app
from pprint import pprint


with app.app_context():

    days = Day.query.all()
    # for day in days:
    #     pprint(day.status)
    #     if day.status == 'Working':
    #         day.status = 'working'
    #     pprint(day.status)
        # db.session.commit()
    for day in days:
        pprint(day.status)