import datetime
import json
import logging
from pprint import pprint
from sqlalchemy import desc, func
from haulage_app.models import Driver, Day, Fuel, Job, Payslip, Truck
from haulage_app.functions import query_to_dict, date_to_db, is_within_acceptable_date_range
from haulage_app import db

def detect_missing_payslips():
    pass