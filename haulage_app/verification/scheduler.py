from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from haulage_app.verification.checks import verification_manager
from flask import current_app

def init_scheduler(app):
    scheduler = BackgroundScheduler()
    
    def run_verification():
        with app.app_context():
            verification_manager.payslip_check()
            verification_manager.day_check()
            verification_manager.fuel_check()
            verification_manager.mileage_check()
    
    scheduler.add_job(
        func=run_verification,
        # trigger=CronTrigger(day_of_week='fri', hour=13,minute=50),
        # trigger=CronTrigger(hour='11-14'),
        trigger=CronTrigger(minute='*'),
        # trigger=CronTrigger(second='*/30'),
        id='weekly_verification',
        name='Run weekly verification checks',
        replace_existing=True
    )
    
    scheduler.start()
    # pass
