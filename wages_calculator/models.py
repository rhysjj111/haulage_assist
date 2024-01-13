import re
from wages_calculator import db
from wages_calculator.functions import *
from sqlalchemy.orm import validates 
from sqlalchemy.ext.hybrid import hybrid_property
from flask import redirect, url_for, flash, request
from datetime import datetime

def preferred_truck(context):
    return context.get_current_parameters()['driver.truck_id']

class Driver(db.Model):
    __table_args__ = (db.UniqueConstraint('first_name', 'last_name', name='_full_name_uc'),)
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    first_name = db.Column(db.String(20), nullable=False) 
    last_name = db.Column(db.String(20), nullable=False) 
    basic_wage = db.Column(db.Integer, nullable=False)
    daily_bonus_threshold = db.Column(db.Integer, nullable=False)
    daily_bonus_percentage = db.Column(db.Float, nullable=False)
    weekly_bonus_threshold = db.Column(db.Integer, nullable=False)
    weekly_bonus_percentage = db.Column(db.Float, nullable=False)
    overnight_value = db.Column(db.Integer, nullable=False)
    truck_id = db.Column(db.Integer, db.ForeignKey("truck.id"))
    days = db.relationship("Day", back_populates="driver", cascade="all, delete", lazy=True)
    payslips = db.relationship("Payslip", back_populates="driver", cascade="all, delete", lazy=True)
    
    def __repr__(self): 
        #represents itself in form of string
        return f"Driver: {self.first_name} {self.last_name}"

    @hybrid_property
    def full_name(self):
        return self.first_name + " " + self.last_name

    ##################################### validation
    @validates('start_date')
    def validate_start_date(self, key, start_date):
        try:
            start_date = datetime.strptime(start_date, "%d/%m/%Y")
        except:
            raise ValueError('Please enter date in format dd/mm/yyyy')
        return start_date

    @validates('first_name', 'last_name')
    def validate_names(self, key, field):
        if not field:
            raise ValueError('Please enter first and last name')
        if len(field) <1 or len(field)>= 25:
            raise ValueError('Please enter name(s) between 1 and 25 characters')
        #regex to make sure no special characters are present except '-' and '_'
        if bool(re.search(r'[^\w-]', field)):
            raise ValueError('Please do not inlude spaces or special characters in name(s), for double barrel names use: "-"')
        if any(character.isdigit() for character in field):
            raise ValueError('Please do not include numbers in name(s)')
        return name_to_db(field)
    
    @validates('basic_wage')
    def validate_basic_wage(self, key, basic_wage):
        try:
            basic_wage = currency_to_db(basic_wage)
        except:
            raise ValueError('Please enter a basic wage value between 400 and 2000')
        else:
            if not(40000 <= basic_wage <= 200000):
                raise ValueError('Please enter a basic wage value between 400 and 2000')
        return basic_wage

    @validates('bonus_percentage')
    def validate_bonus_percentage(self, key, bonus_percentage):
        try:
            bonus_percentage = percentage_to_db(bonus_percentage)
        except:
            raise ValueError('Please enter a bonus percentage value between 15 and 50')
        else:
            if not (0.15 <= bonus_percentage <= 0.5):
                raise ValueError('Please enter a bonus percentage value between 15 and 50')
        return bonus_percentage
    
    @db.event.listens_for(db.session, 'before_flush')
    def validate_full_name(session, flush_context, instances):
        """
        Validation checking Driver full name does not already exist. Cannot be performed with @valdiates
        """
        for instance in session.new:
            if isinstance(instance, Driver):
                full_name = instance.full_name
                database_entry = Driver.query.filter(Driver.full_name == full_name).first()
                if database_entry is not None:
                    raise ValueError('Driver already exists in the database, please choose another name or edit/delete current driver to replace.')


class Truck (db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    registration = db.Column(db.String(8), nullable=False, unique=True)
    make = db.Column(db.String(15), nullable=False)
    model = db.Column(db.String(15), nullable=False)

    fuel_entries = db.relationship("Fuel", back_populates="truck", lazy=True)
    days = db.relationship("Day", back_populates="truck", cascade="all, delete", lazy=True)

    def __repr__(self): 
    #represents itself in form of string
        return f"{self.make} {self.model} with registration: {self.registration}"


class Day(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("driver.id", ondelete="CASCADE"), nullable=False)
    status = db.Column(db.String(15), nullable=False, default="Working")
    additional_earned = db.Column(db.Integer, nullable=False, default=0)
    additional_wages = db.Column(db.Integer, nullable=False, default=0)
    overnight = db.Column(db.Boolean, nullable=False, default=True)
    truck_id = db.Column(db.Integer, db.ForeignKey("truck.id", ondelete="CASCADE"), nullable=False, default=preferred_truck)  
    start_mileage = db.Column(db.Integer)
    end_mileage = db.Column(db.Integer)
    __table_args__ = (db.UniqueConstraint('driver_id', 'date', name='_driver_date_uc'),)
    driver = db.relationship("Driver", back_populates="days", lazy=True)
    truck = db.relationship("Truck", back_populates="days")
    jobs = db.relationship("Job", back_populates="day", cascade="all, delete", lazy=True)

    def __repr__(self):
        #represents itself in form of string
        return f"Day entry: {self.driver.first_name} {self.driver.last_name} ({date_to_web(self.date)})"

    ############ validation
    @validates('driver_id')
    def validate_select_driver(self, key, driver_id):
        if not (Driver.query.filter(Driver.id == driver_id).first()):
            raise ValueError('Selection not available in database. Please select a driver')
        return driver_id
    
    @validates('date')
    def validate_start_date(self, key, date):
        try:
            date = date_to_db(date)
        except:
            raise ValueError('Please enter date in format dd/mm/yyyy')
        
        return date
    
    @validates('earned')
    def validate_earned(self, key, earned):
        try:
            earned = currency_to_db(earned)
        except:
            raise ValueError('Please enter a value earned between 1 and 2000')
        else:
            if not(100 < earned < 200000):
                raise ValueError('Please enter a value earned between 1 and 2000')
        return earned

    @validates('overnight')
    def validate_overnight(self, key, overnight):
        if overnight == 'on':
            overnight = True
        elif overnight is None:
            overnight = False
        else:
            raise ValueError('Please use the selector to indicate whether overnight is present')
        return overnight

    @db.event.listens_for(db.session, 'before_flush')
    def validate_day_check_for_duplicate(session, flush_context, instances):
        """
        Validation checking driver and date have not already been entered. Cannot be performed with @valdiates
        """
        for instance in session.new:
            if isinstance(instance, Day):
                id = instance.id
                date = instance.date
                driver_id = instance.driver_id
                database_entry = Day.query.filter(Day.date == date, Day.driver_id == driver_id).first()
                if database_entry is not None and database_entry.id != id:
                    raise ValueError('This date already has an entry for the driver selected. Edit the entry or select another date')


class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    day_id = db.Column(db.Integer, db.ForeignKey("day.id", ondelete="CASCADE"), nullable=False)
    earned = db.Column(db.Integer, nullable=False)
    collection = db.Column(db.String(20), nullable=False) 
    delivery = db.Column(db.String(20), nullable=False) 
    notes = db.Column(db.String(15)) 
    split = db.Column(db.Boolean, nullable=False, default=False)

    day = db.relationship("Day", back_populates="jobs")

    def __repr__(self): 
    #represents itself in form of string
        return f"Job from: {self.collection} to: {self.delivery} completed by:{self.day.driver.first_name} on {self.day.date}"


class Payslip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)

    date = db.Column(db.Date, nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("driver.id"), nullable=False)
    total_wage = db.Column(db.Integer, nullable=False)
    total_cost_to_employer = db.Column(db.Integer, nullable=False)

    driver = db.relationship("Driver", back_populates="payslips")

    def __repr__(self): 
    #represents itself in form of string
        return f"Payslip for: {self.driver.full_name} on {self.date}"


class Fuel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    date = db.Column(db.Date, nullable=False)
    truck_id = db.Column(db.Integer, db.ForeignKey("truck.id"), nullable=False)
    fuel_card_name = db.Column(db.String(20), nullable=False)    
    fuel_volume = db.Column(db.Integer, nullable=False)
    fuel_cost = db.Column(db.Integer, nullable=False)

    truck = db.relationship("Truck", back_populates="fuel_entries")

    def __repr__(self): 
    #represents itself in form of string
        return f"Fuel entry for: {self.truck.registration} on {self.date}"




class RunningCosts (db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    year = db.Column(db.Date, nullable=False)
    office_staff = db.Column(db.Integer, nullable=False)
    truck_finance =  db.Column(db.Integer, nullable=False)
    goods_in_transit =  db.Column(db.Integer, nullable=False)
    truck_maintenance =  db.Column(db.Integer, nullable=False)

    def __repr__(self): 
    #represents itself in form of string
        return f"Running costs for year: {self.year}"




        











    

