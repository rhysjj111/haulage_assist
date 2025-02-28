from datetime import date, timedelta
from sqlalchemy import func
from haulage_app.models import (
    Payslip, 
    Driver, 
    Day, 
    Truck,
    Fuel,
)
from haulage_app.verification.models import MissingEntryAnomaly, TableName
from haulage_app.models import db
from haulage_app.functions import(
    display_date_pretty,
)
from haulage_app.analysis.functions import(
    get_start_and_end_of_week,
    get_start_of_week,
    find_previous_saturday,
    get_week_number_sat_to_fri,
)

def get_next_friday_from_date(start_date):
    """
    Calculates the Friday of the week for a given date.
    Args:
        date: A datetime.date object.
    Returns:
        A datetime.date object representing the Friday of the week.
    """
    days_ahead = (4 - start_date.weekday()) % 7  # 4 corresponds to Friday
    return start_date + timedelta(days=days_ahead)



def find_missing_payslip_weeks(start_date, end_date):
    """
    Finds weeks where payslips are missing for each driver between given dates.

    Args:
        start_date (datetime.date): The starting date to check for missing payslips.
        end_date (datetime.date): The end date to check for missing payslips.

    Returns:
        dict: A dictionary where keys are driver_id and values are lists of dictionaries.
              Each dictionary in the list represents a missing payslip week and contains the key 'date'
              with the corresponding missing date as a datetime.date object.
    """
    missing_payslips_by_driver = {}
    drivers = Driver.query.all()

    for driver in drivers:
        missing_weeks = []
        current_date = start_date
        
        while current_date <= end_date:
            friday = get_next_friday_from_date(current_date)

            payslip = Payslip.query.filter(Payslip.date == friday, Payslip.driver_id == driver.id).first()
            
            if not payslip:
                missing_weeks.append(friday)
                
            current_date += timedelta(days=7)
        if missing_weeks:
            missing_payslips_by_driver[driver.id] = missing_weeks

    return missing_payslips_by_driver



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

def check_week_for_missing_day_entries(driver_id, year, week_number):
    """
    Checks for missing day entries for a given driver and week.

    Args:
        driver_id: The driver ID.
        week_number: The week number (integer).
        year: The year of the data (integer).
    
    Returns:
        A dictionary containing the driver_id and a list of missing day entries.

    """
    # Calculate the start and end dates for the given week
    start_date, end_date = get_start_and_end_of_week(year, week_number)

    # Query database to find day entries
    day_entries = Day.query.filter(
        Day.driver_id == driver_id,
        Day.date.between(start_date, end_date)
    ).all()

    # Check if any days are missing (Monday to Friday)
    missing_days = []
    present_dates = [entry.date for entry in day_entries]

    # Iterate through each day of the week (Monday=0, Tuesday=1, ..., Friday=4)
    for day_offset in range(5):
        # Calculate the expected date for this weekday
        expected_date = start_date + timedelta(days=day_offset)

        # Check if the expected date is in the list of present dates
        if expected_date not in present_dates:
            missing_days.append(expected_date)
    
    return {
        'driver_id': driver_id,
        'missing_days': missing_days,
        'start_date': start_date,
        'end_date': end_date,
        'week_number': week_number,
        'year': year,
    }
            


def check_week_for_missing_fuel_data(truck_id, year, week_number):
    """
    Checks the consistency of fuel data for a given truck and week.

    Args:
        truck_id: The truck ID.
        week_number: The week number (integer).
        year: The year of the data (integer).

    Returns:
        A dictionary containing the counts of fuel entries, day entries with fuel flag,
        and the difference between them. Returns an empty dictionary if there are no
        inconsistencies.
    """
    # Calculate the start and end dates for the given week
    start_date, end_date = get_start_and_end_of_week(year, week_number)

    # Count the number of fuel entries for the given truck and week
    fuel_entry = Fuel.query.filter(
        Fuel.truck_id == truck_id,
        Fuel.date >= start_date,
        Fuel.date <= end_date
    ).all()

    # Count the number of day entries with fuel_flag=True for the given truck and week
    day_entry_fuel = Day.query.filter(
        Day.truck_id == truck_id,
        Day.date >= start_date,
        Day.date <= end_date,
        Day.fuel == True
    ).all()

    fuel_entry_dates = [entry.date for entry in fuel_entry]
    day_entry_fuel_dates = [entry.date for entry in day_entry_fuel]

    # Count the number of fuel entries
    fuel_entry_count = len(fuel_entry_dates)
    # Count the number of day entries with fuel_flag=True
    day_entry_fuel_count = len(day_entry_fuel_dates)

    # Calculate the difference
    difference = day_entry_fuel_count - fuel_entry_count

    result = {
        "truck_id": truck_id,
        "week_number": week_number,
        "year": year,
        "invoice_flag_count_difference": difference,
        "fuel_entry_count": fuel_entry_count,
        "fuel_flag_count": day_entry_fuel_count,
        "start_date": start_date,
        "end_date": end_date,
        "missing_invoice_dates": [],
    }

    if difference > 0:
        unique_day_entry_fuel_dates = list(set(day_entry_fuel_dates) - set(fuel_entry_dates))
        result["missing_invoice_dates"] = unique_day_entry_fuel_dates
        return result
    else:
        return result

def check_week_for_missing_day_entries_for_date_range(start_date, end_date):
    """
    Checks for missing day entries for each driver between two dates.
    Args:
        start_date: The start date of the date range.
        end_date: The end date of the date range.

    Returns:
        A list of dictionaries containing the driver_id, missing_days, start_date, end_date,
        week_number, and year for each driver with missing day entries.
    """

    results = []

    # Find the first saturday before or on the start date to be the start of week
    adjusted_start_date = find_previous_saturday(start_date)

    # Find the last friday on or after the end_date to be the end of week
    if end_date.weekday() != 4:  # if not friday
        adjusted_end_date = get_next_friday_from_date(end_date)
    else:
        adjusted_end_date = end_date

    # Iterate through each week in the date range
    current_date = adjusted_start_date
    while current_date <= adjusted_end_date:
        year, week_number = get_week_number_sat_to_fri(current_date)

        drivers = Driver.query.all()
        for driver in drivers:
            consistency_check_result = check_week_for_missing_day_entries(driver.id, year, week_number)
            #append the data to the results list
            if consistency_check_result['missing_days'] != []:
                results.append(consistency_check_result)

        # Move to the next week
        current_date += timedelta(days=7)

    return results

def check_week_for_missing_fuel_data_for_date_range(start_date, end_date):
    """
    Checks fuel data consistency for all trucks within a given date range.

    Args:
        start_date: The start date of the range (datetime.date).
        end_date: The end date of the range (datetime.date).

    Returns:
        A list of dictionaries, where each dictionary represents a week and truck 
        combination. Each dictionary contains truck_id, week_number, year and fuel_flag_difference.
    """

    results = []

    # Find the first saturday before or on the start date to be the start of week
    adjusted_start_date = find_previous_saturday(start_date)

    # Find the last friday on or after the end_date to be the end of week
    if end_date.weekday() != 4:  # if not friday
        adjusted_end_date = get_next_friday_from_date(end_date)
    else:
        adjusted_end_date = end_date

    # Iterate through each week in the date range
    current_date = adjusted_start_date
    while current_date <= adjusted_end_date:
        year, week_number = get_week_number_sat_to_fri(current_date)

        trucks = Truck.query.all()
        for truck in trucks:
            consistency_check_result = check_week_for_missing_fuel_data(truck.id, year, week_number)
            #append the data to the results list
            results.append(consistency_check_result)

        # Move to the next week
        current_date += timedelta(days=7)

    return results

def process_missing_day_entries(day_entry_output):

    ten_days_ago = date.today() - timedelta(days=10)

    anomalies_to_add = []
    for data in day_entry_output:
        driver_id = data['driver_id']
        missing_dates = data['missing_days']

        # Fetch Driver object from cache or database
        driver = driver_cache.get(driver_id)
        if not driver:
            driver = Driver.query.get(driver_id)
            driver_cache[driver_id] = driver

        for date_obj in missing_dates:
            # Create a new Anomaly instance
            table_name = TableName.DAY
            anomaly_already_present = MissingEntryAnomaly.query.filter_by(
                date=date_obj, driver_id=driver_id, table_name=table_name
            ).first()

            if not anomaly_already_present and date_obj < ten_days_ago:
                anomaly = MissingEntryAnomaly(
                    date=date_obj,
                    description=f'Missing: Day entry for {driver.full_name} on {display_date_pretty(date_obj)}',
                    driver_id=driver_id,
                    table_name=table_name,
                    is_read=False,
                    is_recurring=False,
                )
                anomalies_to_add.append(anomaly)
            elif anomaly_already_present and anomaly_already_present.isread and not anomaly_already_present.is_recurring:
                try:
                    anomaly_already_present.is_recurring = True
                    db.session.commit()
                except Exception as e:
                    print(f'Error updating anomaly: {e}')
                else:
                    print(f'Success updating anomaly {date_obj}, {driver.full_name}')
        try:
            db.session.add(anomalies_to_add)
            db.session.commit()
        except Exception as e:
            print(f"Error creating anomaly: {e}")
        else:
            print(f'Success entering anomaly {date_obj}, {driver.full_name}')
    print('All fuel entries processed.')

def check_all_missing_day_entries():
    """
    Checks day entry consistency across all available data for all drivers.
    Returns:
        A list of dictionaries, where each dictionary represents a week and driver
        combination with missing day entries. Each dictionary
        contains driver_id, week_number, year, and missing_dates.
    """
    # Find the earliest and latest dates in the Day table.
    min_date_result = Day.query.order_by(Day.date.asc()).first()
    max_date_result = Day.query.order_by(Day.date.desc()).first()

    if not min_date_result or not max_date_result:
        print("No data found in the Day table.")
        return []

    start_date = min_date_result.date
    end_date = max_date_result.date

    # Check day entries for the range
    day_entry_output = check_week_for_missing_day_entries_for_date_range(start_date, end_date)

    return day_entry_output

def check_all_missing_fuel_data():
    """
    Checks fuel data consistency across all available data for all trucks.

    Returns:
        A list of dictionaries, where each dictionary represents a week and truck
        combination with a non-zero fuel_flag_difference. Each dictionary
        contains truck_id, week_number, year, and fuel_flag_difference.
    """

    # Find the earliest and latest dates in the Day table.
    min_date_result = Day.query.order_by(Day.date.asc()).first()
    max_date_result = Day.query.order_by(Day.date.desc()).first()

    if not min_date_result or not max_date_result:
        print("No data found in the Day table.")
        return []

    start_date = min_date_result.date
    end_date = max_date_result.date
    
    #use the function created previously to perform the check for that range.
    all_results = check_week_for_missing_fuel_data_for_date_range(start_date, end_date)
    
    #filter results to only include weeks with differences
    filtered_results = [result for result in all_results if result['missing_invoice_dates'] != []]

    return filtered_results

def process_missing_fuel_data(fuel_consistency_output):

    ten_days_ago = date.today() - timedelta(days=10)
    for data in fuel_consistency_output:
        truck_id = data['truck_id']
        truck = Truck.query.get(truck_id)
        missing_dates = data['missing_invoice_dates']

        for date_obj in missing_dates:
            # Create a new Anomaly instance
            table_name = TableName.FUEL
            anomaly_already_present = MissingEntryAnomaly.query.filter_by(date=date_obj, truck_id=truck_id, table_name=table_name).first()
    
            if not anomaly_already_present and date_obj < ten_days_ago:
                try:
                    anomaly = MissingEntryAnomaly(
                        date=date_obj,
                        description=f'Missing: Fuel Invoice for {truck.registration} on {display_date_pretty(date_obj)}',
                        truck_id=truck_id,
                        table_name=table_name,
                        is_read=False,
                        is_recurring=False,
                    )
                    db.session.add(anomaly)
                    db.session.commit()
                except Exception as e:
                    print(f"Error creating anomaly: {e}")
                else:
                    print(f'Success entering anomaly {date_obj}, {truck.registration}')
            elif not anomaly_already_present:
                pass
            else:
                if not anomaly_already_present.is_read:
                    pass
                else:
                    if not anomaly_already_present.is_recurring:
                        try:
                            anomaly_already_present.is_recurring = True
                            db.session.commit()
                        except Exception as e:
                            print(f'Error updating anomaly: {e}')
                    else:
                        pass
    print('All fuel entries processed.')

def process_missing_payslips(missing_payslips_output):
    """
    Process missing payslips and update the Anomaly table.
    Args:
        missing_payslips_output (dict): Output from find_missing_payslips() function.
    Returns:
        None
    """
    acceptable_days_to_repeat = 25
    today = date.today()
    
    for driver_id, missing_dates in missing_payslips_output.items():
        driver = Driver.query.get(driver_id)
        for date_obj in missing_dates:
            # Check if the entry is already in the database
            table_name = TableName.PAYSLIP
            anomaly_entry = MissingEntryAnomaly.query.filter_by(date=date_obj, driver_id=driver_id, table_name=table_name).first()
            
            # If not in the database, add a new entry
            if not anomaly_entry:
                new_anomaly = MissingEntryAnomaly(
                    date=date_obj,
                    description=f"Missing: PAYSLIP for {driver.full_name.capitalize()} on {display_date_pretty(date_obj)}",
                    driver_id=driver_id,
                    table_name=table_name,
                    is_read=False,
                    is_recurring=False,
                    )
                db.session.add(new_anomaly)
                db.session.commit()
            else:
                # If in the database, check if is_read is False
                if not anomaly_entry.is_read:
                    # If is_read is False, do nothing
                    pass
                else:
                    # If is_read is True, check if is_repeated is False
                    # anomaly_entry_date = anomaly_entry.timestamp.date()
                    # older_than_threshold = anomaly_entry_date < today - timedelta(days=acceptable_days_to_repeat)
                    older_than_threshold = True
                    # If anomaly is recurring, and original entry is older than 25 days, update is_read to False and is_repeated to True
                    if not anomaly_entry.is_recurring and older_than_threshold:
                        anomaly_entry.is_read = False
                        anomaly_entry.is_recurring = True
                        db.session.commit()
                    else:
                        pass
    print("ALL Missing payslips processed")





