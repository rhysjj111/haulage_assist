# Plan for weekly analysis route.

## Below is the desired json/dictionary structure to be achieved within the weekly analysis route.

```
[
  {
    <!-- # week details -->
    "week_start_date": "2025-05-26",
    "week_end_date": "2025-06-01",
    "year": 2025,
    "week_number": 22,
    "status": "Partial/Complete",

    <!-- # weekly totals -->
    "period_total_earned": 640.00,
    "period_total_estimated_fuel_sum": 85.00,
    "period_total_actual_fuel_sum": 25.00,
    "period_total_calculated_wage_sum": 192.00,
    "period_total_estimated_cost_to_employer_sum": 192.00,
    "period_total_actual_cost_to_employer_sum": 60.00,
    "period_total_running_costs": 262.50,
    "period_total_costs_best_available": 262.50,
    "period_net_profit_best_available": 377.50,
    "period_fuel_status": "Estimated/Actual",
    "period_wage_status": "Estimated/Actual",

    <!-- # weekly breakdown by driver -->
    "drivers": [
      {
        "driver_id": 1,
        "driver_name": "Alice Wonderland",
        "truck_id": 1,
        "weekly_earned": 430.00,
        "weekly_estimated_fuel_sum": 50.00,
        "weekly_actual_fuel_sum": 25.00,
        "weekly_calculated_wage_sum": 129.00,
        "weekly_estimated_cost_to_employer": 129.00,
        "weekly_actual_cost_to_employer": 60.00,
        "weekly_running_costs": 159.00,
        "weekly_total_costs_best_available": 159.00,
        "weekly_net_profit_best_available": 271.00,
        "weekly_fuel_status": "Estimated/Actual",
        "weekly_wage_status": "Estimated/Actual",
        "days_worked": 5,
        "daily_breakdown": [
          {
            "day_id": 1,
            "date": "2025-05-26",
            "status": "working/absent/holiday",
            "day_start_mileage": 70.0,
            "day_end_mileage": 100.0,
            "day_calculated_mileage": 30.0,
            "daily_earned": 230.00,
            "overnight": True/False,
            "fuel_flag": True/False,
            "daily_bonus": 0.00,
            "daily_estimated_fuel_sum": 25.00,
            "jobs": [
              {
                "job_id": 1,
                "earned": 150.00,
                "collection": "Derby",
                "delivery": "Nottingham",
                "split": True/False,
              },
            ],
            "fuel_entries_details": [
              {
                "fuel_id": 1,
                "fuel_cost": 25.00,
                "fuel_litres": 25.00,
              }
            ],
          },
        ]
      }
    ]
  }
]
```

### Sample application
```


Python

# app.py
from flask import Flask, jsonify, render_template, request
from flask_sqlalchemy import SQLAlchemy
from datetime import date, timedelta, datetime
from collections import defaultdict
import calendar # Needed for monthrange calculations


# --- App and DB Initialization ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///drivers_report.db' # Using SQLite for simplicity
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Suppress warning
db = SQLAlchemy(app)

# --- SQLAlchemy Models ---
# These define your database tables and their relationships.

class Day(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    mileage = db.Column(db.Float, default=0.0) # Mileage for the entire day
    jobs = db.relationship('Job', backref='day', lazy=True)
    fuel_entries = db.relationship('FuelEntry', backref='day', lazy=True)
    wage_entries = db.relationship('WageEntry', backref='day', lazy=True)

    def __repr__(self):
        return f'<Day {self.date} (Mileage: {self.mileage})>'

class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    jobs = db.relationship('Job', backref='driver', lazy=True) # Direct relationship for job assignment

    def __repr__(self):
        return f'<Driver {self.name}>'

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=False)
    day_id = db.Column(db.Integer, db.ForeignKey('day.id'), nullable=False)
    date = db.Column(db.Date, nullable=False) # Redundant but useful for direct queries
    earned = db.Column(db.Float, nullable=False)
    other_costs = db.Column(db.Float, default=0.0) # Non-fuel, non-wage operational costs
    description = db.Column(db.String(255))

    def __repr__(self):
        return f'<Job {self.id} on {self.date} by Driver {self.driver_id}>'

class FuelEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day_id = db.Column(db.Integer, db.ForeignKey('day.id'), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True) # Optional: if fuel assigned per driver
    date = db.Column(db.Date, nullable=False) # Redundant but useful
    amount = db.Column(db.Float, nullable=False) # Actual fuel cost from invoice
    description = db.Column(db.String(255))

    def __repr__(self):
        return f'<FuelEntry {self.id} on {self.date} for Driver {self.driver_id}>'

class WageEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day_id = db.Column(db.Integer, db.ForeignKey('day.id'), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=False)
    date = db.Column(db.Date, nullable=False) # Redundant but useful
    amount = db.Column(db.Float, nullable=False) # Actual wage paid out
    description = db.Column(db.String(255))

    def __repr__(self):
        return f'<WageEntry {self.id} on {self.date} for Driver {self.driver_id}>'


# --- Cost Calculation Parameters ---
# These parameters are used for estimating fuel and wage costs.
FUEL_EFFICIENCY_MPG = 15.0
FUEL_COST_PER_GALLON = 5.0
WAGE_PERCENTAGE_OF_EARNED = 0.30

# --- Shared Helper Functions ---
# These functions perform common date calculations and cost estimations.

def get_iso_week_start_end_dates(year, week_number):
    """Calculates the start (Monday) and end (Sunday) dates for a given ISO week number."""
    start_of_week = date.fromisocalendar(year, week_number, 1)
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week

def calculate_estimated_fuel_cost(day_mileage):
    """Estimates fuel cost based on daily mileage."""
    if day_mileage is None or day_mileage <= 0: return 0.0
    return round((day_mileage / FUEL_EFFICIENCY_MPG) * FUEL_COST_PER_GALLON, 2)

def calculate_estimated_wage_cost(earned_amount):
    """Estimates wage cost based on earnings."""
    if earned_amount is None or earned_amount <= 0: return 0.0
    return round(earned_amount * WAGE_PERCENTAGE_OF_EARNED, 2)

# --- Database Seeding ---
# This function populates your database with sample data.
# It runs once when the app starts for the very first time.
@app.before_first_request
def create_tables():
    db.create_all()
    if not Driver.query.first():
        driver1 = Driver(name="Alice Wonderland")
        driver2 = Driver(name="Bob The Builder")
        db.session.add_all([driver1, driver2])
        db.session.commit()

        # Current date for seeding reference (e.g., Sunday, June 1, 2025)
        current_date = date(2025, 6, 1) # Force to a known date for predictable output
        current_year, current_week_num, _ = current_date.isocalendar() # 2025, 22, 7 (Sunday)
        week_start, _ = get_iso_week_start_end_dates(current_year, current_week_num) # Mon, May 26, 2025

        # Create Day entries with mileage for the current week (Week 22, 2025)
        day_mon = Day(date=week_start + timedelta(days=0), mileage=70.0) # May 26
        day_tue = Day(date=week_start + timedelta(days=1), mileage=45.0) # May 27
        day_wed = Day(date=week_start + timedelta(days=2), mileage=80.0) # May 28
        day_fri = Day(date=week_start + timedelta(days=4), mileage=60.0) # May 30
        day_sat = Day(date=week_start + timedelta(days=5), mileage=0.0)  # May 31 (No mileage/jobs)
        db.session.add_all([day_mon, day_tue, day_wed, day_fri, day_sat])
        db.session.commit() # Commit days first to get their IDs

        # --- Sample Jobs (Current Week: Week 22, 2025) ---
        db.session.add(Job(driver=driver1, day=day_mon, date=day_mon.date, earned=150.00, other_costs=5.00, description="Monday Delivery A"))
        db.session.add(Job(driver=driver1, day=day_mon, date=day_mon.date, earned=80.00, other_costs=2.00, description="Monday Pickup B"))
        db.session.add(Job(driver=driver1, day=day_wed, date=day_wed.date, earned=200.00, other_costs=10.00, description="Wednesday Long Haul"))

        db.session.add(Job(driver=driver2, day=day_tue, date=day_tue.date, earned=120.00, other_costs=3.00, description="Tuesday Courier Run"))
        db.session.add(Job(driver=driver2, day=day_fri, date=day_fri.date, earned=90.00, other_costs=2.50, description="Friday Local Drop"))

        # --- Sample Fuel & Wage Entries (Actuals for Current Week) ---
        db.session.add(FuelEntry(day=day_mon, date=day_mon.date, driver=driver1, amount=25.00, description="Actual Fuel for Monday (shared)"))
        db.session.add(WageEntry(day=day_wed, date=day_wed.date, driver=driver1, amount=60.00, description="Actual Wage for Alice's Wed Long Haul"))

        # --- Sample Data for Previous Week (Week 21, 2025) ---
        prev_week_start, _ = get_iso_week_start_end_dates(current_year, current_week_num - 1)
        day_prev_mon = Day(date=prev_week_start + timedelta(days=0), mileage=50.0) # May 19
        db.session.add(day_prev_mon)
        db.session.commit()
        db.session.add(Job(driver=driver1, day=day_prev_mon, date=day_prev_mon.date, earned=100.00, other_costs=4.00, description="Prev Week Monday Job"))
        db.session.add(FuelEntry(day=day_prev_mon, date=day_prev_mon.date, driver=driver1, amount=18.00, description="Actual Fuel for Prev Mon"))
        db.session.add(WageEntry(day=day_prev_mon, date=day_prev_mon.date, driver=driver1, amount=30.00, description="Actual Wage for Prev Mon"))

        # --- Sample Data for a completely empty week (Week 20, 2025) ---
        # No Day, Job, FuelEntry, or WageEntry records for Week 20
        # This will simulate a "No data" week.

        db.session.commit()
        print("Database seeded with sample data.")


# --- Reusable Data Aggregation Functions ---
# These functions encapsulate the core logic for building the report data.

def get_weekly_report_data_agg(year, week_num):
    """Aggregates driver data for a specific ISO week."""
    start_of_week, end_of_week = get_iso_week_start_end_dates(year, week_num)
    
    # Determine the overall status for the week
    overall_period_status = "Complete" # Default for past week
    if start_of_week > date.today():
        overall_period_status = "Future"
    elif end_of_week >= date.today(): # If week ends today or in future, it's partial
        overall_period_status = "Partial/Estimated"

    # 1. Query Days with Mileage (for estimated fuel)
    days_in_period_query = db.session.query(Day).\
        filter(Day.date >= start_of_week, Day.date <= end_of_week).\
        all()
    days_lookup = {d.date.strftime('%Y-%m-%d'): d for d in days_in_period_query}

    # 2. Query Jobs
    jobs_for_period = db.session.query(Job, Driver).\
        join(Driver).\
        filter(Job.date >= start_of_week, Job.date <= end_of_week).\
        order_by(Driver.id, Job.date).\
        all()
    
    # 3. Query Fuel Entries (Actuals)
    fuel_entries_for_period = db.session.query(FuelEntry, Driver).\
        outerjoin(Driver).\
        filter(FuelEntry.date >= start_of_week, FuelEntry.date <= end_of_week).\
        all()

    # 4. Query Wage Entries (Actuals)
    wage_entries_for_period = db.session.query(WageEntry, Driver).\
        join(Driver).\
        filter(WageEntry.date >= start_of_week, WageEntry.date <= end_of_week).\
        all()

    # --- Initialize Aggregation Structure ---
    # defaultdicts are used for dynamic aggregation
    drivers_data = defaultdict(lambda: {
        "driver_id": None, "driver_name": None,
        "weekly_earned": 0.0, "weekly_other_costs": 0.0,
        "weekly_estimated_fuel_sum": 0.0, "weekly_actual_fuel_sum": 0.0,
        "weekly_estimated_wage_sum": 0.0, "weekly_actual_wage_sum": 0.0,
        "weekly_total_costs_best_available": 0.0,
        "weekly_net_profit_best_available": 0.0,
        "daily_breakdown": defaultdict(lambda: { # Will hold data only for days with activity
            "date": None, "day_mileage": 0.0,
            "daily_earned": 0.0, "daily_other_costs": 0.0,
            "daily_estimated_fuel_sum": 0.0, "daily_actual_fuel_sum": 0.0,
            "daily_estimated_wage_sum": 0.0, "daily_actual_wage_sum": 0.0,
            "daily_total_costs_best_available": 0.0,
            "daily_net_profit_best_available": 0.0,
            "jobs": [], "fuel_entries_details": [], "wage_entries_details": [],
            "status": "No data" # Initial status, updated if data is found
        })
    })

    # --- Step 1: Process Jobs (base earnings, other costs, estimated wages) ---
    for job, driver in jobs_for_period:
        driver_id = driver.id
        job_date = job.date
        day_date_str = job_date.strftime('%Y-%m-%d')

        drivers_data[driver_id]["driver_id"] = driver.id
        drivers_data[driver_id]["driver_name"] = driver.name

        job_estimated_wage = calculate_estimated_wage_cost(job.earned)
        
        drivers_data[driver_id]["weekly_earned"] += job.earned
        drivers_data[driver_id]["weekly_other_costs"] += job.other_costs
        drivers_data[driver_id]["weekly_estimated_wage_sum"] += job_estimated_wage

        current_day_breakdown = drivers_data[driver_id]["daily_breakdown"][day_date_str]
        current_day_breakdown["date"] = day_date_str
        current_day_breakdown["daily_earned"] += job.earned
        current_day_breakdown["daily_other_costs"] += job.other_costs
        current_day_breakdown["daily_estimated_wage_sum"] += job_estimated_wage
        
        current_day_breakdown["jobs"].append({
            "job_id": job.id, "earned": job.earned, "other_costs": job.other_costs,
            "description": job.description, "estimated_wage_cost_job_contribution": job_estimated_wage
        })

    # --- Step 2: Process Actual Fuel Entries ---
    for fuel_entry, driver in fuel_entries_for_period:
        driver_id = fuel_entry.driver_id # Use the driver_id on the FuelEntry if present
        if driver_id is None: # If fuel isn't driver-specific for the report, skip or handle separately
            continue

        fuel_date = fuel_entry.date
        day_date_str = fuel_date.strftime('%Y-%m-%d')

        drivers_data[driver_id]["driver_id"] = driver_id
        drivers_data[driver_id]["driver_name"] = driver.name # Ensure name is set for drivers with only fuel/wage entries

        drivers_data[driver_id]["weekly_actual_fuel_sum"] += fuel_entry.amount

        current_day_breakdown = drivers_data[driver_id]["daily_breakdown"][day_date_str]
        current_day_breakdown["date"] = day_date_str
        current_day_breakdown["daily_actual_fuel_sum"] += fuel_entry.amount
        current_day_breakdown["fuel_entries_details"].append({
            "id": fuel_entry.id, "amount": fuel_entry.amount, "description": fuel_entry.description
        })

    # --- Step 3: Process Actual Wage Entries ---
    for wage_entry, driver in wage_entries_for_period:
        driver_id = wage_entry.driver_id # Wages are driver specific
        wage_date = wage_entry.date
        day_date_str = wage_date.strftime('%Y-%m-%d')

        drivers_data[driver_id]["driver_id"] = driver.id
        drivers_data[driver_id]["driver_name"] = driver.name

        drivers_data[driver_id]["weekly_actual_wage_sum"] += wage_entry.amount

        current_day_breakdown = drivers_data[driver_id]["daily_breakdown"][day_date_str]
        current_day_breakdown["date"] = day_date_str
        current_day_breakdown["daily_actual_wage_sum"] += wage_entry.amount
        
        current_day_breakdown["wage_entries_details"].append({
            "id": wage_entry.id, "amount": wage_entry.amount, "description": wage_entry.description
        })

    # --- Step 4: Finalize Totals & Statuses (Iterate through all drivers & days) ---
    report_drivers = []
    all_drivers_in_db = Driver.query.order_by(Driver.name).all()

    for driver_obj in all_drivers_in_db:
        driver_id = driver_obj.id
        # Get driver's aggregated data, or initialize if no jobs/entries for them
        driver_info = drivers_data.get(driver_id, {
            "driver_id": driver_obj.id, "driver_name": driver_obj.name,
            "weekly_earned": 0.0, "weekly_other_costs": 0.0,
            "weekly_estimated_fuel_sum": 0.0, "weekly_actual_fuel_sum": 0.0,
            "weekly_estimated_wage_sum": 0.0, "weekly_actual_wage_sum": 0.0,
            "weekly_total_costs_best_available": 0.0,
            "weekly_net_profit_best_available": 0.0,
            "daily_breakdown": {}
        })

        daily_breakdown_list = []
        for i in range(7): # Iterate through all 7 days of the week for status and mileage
            current_day_date = start_of_week + timedelta(days=i)
            day_date_str = current_day_date.strftime('%Y-%m-%d')
            
            day_obj_for_mileage = days_lookup.get(day_date_str)
            daily_mileage = day_obj_for_mileage.mileage if day_obj_for_mileage else 0.0
            daily_estimated_fuel_from_mileage = calculate_estimated_fuel_cost(daily_mileage)

            # Get the aggregated data for this specific day and driver, or create a default
            day_data = driver_info["daily_breakdown"].get(day_date_str, {
                "date": day_date_str, "day_mileage": daily_mileage,
                "daily_earned": 0.0, "daily_other_costs": 0.0,
                "daily_estimated_fuel_sum": 0.0, "daily_actual_fuel_sum": 0.0,
                "daily_estimated_wage_sum": 0.0, "daily_actual_wage_sum": 0.0,
                "daily_total_costs_best_available": 0.0, "daily_net_profit_best_available": 0.0,
                "jobs": [], "fuel_entries_details": [], "wage_entries_details": [],
                "status": "No data" # Default, to be overridden if any activity
            })
            
            day_data["daily_estimated_fuel_sum"] = daily_estimated_fuel_from_mileage # Update with daily estimate

            # Determine Best Available Fuel Cost for this day
            daily_fuel_cost_for_total = day_data["daily_actual_fuel_sum"] # Prioritize actual
            daily_fuel_status = "Actual"
            if daily_fuel_cost_for_total == 0.0 and day_data["daily_estimated_fuel_sum"] > 0:
                daily_fuel_cost_for_total = day_data["daily_estimated_fuel_sum"]
                daily_fuel_status = "Estimated"
            elif daily_fuel_cost_for_total == 0.0 and day_data["daily_estimated_fuel_sum"] == 0.0:
                daily_fuel_status = "N/A"

            # Determine Best Available Wage Cost for this day
            daily_wage_cost_for_total = day_data["daily_actual_wage_sum"] # Prioritize actual
            daily_wage_status = "Actual"
            if daily_wage_cost_for_total == 0.0 and day_data["daily_estimated_wage_sum"] > 0:
                daily_wage_cost_for_total = day_data["daily_estimated_wage_sum"]
                daily_wage_status = "Estimated"
            elif daily_wage_cost_for_total == 0.0 and day_data["daily_estimated_wage_sum"] == 0.0:
                daily_wage_status = "N/A"

            # Calculate daily total costs and net profit using best available figures
            day_data["daily_total_costs_best_available"] = (
                day_data["daily_other_costs"] + daily_fuel_cost_for_total + daily_wage_cost_for_total
            )
            day_data["daily_net_profit_best_available"] = (
                day_data["daily_earned"] - day_data["daily_total_costs_best_available"]
            )
            
            # Add statuses and chosen values to day data
            day_data["daily_fuel_cost_used_for_total"] = daily_fuel_cost_for_total
            day_data["daily_fuel_status"] = daily_fuel_status
            day_data["daily_wage_cost_used_for_total"] = daily_wage_cost_for_total
            day_data["daily_wage_status"] = daily_wage_status

            # Set overall day status (Partial/Complete/No data/Future)
            # A day has "data" if it has earned, other costs, actual fuel/wage, or any jobs/entries.
            has_activity_for_day = (
                day_data["daily_earned"] > 0 or day_data["daily_other_costs"] > 0 or
                day_data["daily_actual_fuel_sum"] > 0 or day_data["daily_actual_wage_sum"] > 0 or
                day_data["jobs"] or day_data["fuel_entries_details"] or day_data["wage_entries_details"]
            )

            if has_activity_for_day:
                day_data["status"] = "Complete" if current_day_date < date.today() else "Partial/Estimated"
            elif current_day_date > date.today():
                day_data["status"] = "Future"
            # If nothing above, status remains "No data" (default)

            daily_breakdown_list.append(day_data)
        
        # Filter out days with "No data" or "Future" status based on your preference
        driver_info["daily_breakdown"] = [d for d in daily_breakdown_list if d["status"] not in ["No data", "Future"]]
        driver_info["daily_breakdown"].sort(key=lambda x: x['date']) # Ensure sorted

        # Recalculate weekly sums based on the *filtered* daily breakdown data
        # This is essential if you filter out days, so weekly sums reflect displayed data
        driver_info["weekly_earned"] = sum(d['daily_earned'] for d in driver_info["daily_breakdown"])
        driver_info["weekly_other_costs"] = sum(d['daily_other_costs'] for d in driver_info["daily_breakdown"])
        driver_info["weekly_estimated_fuel_sum"] = sum(d['daily_estimated_fuel_sum'] for d in driver_info["daily_breakdown"])
        driver_info["weekly_actual_fuel_sum"] = sum(d['daily_actual_fuel_sum'] for d in driver_info["daily_breakdown"])
        driver_info["weekly_estimated_wage_sum"] = sum(d['daily_estimated_wage_sum'] for d in driver_info["daily_breakdown"])
        driver_info["weekly_actual_wage_sum"] = sum(d['daily_actual_wage_sum'] for d in driver_info["daily_breakdown"])
        driver_info["weekly_total_costs_best_available"] = sum(d['daily_total_costs_best_available'] for d in driver_info["daily_breakdown"])
        driver_info["weekly_net_profit_best_available"] = sum(d['daily_net_profit_best_available'] for d in driver_info["daily_breakdown"])

        # Determine driver's weekly fuel/wage status based on filtered data
        driver_info["weekly_fuel_status"] = "N/A"
        if driver_info["weekly_actual_fuel_sum"] > 0: driver_info["weekly_fuel_status"] = "Actual"
        elif driver_info["weekly_estimated_fuel_sum"] > 0: driver_info["weekly_fuel_status"] = "Estimated"
        
        driver_info["weekly_wage_status"] = "N/A"
        if driver_info["weekly_actual_wage_sum"] > 0: driver_info["weekly_wage_status"] = "Actual"
        elif driver_info["weekly_estimated_wage_sum"] > 0: driver_info["weekly_wage_status"] = "Estimated"

        # Only add driver to report if they have any data at all for the week
        # (This check is applied AFTER recalculating sums based on filtered daily data)
        if driver_info["weekly_earned"] > 0 or driver_info["weekly_total_costs_best_available"] > 0:
            report_drivers.append(driver_info)
    
    report_drivers.sort(key=lambda x: x['driver_name']) # Sort final list of drivers

    # If no drivers were added to report_drivers, it means no data for the whole week
    if not report_drivers and overall_period_status == "Complete":
        overall_period_status = "No data"

    # Calculate overall period totals from aggregated driver data
    # (These sums will reflect the filtered `report_drivers` list)
    period_total_earned = sum(d['weekly_earned'] for d in report_drivers)
    period_total_other_costs = sum(d['weekly_other_costs'] for d in report_drivers)
    period_total_estimated_fuel_sum = sum(d['weekly_estimated_fuel_sum'] for d in report_drivers)
    period_total_actual_fuel_sum = sum(d['weekly_actual_fuel_sum'] for d in report_drivers)
    period_total_estimated_wage_sum = sum(d['weekly_estimated_wage_sum'] for d in report_drivers)
    period_total_actual_wage_sum = sum(d['weekly_actual_wage_sum'] for d in report_drivers)
    period_total_costs_best_available = sum(d['weekly_total_costs_best_available'] for d in report_drivers)
    period_net_profit_best_available = sum(d['weekly_net_profit_best_available'] for d in report_drivers)

    # Determine overall period fuel/wage status
    period_fuel_status = "N/A"
    if period_total_actual_fuel_sum > 0: period_fuel_status = "Actual"
    elif period_total_estimated_fuel_sum > 0: period_fuel_status = "Estimated"
    
    period_wage_status = "N/A"
    if period_total_actual_wage_sum > 0: period_wage_status = "Actual"
    elif period_total_estimated_wage_sum > 0: period_wage_status = "Estimated"

    return {
        "week_start_date": start_of_week.strftime('%Y-%m-%d'),
        "week_end_date": end_of_week.strftime('%Y-%m-%d'),
        "year": year,
        "week_number": week_num,
        "status": overall_period_status,
        "drivers": report_drivers,
        "period_total_earned": period_total_earned,
        "period_total_other_costs": period_total_other_costs,
        "period_total_estimated_fuel_sum": period_total_estimated_fuel_sum,
        "period_total_actual_fuel_sum": period_total_actual_fuel_sum,
        "period_total_estimated_wage_sum": period_total_estimated_wage_sum,
        "period_total_actual_wage_sum": period_total_actual_wage_sum,
        "period_total_costs_best_available": period_total_costs_best_available,
        "period_net_profit_best_available": period_net_profit_best_available,
        "period_fuel_status": period_fuel_status,
        "period_wage_status": period_wage_status,
    }


# --- (Placeholder for get_monthly_report_data_agg and get_yearly_report_data_agg) ---
# You would fill these in following the same pattern as get_weekly_report_data_agg,
# but with aggregation logic adjusted for monthly/yearly breakdowns.
# Example placeholder return:
def get_monthly_report_data_agg(year, month_num):
    start_of_month = date(year, month_num, 1)
    end_of_month = date(year, month_num, calendar.monthrange(year, month_num)[1])
    overall_period_status = "Complete"
    if end_of_month >= date.today(): overall_period_status = "Partial/Estimated"
    if start_of_month > date.today(): overall_period_status = "Future"
    # In a real implementation, this would perform queries and aggregation for the month
    # similar to get_weekly_report_data_agg, but summing up to month/week levels.
    return {"month_id": f"{year}-{month_num:02d}", "month_name": start_of_month.strftime('%B %Y'), "status": overall_period_status, "drivers": [], "total_month_earned": 0.0, "total_month_costs": 0.0, "period_fuel_status": "N/A", "period_wage_status": "N/A"}

def get_yearly_report_data_agg(year):
    start_of_year = date(year, 1, 1)
    end_of_year = date(year, 12, 31)
    overall_period_status = "Complete"
    if end_of_year >= date.today(): overall_period_status = "Partial/Estimated"
    if start_of_year > date.today(): overall_period_status = "Future"
    # In a real implementation, this would perform queries and aggregation for the year
    # summing up to yearly/monthly/weekly levels.
    return {"year_id": str(year), "status": overall_period_status, "drivers": [], "total_year_earned": 0.0, "total_year_costs": 0.0, "period_fuel_status": "N/A", "period_wage_status": "N/A"}


# --- Jinja2 Custom Filters and Context Processors ---
# These make date handling in templates easier.
@app.template_filter('to_date')
def to_date_filter(s):
    if s:
        return datetime.strptime(s, '%Y-%m-%d').date()
    return None

@app.context_processor
def inject_today_date_and_earliest():
    # This ensures 'today_date' and 'earliest_data_date_in_system' are available in ALL templates
    return {
        'today_date': date.today(),
        'earliest_data_date_in_system': get_earliest_data_date()
    }

_earliest_data_date_cache = None # Cache for efficiency

def get_earliest_data_date():
    """
    Queries the database to find the absolute earliest date for which any data exists.
    Caches the result after the first call.
    """
    global _earliest_data_date_cache
    if _earliest_data_date_cache is None:
        earliest_job_date = db.session.query(db.func.min(Job.date)).scalar()
        earliest_day_date = db.session.query(db.func.min(Day.date)).scalar()
        earliest_fuel_date = db.session.query(db.func.min(FuelEntry.date)).scalar()
        earliest_wage_date = db.session.query(db.func.min(WageEntry.date)).scalar()

        all_dates = [d for d in [earliest_job_date, earliest_day_date, earliest_fuel_date, earliest_wage_date] if d is not None]
        
        if all_dates:
            _earliest_data_date_cache = min(all_dates)
        else:
            # If no data at all, set to a very early date so 'Previous' is always disabled
            _earliest_data_date_cache = date(1970, 1, 1) # Arbitrary very early date
    return _earliest_data_date_cache


# --- Flask Routes for Display Pages (HTML Rendering) ---

@app.route('/')
def home_page():
    """Application homepage, providing navigation links to reports."""
    today = date.today()
    current_year, current_week_num, _ = today.isocalendar()
    current_month_num = today.month

    return render_template('home_page.html',
                           current_year=current_year,
                           current_week_num=current_week_num,
                           current_month_num=current_month_num)

@app.route('/report/weekly')
def display_weekly_report():
    """Renders the HTML page for the weekly driver report."""
    today = date.today() # Get today's date within the request context
    year = int(request.args.get('year', today.isocalendar()[0]))
    week_num = int(request.args.get('week_num', today.isocalendar()[1]))

    # Call the reusable data aggregation function to get report data
    report_data = get_weekly_report_data_agg(year, week_num)

    # Render the Jinja2 template, passing the aggregated data to it
    return render_template('weekly_report_display.html', report=report_data)

@app.route('/report/monthly')
def display_monthly_report():
    """Renders the HTML page for the monthly driver report."""
    today = date.today()
    year = int(request.args.get('year', today.year))
    month_num = int(request.args.get('month_num', today.month))

    # Call the reusable data aggregation function
    report_data = get_monthly_report_data_agg(year, month_num)

    # Render the Jinja2 template
    return render_template('monthly_report_display.html', report=report_data)

@app.route('/report/yearly')
def display_yearly_report():
    """Renders the HTML page for the yearly driver report."""
    today = date.today()
    year = int(request.args.get('year', today.year))

    # Call the reusable data aggregation function
    report_data = get_yearly_report_data_agg(year)

    # Render the Jinja2 template
    return render_template('yearly_report_display.html', report=report_data)


# --- Flask Routes for API Endpoints (JSON Data) ---
# These routes provide JSON data and would have counterparts for monthly/yearly reports.

@app.route('/api/report/weekly')
def api_weekly_report():
    """Provides JSON data for the weekly driver report."""
    try:
        year = int(request.args.get('year'))
        week_num = int(request.args.get('week_num'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid year or week_num provided."}), 400

    # Call the reusable data aggregation function
    weekly_data = get_weekly_report_data_agg(year, week_num)
    
    # Return as JSON, typically wrapped in a list for consistency with multi-period potential
    return jsonify([weekly_data])

@app.route('/api/report/monthly')
def api_monthly_report():
    """Provides JSON data for the monthly driver report."""
    try:
        year = int(request.args.get('year'))
        month_num = int(request.args.get('month_num'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid year or month_num provided."}), 400
    monthly_data = get_monthly_report_data_agg(year, month_num)
    return jsonify([monthly_data])

@app.route('/api/report/yearly')
def api_yearly_report():
    """Provides JSON data for the yearly driver report."""
    try:
        year = int(request.args.get('year'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid year provided."}), 400
    yearly_data = get_yearly_report_data_agg(year)
    return jsonify([yearly_data])


# --- Main Application Execution ---
if __name__ == '__main__':
    with app.app_context():
        # Ensure database tables are created and seeded with sample data
        # (This is called once when the app starts if tables don't exist)
        create_tables() 
    app.run(debug=True)
```