from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from haulage_app.verification.checks import verification_functions

def init_scheduler(app):
    scheduler = BackgroundScheduler()
    
    # Schedule verification check every Wednesday at 12pm
    scheduler.add_job(
        func=verification_functions.test,
        trigger=CronTrigger(day_of_week='wed', hour=12),
        # trigger=CronTrigger(minute='*/1'),
        id='weekly_verification',
        name='Run weekly verification checks',
        replace_existing=True
    )
    
    scheduler.start()
