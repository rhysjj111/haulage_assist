import re
from wages_calculator import db
from wages_calculator.functions import *
from sqlalchemy.orm import validates 
from sqlalchemy.ext.hybrid import hybrid_property
from flask import redirect, url_for, flash, request
from datetime import datetime



class Driver(db.Model):
    __table_args__ = (db.UniqueConstraint('first_name', 'second_name', name='_full_name_uc'),)
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, nullable=False)
    first_name = db.Column(db.String(30), nullable=False) 
    second_name = db.Column(db.String(30), nullable=False) 
    base_wage = db.Column(db.Integer, nullable=False)
    bonus_percentage = db.Column(db.Float, nullable=False)
    day_end_days = db.relationship("DayEnd", backref="driver", cascade="all, delete", lazy=True)
    
    def __repr__(self): 
        #represents itself in form of string
        return f"Driver: {self.first_name} {self.second_name}"

    @hybrid_property
    def full_name(self):
        return self.first_name + " " + self.second_name

    ##################################### validation
    @validates('start_date')
    def validate_start_date(self, key, start_date):
        try:
            start_date = datetime.strptime(start_date, "%d/%m/%Y")
        except:
            raise ValueError('Please enter date in format dd/mm/yyyy')
        return start_date

    @validates('first_name', 'second_name')
    def validate_names(self, key, field):
        if not field:
            raise ValueError('Please enter first and second name')
        if len(field) <1 or len(field)>= 25:
            raise ValueError('Please enter name(s) between 1 and 25 characters')
        #regex to make sure no special characters are present except '-' and '_'
        if bool(re.search(r'[^\w-]', field)):
            raise ValueError('Please do not inlude spaces or special characters in name(s), for double barrel names use: "-"')
        if any(character.isdigit() for character in field):
            raise ValueError('Please do not include numbers in name(s)')
        return name_to_db(field)
    
    @validates('base_wage')
    def validate_base_wage(self, key, base_wage):
        try:
            base_wage = currency_to_db(base_wage)
        except:
            raise ValueError('Please enter a base wage value between 400 and 2000')
        else:
            if not(40000 <= base_wage <= 200000):
                raise ValueError('Please enter a base wage value between 400 and 2000')
        return base_wage

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

        


class DayEnd(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    earned = db.Column(db.Integer, nullable=False)
    overnight = db.Column(db.Boolean, nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("driver.id", ondelete="CASCADE"), nullable=False)
    __table_args__ = (db.UniqueConstraint('driver_id', 'date', name='_driver_date_uc'),)

    def __repr__(self):
        #represents itself in form of string
        return f"Day end enry: {self.driver.first_name} {self.driver.second_name} ({date_to_web(self.date)})"


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
    def validate_day_end_check_for_duplicate(session, flush_context, instances):
        """
        Validation checking driver and date have not already been entered. Cannot be performed with @valdiates
        """
        for instance in session.new:
            if isinstance(instance, DayEnd):
                id = instance.id
                date = instance.date
                driver_id = instance.driver_id
                database_entry = DayEnd.query.filter(DayEnd.date == date, DayEnd.driver_id == driver_id).first()
                if database_entry is not None and database_entry.id != id:
                    raise ValueError('This date already has an entry for the driver selected. Edit the entry or select another date')







    

