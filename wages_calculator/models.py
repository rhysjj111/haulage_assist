from wages_calculator import db
from sqlalchemy.orm import validates

class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, nullable=False)
    first_name = db.Column(db.String(30), nullable=False) 
    second_name = db.Column(db.String(30), nullable=False) 
    base_wage = db.Column(db.Integer, nullable=False)
    bonus_percentage = db.Column(db.Float, nullable=False)
    day_end_days = db.relationship("DayEnd", backref="driver", cascade="all, delete", lazy=True)

    def name(self):
        #returns full name of driver
        return f"{self.first_name} {self.second_name}"
        
    def __repr__(self): 
        #represents itself in form of string
        return f"Driver: {self.first_name} {self.second_name}"
    
    @validates('first_name')
    def validate_first_name(self, key, first_name):
        if len(first_name) == 3:
            raise AssertionError
        return first_name

class DayEnd(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    earned = db.Column(db.Integer, nullable=False)
    overnight = db.Column(db.Boolean, nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("driver.id", ondelete="CASCADE"), nullable=False)

    def __repr__(self):
        #represents itself in form of string
        return f"Enry for: {self.driver.first_name} {self.driver.second_name} on {self.date}"


