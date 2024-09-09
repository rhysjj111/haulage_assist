import re
from haulage_app import db
from haulage_app.functions import *
from sqlalchemy.orm import validates 
from sqlalchemy.ext.hybrid import hybrid_property
from flask import redirect, url_for, flash, request
from datetime import datetime


class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    first_name = db.Column(db.String(50), nullable=False) 
    last_name = db.Column(db.String(50), nullable=False) 
    basic_wage = db.Column(db.Integer, nullable=False)
    daily_bonus_threshold = db.Column(db.Integer, nullable=False)
    daily_bonus_percentage = db.Column(db.Float, nullable=False)
    weekly_bonus_threshold = db.Column(db.Integer, nullable=False)
    weekly_bonus_percentage = db.Column(db.Float, nullable=False)
    overnight_value = db.Column(db.Integer, nullable=False)

    __table_args__ = (db.UniqueConstraint('first_name', 'last_name', name='_full_name_uc'),)
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
            raise ValueError('Please enter a basic wage value between £400 and £2000')
        else:
            if not(40000 <= basic_wage <= 200000):
                raise ValueError('Please enter a basic wage value between £400 and £2000')
        return basic_wage

    @validates('daily_bonus_threshold')
    def validate_daily_bonus_threshold(self, key, daily_bonus_threshold):
        try:
            daily_bonus_threshold = currency_to_db(daily_bonus_threshold)
        except:
            raise ValueError('Please enter a daily bonus threshold value between £300.00 and £450.00')
        else:
            if not(30000 <= daily_bonus_threshold <= 45000):
                raise ValueError('Please enter a daily bonus threshold value between £300.00 and £450.00')
        return daily_bonus_threshold

    @validates('daily_bonus_percentage')
    def validate_daily_bonus_percentage(self, key, daily_bonus_percentage):
        try:
            daily_bonus_percentage = percentage_to_db(daily_bonus_percentage)
        except:
            raise ValueError('Please enter a daily bonus percentage value between 20.00% and 50.00%')
        else:
            if not(0.2 <= daily_bonus_percentage <= 0.5):
                raise ValueError('Please enter a daily bonus percentage value between 20.00% and 50.00%')
        return daily_bonus_percentage

    @validates('weekly_bonus_threshold')
    def validate_weekly_bonus_threshold(self, key, weekly_bonus_threshold):
        try:
            weekly_bonus_threshold = currency_to_db(weekly_bonus_threshold)
        except:
            raise ValueError('Please enter a weekly bonus threshold value between £2,200.00 and £3,000.00')
        else:
            if not(220000 <= weekly_bonus_threshold <= 300000):
                raise ValueError('Please enter a weekly bonus threshold value between £2,200.00 and £3,000.00')
        return weekly_bonus_threshold

    @validates('weekly_bonus_percentage')
    def validate_weekly_bonus_percentage(self, key, weekly_bonus_percentage):
        try:
            weekly_bonus_percentage = percentage_to_db(weekly_bonus_percentage)
        except:
            raise ValueError('Please enter a weekly bonus percentage value between 10.00% and 35.00%')
        else:
            if not(0.1 <= weekly_bonus_percentage <= 0.35):
                raise ValueError('Please enter a weekly bonus percentage value between 10.00% and 35.00%')
        return weekly_bonus_percentage

    @validates('overnight_value')
    def validate_overnight_value(self, key, overnight_value):
        try:
            overnight_value = currency_to_db(overnight_value)
        except:
            raise ValueError('Please enter an overnight value between £10.00 and £50.00')
        else:
            if not(1000 <= overnight_value <= 5000):
                raise ValueError('Please enter an overnight value between £10.00 and £50.00')
        return overnight_value
    
    @db.event.listens_for(db.session, 'before_flush')
    def validate_full_name(session, flush_context, instances):
        """
        Validation checking Driver full name does not already exist. Cannot be performed with @valdiates
        """
        for instance in session.new:
            if isinstance(instance, Driver):
                id = instance.id
                full_name = instance.full_name
                database_entry = Driver.query.filter(Driver.full_name == full_name).first()
                if database_entry is not None and database_entry.id != id:
                    raise ValueError('Driver already exists in the database, please choose another name or edit/delete current driver to replace.')


class Truck (db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    registration = db.Column(db.String(8), nullable=False, unique=True, index=True)
    make = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)

    fuel_entries = db.relationship("Fuel", back_populates="truck", lazy=True)
    days = db.relationship("Day", back_populates="truck", cascade="all, delete", lazy=True)

    def __repr__(self): 
    #represents itself in form of string
        return f"{self.make} {self.model} with registration: {self.registration}"

    @validates('registration')
    def validate_names(self, key, registration):
        if not registration:
            raise ValueError('Please enter a registration in the format "XX00 XXX"')
        if len(registration) != 8:
            raise ValueError('Please enter a registration in the format "XX00 XXX"')
        #regex to make sure no special characters are present except '-' and '_'
        if bool(re.search(r'/\b[a-z]{2}([1-9]|0[2-9]|6[0-9]|1[0-9])[a-z]{3}\b/i ', registration)):
            raise ValueError('Please enter a registration in the format "XX00 XXX"')
        return registration.upper()


class Day(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey("driver.id", ondelete="CASCADE"), nullable=False, index=True)
    truck_id = db.Column(db.Integer, db.ForeignKey("truck.id", ondelete="CASCADE"), nullable=False, index=True)  
    status = db.Column(db.String(50), nullable=False, default="Working")
    overnight = db.Column(db.Boolean, nullable=False)
    fuel = db.Column(db.Boolean, default=True)
    test= db.Column(db.Boolean)
    start_mileage = db.Column(db.Integer, nullable=False, default = 0)
    end_mileage = db.Column(db.Integer, nullable=False, default = 0)
    additional_earned = db.Column(db.Integer, nullable=False, default=0)
    additional_wages = db.Column(db.Integer, nullable=False, default=0)
    
    __table_args__ = (db.UniqueConstraint('driver_id', 'date', name='_driver_date_uc'),)
    driver = db.relationship("Driver", back_populates="days", lazy=True)
    truck = db.relationship("Truck", back_populates="days")
    jobs = db.relationship("Job", back_populates="day", cascade="all, delete", lazy=True)

    def __repr__(self):
        #represents itself in form of string
        return f"Day entry: {self.driver.full_name} {display_date(self.date)}"

    def calculate_total_earned(self):
        """
        Calculate the total earned for the day by summing the 'earned' column of each associated Job entry.
        """
        total_earned = 0
        for job in self.jobs:
            total_earned += job.earned
        return total_earned

    def calculate_daily_bonus(self, driver):
        """
        Calculate the daily bonus based on the driver's settings.
        """
        daily_total_earned = self.calculate_total_earned()
        if daily_total_earned > driver.daily_bonus_threshold:
            return int((daily_total_earned - driver.daily_bonus_threshold) * driver.daily_bonus_percentage)
        else:
            return 0

    ############ validation
    
    @validates('date')
    def validate_start_date(self, key, date):
        try:
            date = date_to_db(date)
        except:
            raise ValueError('Please enter date in format dd/mm/yyyy')
        return date

    @validates('driver_id')
    def validate_select_driver(self, key, driver_id):
        if not (Driver.query.filter(Driver.id == driver_id).first()):
            raise ValueError('Selection not available in database. Please select a driver')
        return driver_id

    @validates('truck_id')
    def validate_select_driver(self, key, truck_id):
        if not (Truck.query.filter(Truck.id == truck_id).first()):
            raise ValueError('Selection not available in database. Please select a truck')
        return truck_id
    
    @validates('additional_earned', 'additional_wages')
    def validate_additional(self, key, field):
        try:
            field = currency_to_db(field)
        except:
            raise ValueError('Please enter a value earned between £0 and £2000')
        else:
            if not(0 <= field < 200000):
                raise ValueError('Please enter a value earned between £0 and £2000')
        return field
    
    @validates('start_mileage', 'end_mileage')
    def validate_mileage(self, key, field):
        try:
            field = currency_to_db(field)
        except:
            raise ValueError('Please enter a value earned between 0 and 1,000,000')
        else:
            if not(0 <= field < 100000000):
                raise ValueError('Please enter a value earned between 0 and 1,000,000')
        return field

    @validates('overnight', 'fuel')
    def validate_boolean_field(self, key, value):
        if value == 'on':
            return True
        elif value is None:
            return False
        else:
            raise ValueError(f'Invalid value for {key}. Please use the selector.')


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
    day_id = db.Column(db.Integer, db.ForeignKey("day.id", ondelete="CASCADE"), nullable=False, index=True)
    earned = db.Column(db.Integer, nullable=False)
    collection = db.Column(db.String(50), nullable=False) 
    delivery = db.Column(db.String(50), nullable=False) 
    notes = db.Column(db.String(50)) 
    split = db.Column(db.Boolean, default=False)

    day = db.relationship("Day", back_populates="jobs")

    def __repr__(self): 
    #represents itself in form of string
        return f"Job entry: {display_date(self.day.date)} {self.day.driver.full_name} - {format_currency(display_currency(self.earned))} "


    @validates('collection', 'delivery')
    def validate_names(self, key, field):
        if not field:
            raise ValueError('Please enter a collection and delivery')
        if len(field) <1 or len(field)>= 25:
            raise ValueError('Please enter a collection and delivery between 1 and 25 characters')
        if any(character.isdigit() for character in field):
            raise ValueError('Please do not include numbers in name(s)')
        return name_to_db(field)

    @validates('earned')
    def validate_earned(self, key, earned):
        try:
            earned = currency_to_db(earned)
        except:
            raise ValueError('Please enter a value earned between £1 and £2000')
        else:
            if not(100 < earned < 200000):
                raise ValueError('Please enter a value earned between £1 and £2000')
        return earned

    @validates('split')
    def validate_boolean_field(self, key, value):
        if value == 'on':
            return True
        elif value is None:
            return False
        else:
            raise ValueError(f'Invalid value for {key}. Please use the selector.')
    # @validates('split')
    # def validate_split(self, key, split):
    #     if split == 'on':
    #         split = True
    #     elif split is None or split == "":
    #         split = False
    #     else:
    #         raise ValueError('Please use the selector to indicate whether split is present')
    #     return split
    



class Payslip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)

    date = db.Column(db.Date, nullable=False, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey("driver.id"), nullable=False, index=True)
    total_wage = db.Column(db.Integer, nullable=False)
    total_cost_to_employer = db.Column(db.Integer, nullable=False)

    driver = db.relationship("Driver", back_populates="payslips")
    __table_args__ = (db.UniqueConstraint('driver_id', 'date', name='_driver_date_ps_uc'),)

    def __repr__(self): 
    #represents itself in form of string
        return f"Payslip for: {self.driver.full_name} on {self.date}"

    @validates('date')
    def validate_start_date(self, key, date):
        try:
            date = date_to_db(date)
        except:
            raise ValueError('Please enter date in format dd/mm/yyyy')
        return date

    @validates('total_wage', 'total_cost_to_employer')
    def validate_earned(self, key, field):
        try:
            field = currency_to_db(field)
        except:
            raise ValueError('Please enter a value earned between £1 and £3000')
        else:
            if not(100 < field < 300000):
                raise ValueError('Please enter a value earned between £1 and £3000')
        return field    



class Fuel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    date = db.Column(db.Date, nullable=False, index=True)
    truck_id = db.Column(db.Integer, db.ForeignKey("truck.id"), nullable=False, index=True)
    fuel_card_name = db.Column(db.String(50), nullable=False, index=True)    
    fuel_volume = db.Column(db.Integer, nullable=False)
    fuel_cost = db.Column(db.Integer, nullable=False)

    truck = db.relationship("Truck", back_populates="fuel_entries")

    def __repr__(self): 
    #represents itself in form of string
        return f"Fuel entry for: {self.truck.registration} on {self.date}"

    @validates('date')
    def validate_start_date(self, key, date):
        try:
            date = date_to_db(date)
        except:
            raise ValueError('Please enter date in format dd/mm/yyyy')
        return date    

    @validates('fuel_volume')
    def validate_fuel_volume(self, key, fuel_volume):
        try:
            fuel_volume = currency_to_db(fuel_volume)
        except:
            raise ValueError('Please enter a volume between 1.00L and 1000.00L')
        else:
            if not(100 < fuel_volume < 100000):
                raise ValueError('Please enter a volume between 1.00L and 1000.00L')
        return fuel_volume  

    @validates('fuel_cost')
    def validate_earned(self, key, fuel_cost):
        try:
            fuel_cost = currency_to_db(fuel_cost)
        except:
            raise ValueError('Please enter a value between £1.00 and £1500.00')
        else:
            if not(100 < fuel_cost < 150000):
                raise ValueError('Please enter a value between £1.00 and £1500.00')
        return fuel_cost  




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




        











    

