import re
import datetime
import enum
from haulage_app import db
from haulage_app.base import Base
from haulage_app.functions import *
from typing_extensions import Annotated
from typing import List, Optional
from sqlalchemy.orm import validates, Mapped, mapped_column, relationship
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import String, ForeignKey, Integer, DateTime, Date, func, Computed

str50 = Annotated[str, mapped_column(String(50))]
tstamp = Annotated[datetime.datetime, mapped_column(DateTime, server_default=func.now(), nullable=True)]
date = Annotated[datetime.date, mapped_column(Date, index=True)]
intpk = Annotated[int, mapped_column(primary_key=True)]
driverfk = Annotated[int, mapped_column(ForeignKey("driver.id"), index=True)]
driverfk_restrict = Annotated[int, mapped_column(ForeignKey("driver.id", ondelete="RESTRICT"), index=True)]
truckfk = Annotated[int, mapped_column(ForeignKey("truck.id"), index=True)]
truckfk_cascade = Annotated[int, mapped_column(ForeignKey("truck.id", ondelete="CASCADE"), index=True)]
truckfk_restrict = Annotated[int, mapped_column(ForeignKey("truck.id", ondelete="RESTRICT"), index=True)]
dayfk = Annotated[int, mapped_column(ForeignKey("day.id"), index=True)]
dayfk_cascade = Annotated[int, mapped_column(ForeignKey("day.id", ondelete="CASCADE"), index=True)]
dayfk_restrict = Annotated[int, mapped_column(ForeignKey("day.id", ondelete="RESTRICT"), index=True)]
expensefk_cascade = Annotated[int, mapped_column(ForeignKey("expense.id", ondelete="CASCADE"), index=True)]
week_number_computed = Annotated[int, mapped_column(
    Computed("((EXTRACT(DOW FROM date) + EXTRACT(week FROM date) * 7 - 6) / 7)::integer"),
    index=True
)]

class EmploymentStatus(enum.Enum):
    ACTIVE = 'active'
    INACTIVE = 'terminated'


class Driver(db.Model):
    id: Mapped[intpk]
    timestamp: Mapped[tstamp]
    first_name: Mapped[str50] 
    last_name: Mapped[str50] 
    basic_wage: Mapped[int]
    daily_bonus_threshold: Mapped[int]
    daily_bonus_percentage: Mapped[float]
    weekly_bonus_threshold: Mapped[int]
    weekly_bonus_percentage: Mapped[float]
    overnight_value: Mapped[int]
    truck_id: Mapped[Optional[truckfk]]

    __table_args__ = (db.UniqueConstraint('first_name', 'last_name', name='_full_name_uc'),)

    employment_history: Mapped[List["DriverEmploymentHistory"]] = relationship(back_populates="driver", lazy=True, order_by="DriverEmploymentHistory.start_date.desc()")
    days: Mapped[List["Day"]] = relationship(back_populates="driver", lazy=True)
    payslips: Mapped[List["Payslip"]] = relationship(back_populates="driver", lazy=True)
    
    def __repr__(self): 
        #represents itself in form of string
        return f"Driver: {self.first_name} {self.last_name}"
        
    @hybrid_property
    def current_employment(self):
        """Returns the current active employment record"""
        return DriverEmploymentHistory.query.filter(
            DriverEmploymentHistory.driver_id == self.id,
            DriverEmploymentHistory.end_date.is_(None)
        ).first()

    @hybrid_property
    def is_currently_employed(self):
        """Returns True if driver has an active employment record"""
        return self.current_employment is not None

    def get_employment_on_date(self, check_date):
        """Returns employment record active on a specific date"""
        return DriverEmploymentHistory.query.filter(
            DriverEmploymentHistory.driver_id == self.id,
            DriverEmploymentHistory.start_date <= check_date,
            db.or_(
                DriverEmploymentHistory.end_date.is_(None),
                DriverEmploymentHistory.end_date >= check_date
            )
        ).first()

    def terminate_employment(self, end_date):
        """Helper method to terminate current employment"""
        current_record = self.current_employment
        if current_record:
            current_record.end_date = end_date
            current_record.employment_status = EmploymentStatus.TERMINATED  # Use enum value
            db.session.commit()
            return current_record
        return None


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
            basic_wage = float_to_db(basic_wage)
        except:
            raise ValueError('Please enter a basic wage value between £400 and £2000')
        else:
            if not(40000 <= basic_wage <= 200000):
                raise ValueError('Please enter a basic wage value between £400 and £2000')
        return basic_wage

    @validates('daily_bonus_threshold')
    def validate_daily_bonus_threshold(self, key, daily_bonus_threshold):
        try:
            daily_bonus_threshold = float_to_db(daily_bonus_threshold)
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
            weekly_bonus_threshold = float_to_db(weekly_bonus_threshold)
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
            overnight_value = float_to_db(overnight_value)
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


class DriverEmploymentHistory(db.Model):
    id: Mapped[intpk]
    timestamp: Mapped[tstamp]
    driver_id: Mapped[driverfk_restrict]
    start_date: Mapped[date]
    end_date: Mapped[Optional[date]]
    employment_status: Mapped[EmploymentStatus] = mapped_column(default=EmploymentStatus.ACTIVE)
    
    __table_args__ = (
        db.CheckConstraint('end_date IS NULL OR end_date > start_date', name='valid_employment_period'),
        db.Index('idx_driver_employment_dates', 'driver_id', 'start_date', 'end_date'),
    )

    driver: Mapped["Driver"] = relationship(back_populates="employment_history")

    def __repr__(self):
        status = "Current" if self.end_date is None else f"Ended {display_date(self.end_date)}"
        return f"Employment: {self.driver.full_name} - Started {display_date(self.start_date)} - {status}"

    @hybrid_property
    def is_current_employment(self):
        return self.end_date is None

    @hybrid_property
    def employment_duration_days(self):
        end = self.end_date or datetime.date.today()
        return (end - self.start_date).days

    def calculate_employment_duration_readable(self):
        """Returns employment duration in a human-readable format"""
        days = self.employment_duration_days
        years = days // 365
        remaining_days = days % 365
        months = remaining_days // 30
        remaining_days = remaining_days % 30
        
        parts = []
        if years > 0:
            parts.append(f"{years} year{'s' if years != 1 else ''}")
        if months > 0:
            parts.append(f"{months} month{'s' if months != 1 else ''}")
        if remaining_days > 0 or not parts:
            parts.append(f"{remaining_days} day{'s' if remaining_days != 1 else ''}")
        
        return ", ".join(parts)

    ##################################### validation

    @validates('start_date')
    def validate_start_date(self, key, start_date):
        try:
            start_date = date_to_db(start_date)
        except:
            raise ValueError('Please enter start date in format dd/mm/yyyy')
        return start_date

    @validates('end_date')
    def validate_end_date(self, key, end_date):
        if end_date is None or end_date == "":
            return None
        try:
            end_date = date_to_db(end_date)
        except:
            raise ValueError('Please enter end date in format dd/mm/yyyy')
        else:
            if hasattr(self, 'start_date') and self.start_date and end_date <= self.start_date:
                raise ValueError("End date must be after start date")
        return end_date

    @validates('driver_id')
    def validate_driver_exists(self, key, driver_id):
        if not Driver.query.filter(Driver.id == driver_id).first():
            raise ValueError('Selected driver does not exist in database')
        return driver_id

    @db.event.listens_for(db.session, 'before_flush')
    def validate_no_overlapping_employment(session, flush_context, instances):
        """
        Validation to ensure no overlapping employment periods for the same driver
        """
        for instance in session.new | session.dirty:
            if isinstance(instance, DriverEmploymentHistory):
                driver_id = instance.driver_id
                start_date = instance.start_date
                end_date = instance.end_date
                current_id = instance.id

                # Query for overlapping employment periods
                query = DriverEmploymentHistory.query.filter(
                    DriverEmploymentHistory.driver_id == driver_id,
                    DriverEmploymentHistory.id != current_id
                )

                for existing in query.all():
                    existing_start = existing.start_date
                    existing_end = existing.end_date

                    # Check for overlap
                    # Case 1: The existing record is an active, open-ended employment.
                    if existing_end is None:
                        # You cannot add another active (open-ended) employment.
                        if end_date is None:
                            raise ValueError('Driver already has an active employment period.')
                        # A new, historical period must end BEFORE the active one starts.
                        if end_date >= existing_start:
                            raise ValueError('Employment period overlaps with the start of the current active period.')
                    
                    # Case 2: The existing record is a completed employment.
                    else:  
                        # If the new record is an active employment, it must start AFTER the existing one ended.
                        if end_date is None:
                            if start_date <= existing_end:
                                raise ValueError('New active employment cannot start before a previous one has ended.')
                        # If both are completed periods, their date ranges cannot overlap.
                        else:
                            # They overlap if the new one doesn't end before the existing one starts,
                            # AND the new one doesn't start after the existing one ends.
                            if not (end_date < existing_start or start_date > existing_end):
                                raise ValueError('Employment period overlaps with an existing employment period.')



class Truck(db.Model):
    id: Mapped[intpk]
    timestamp: Mapped[tstamp]
    registration: Mapped[str] = mapped_column(String(8), nullable=False, unique=True, index=True)
    make: Mapped[str50]
    model: Mapped[str50]

    fuel_entries: Mapped[List["Fuel"]] = relationship(back_populates="truck", lazy=True)
    days: Mapped[List["Day"]] = relationship(back_populates="truck", lazy=True)

    # formatted_anomaly = db.relationship("FormattedAnomaly", back_populates="truck", uselist=False, lazy=True)

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
    id: Mapped[intpk]
    timestamp: Mapped[tstamp]
    date: Mapped[date]
    driver_id: Mapped[driverfk_restrict]
    truck_id: Mapped[Optional[truckfk_restrict]]
    status: Mapped[str50] = mapped_column(nullable=False, default="working")
    overnight: Mapped[bool] = mapped_column(default=False)
    fuel: Mapped[bool] = mapped_column(default=False)
    start_mileage: Mapped[int] = mapped_column(default=0)
    end_mileage: Mapped[int] = mapped_column(default=0)
    additional_earned: Mapped[int] = mapped_column(default=0)
    additional_wages: Mapped[int] = mapped_column(default=0)
    
    __table_args__ = (db.UniqueConstraint('driver_id', 'date', name='_driver_date_uc'),)

    driver: Mapped["Driver"] = relationship(back_populates="days")
    truck: Mapped["Truck"] = relationship(back_populates="days")
    jobs: Mapped[List["Job"]] = relationship(back_populates="day", lazy=True)
    fuel_entries: Mapped[List["Fuel"]] = relationship(back_populates="day", lazy=True)
    payslip_entries: Mapped[List["Payslip"]] = relationship(back_populates="day", lazy=True)
    
    def __repr__(self):
        #represents itself in form of string
        return f"Day entry: {self.driver.full_name} {display_date(self.date)}"

    @hybrid_property
    def get_week_number(self):
        return get_week_number_sat_to_fri(self.date)

    def calculate_total_earned(self):
        """
        Calculate the total earned for the day by summing the 'earned' column of each associated Job entry.
        """
        total_earned = 0
        for job in self.jobs:
            total_earned += job.earned
        total_earned += self.additional_earned
        return total_earned

    def calculate_daily_bonus(self, driver):
        """
        Calculate the daily bonus based on the driver's settings.
        """
        daily_total_earned = self.calculate_total_earned()
        if daily_total_earned > driver.daily_bonus_threshold:
            daily_bonus = int(((daily_total_earned - driver.daily_bonus_threshold) * driver.daily_bonus_percentage) + self.additional_wages)
            return daily_bonus
        else:
            return 0 + self.additional_wages

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
        if self.status == "working":
            if not (Truck.query.filter(Truck.id == truck_id).first()):
                raise ValueError('Please select a truck')
            return truck_id
        return None
    
    @validates('additional_earned', 'additional_wages')
    def validate_additional(self, key, field):
        if field is None or field == "":  # Check for None or empty string
            return 0
        if self.status == "working":
            try:
                field = float_to_db(field)
            except:
                raise ValueError('Please enter a value earned between £0 and £2000')
            else:
                if not(0 <= field < 200000):
                    raise ValueError('Please enter a value earned between £0 and £2000')
            return field
        return 0
    
    @validates('start_mileage', 'end_mileage')
    def validate_mileage(self, key, field):
        if field is None or field == "":  # Check for None or empty string
            return 0 
        if self.status == "working":
            try:
                field = float_to_db(field)
            except:
                raise ValueError('Please enter a number')
            else:
                if not(0 <= field < 1000000000):
                    raise ValueError('Please enter a number between 0 and 10000000')
            return field
        return 0

    @validates('overnight', 'fuel')
    def validate_boolean_field(self, key, value):
        if self.status == "working":
            if value == 'on':
                return True
            elif value is None or value == None or value == "":
                return False
            else:
                raise ValueError(f'Invalid value for {key}. Please use the selector.')
        return False


class Job(db.Model):
    id: Mapped[intpk]
    timestamp: Mapped[tstamp]
    day_id: Mapped[dayfk_restrict]
    earned: Mapped[int]
    collection: Mapped[str50] 
    delivery: Mapped[str50] 
    notes: Mapped[Optional[str50]]
    split: Mapped[bool] = mapped_column(default=False)

    day: Mapped["Day"] = relationship(back_populates="jobs")

    def __repr__(self): 
    #represents itself in form of string
        return f"Job entry: {display_date(self.day.date)} {self.day.driver.full_name} - {fd_currency(self.earned)} "

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
            earned = float_to_db(earned)
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
        elif value is None or value == "":
            return False
        else:
            raise ValueError(f'Invalid value for {key}. Please use the selector.')


class Payslip(db.Model):
    id: Mapped[intpk]
    day_id: Mapped[Optional[dayfk]]
    timestamp: Mapped[tstamp]
    date: Mapped[date]
    driver_id: Mapped[driverfk]
    total_wage: Mapped[int]
    total_cost_to_employer: Mapped[int]
    week_number_mtf: Mapped[week_number_computed]

    day: Mapped["Day"] = relationship(back_populates="payslip_entries")

    __table_args__ = (
        db.UniqueConstraint(
            'driver_id',
            'week_number_mtf',
            name='_driver_week_payslip_uc'
        ),
    )

    driver: Mapped["Driver"] = relationship(back_populates="payslips")

    def __repr__(self): 
    #represents itself in form of string
        return f"Payslip for: {self.driver.full_name} on {self.date}"

    @hybrid_property
    def get_week_number(self):
        """Returns year and week number of the date in a tuple"""
        return get_week_number_sat_to_fri(self.date)

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
            field = float_to_db(field)
        except:
            raise ValueError('Please enter a value earned between £1 and £3000')
        else:
            if not(100 < field < 300000):
                raise ValueError('Please enter a value earned between £1 and £3000')
        return field    



class Fuel(db.Model):
    id: Mapped[intpk]
    timestamp: Mapped[tstamp]
    date: Mapped[date]
    truck_id: Mapped[truckfk]
    day_id: Mapped[Optional[dayfk]]
    fuel_card_name: Mapped[str50] = mapped_column(index=True)    
    fuel_volume: Mapped[int]
    fuel_cost: Mapped[int]

    truck: Mapped["Truck"] = relationship(back_populates="fuel_entries")
    day: Mapped["Day"] = relationship(back_populates="fuel_entries")

    def __repr__(self): 
    #represents itself in form of string
        return f"Fuel entry for: {self.truck.registration} on {self.date}"

    @hybrid_property
    def get_week_number(self):
        return get_week_number_sat_to_fri(self.date)

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
            fuel_volume = float_to_db(fuel_volume)
        except:
            raise ValueError('Please enter a volume between 1.00L and 1000.00L')
        else:
            if not(100 < fuel_volume < 100000):
                raise ValueError('Please enter a volume between 1.00L and 1000.00L')
        return fuel_volume  

    @validates('fuel_cost')
    def validate_earned(self, key, fuel_cost):
        try:
            fuel_cost = float_to_db(fuel_cost)
        except:
            raise ValueError('Please enter a value between £1.00 and £1500.00')
        else:
            if not(100 < fuel_cost < 150000):
                raise ValueError('Please enter a value between £1.00 and £1500.00')
        return fuel_cost  


class Expense(db.Model):
    id: Mapped[intpk]
    timestamp: Mapped[tstamp]
    name: Mapped[str50] = mapped_column(index=True)
    description: Mapped[Optional[str]] = mapped_column(db.String(200))

    occurrences: Mapped[List["ExpenseOccurrence"]] = relationship(back_populates="expense", cascade="all, delete", lazy=True)

    def __repr__(self):
        #represents itself in form of string
            return f"Expense: {self.name}"

class ExpenseOccurrence(db.Model):
    id: Mapped[intpk]
    timestamp: Mapped[tstamp]
    expense_id: Mapped[expensefk_cascade]
    start_date: Mapped[date]
    end_date: Mapped[Optional[date]]
    cost: Mapped[int]

    expense: Mapped["Expense"] = relationship(back_populates="occurrences")

    def __repr__(self):
        #represents itself in form of string
            return f"Occurrence For Expense: {self.expense.name}, Start Date: {self.start_date}"

    @validates('end_date')
    def validate_end_date(self, key, end_date):
        try:
            end_date = date_to_db(end_date)
        except:
            raise ValueError('Please enter date in format dd/mm/yyyy')
        else:
            if end_date is not None:
                if end_date <= self.start_date:
                    raise ValueError("End date must be after start date")
        return end_date

    @validates('start_date')
    def validate_start_date(self, key, start_date):
        try:
            start_date = date_to_db(start_date)
        except:
            raise ValueError('Please enter date in format dd/mm/yyyy asdva')
        else:
            if self.end_date is not None and start_date >= self.end_date:
                raise ValueError("Start date must be before end date")
        return start_date
    
    @validates('cost')
    def validate_earned(self, key, cost):
        try:
            cost = float_to_db(cost)
        except:
            raise ValueError('Please enter a value between £1.00 and £1500.00')
        else:
            if not(100 < cost < 150000):
                raise ValueError('Please enter a value between £1.00 and £1500.00')
        return cost



        











    

