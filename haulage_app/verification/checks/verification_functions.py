from datetime import date, timedelta
from sqlalchemy import func
from haulage_app.models import Payslip, Driver

def test():
    print('cunt')

def find_missing_payslip_weeks(start_date, end_date):
    """
    Find weeks where payslips are missing between given dates
    
    Args:
        start_date (datetime): Starting date to check from
        end_date (datetime): End date to check to
        
    Returns:
        list: List of Friday dates where payslips are missing
    """
    missing_weeks = []
    current_date = start_date
    
    while current_date <= end_date:
        friday = get_friday_from_date(current_date)
        payslip = Payslip.query.filter(Payslip.date == friday).first()
        
        if not payslip:
            missing_weeks.append(friday)
            
        current_date += timedelta(days=7)
        
    return missing_weeks

def get_all_missing_payslip_weeks():
    """
    Get all missing payslip weeks from first to last payslip entry
    
    Returns:
        list: List of Friday dates where payslips are missing
    """
    first_payslip = Payslip.query.order_by(Payslip.date.asc()).first()
    last_payslip = Payslip.query.order_by(Payslip.date.desc()).first()
    
    if not first_payslip or not last_payslip:
        return []
        
    return find_missing_payslip_weeks(first_payslip.date, last_payslip.date)



def find_missing_payslips():
    """
    Checks for missing payslips for each driver and returns a list of missing dates.

    Returns:
        dict: A dictionary where keys are driver names and values are lists of missing Friday dates.
    """
    missing_payslips = {}
    drivers = Driver.query.all()

    for driver in drivers:
        missing_dates = []
        # Find the first and last Friday based on existing payslips for the driver
        first_payslip_date = (
            Payslip.query.with_entities(func.min(Payslip.date))
            .filter_by(driver_id=driver.id)
            .scalar()
        )
        last_payslip_date = (
            Payslip.query.with_entities(func.max(Payslip.date))
            .filter_by(driver_id=driver.id)
            .scalar()
        )

        if first_payslip_date and last_payslip_date:
            # Generate all Fridays between the first and last payslip dates
            current_date = first_payslip_date
            while current_date <= last_payslip_date:
                if current_date.weekday() == 4:  # Friday
                    payslip_exists = Payslip.query.filter_by(
                        driver_id=driver.id, date=current_date
                    ).first()
                    if not payslip_exists:
                        missing_dates.append(current_date)
                current_date += timedelta(days=1)

        if missing_dates:
            missing_payslips[driver.id] = missing_dates

    print(missing_payslips)


def process_missing_payslips(missing_payslips_output):
    """
    Process missing payslips and update the Anomaly table.
    Args:
        missing_payslips_output (dict): Output from find_missing_payslips() function.
    Returns:
        None
    """
    from haulage_app.verification.models import Anomaly
    from haulage_app.models import db
    
    for driver_id, missing_dates in missing_payslips_output.items():
        for date_obj in missing_dates:
            # Check if the entry is already in the database
            anomaly_entry = Anomaly.query.filter_by(date=date_obj, driver_id=driver_id).first()
            
            if not anomaly_entry:
                # If not in the database, add a new entry
                new_anomaly = Anomaly(date=date_obj, driver_id=driver_id)
                db.session.add(new_anomaly)
                db.session.commit()
            else:
                # If in the database, check if is_read is False
                if not anomaly_entry.is_read:
                    # If is_read is False, do nothing
                    pass
                else:
                    # If is_read is True, check if is_repeated is False
                    if not anomaly_entry.is_repeated:
                        # If is_repeated is False, update is_read to False and is_repeated to True
                        anomaly_entry.is_read = False
                        anomaly_entry.is_repeated = True
                        db.session.commit()
    print("Missing payslips processed")


