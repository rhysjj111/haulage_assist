import datetime
import logging
import json


#functions format to db
def date_to_db(date):
    """Converts a string to a date, handling both DD/MM/YYYY and YYYY-MM-DD formats."""
    try:
        return datetime.datetime.strptime(date, "%d/%m/%Y").date()
    except ValueError:
        try:
            return datetime.datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            # Raise an exception with a more informative message
            raise ValueError(f"Invalid date format: {date}. Expected DD/MM/YYYY or YYYY-MM-DD") 

def name_to_db(value):
    """ Converts a name to a string which is lowercase with no whitespace at start or end of string """
    return str(value).capitalize().strip()

def float_to_db(value):
    """ To be used to convert floats to integers to store in the database """
    return round(float(value), 2)*100

def percentage_to_db(value):
    """ To be used to convert percentages to floats to store in the database """
    return round(float(value), 2)/100

#functions format to display on web
def display_date(date):
    """ Formats a date to a string for display to the user """
    return datetime.datetime.strftime(date, "%d/%m/%Y")

def display_date_iso(date):
    """Formats a date object to a string in YYYY-MM-DD format for display."""
    return datetime.datetime.strftime(date, "%Y-%m-%d")
    
def format_currency(amount, currency="£"):
    """ Formats a number to '£x.xx' from 'x.xx' ready to display to user """
    return f"{currency}{amount:.2f}"

def format_percentage(percentage):
    """ Formats a number from 'xx.xx%' to 'x.xx' ready to display to user """
    return f"{percentage:.0f}%"

def display_float(amount):
    """ Converts a number from integer to float ready to display to user """
    return float(amount/100)

def display_int(amount):
    """ Converts a number from db integer to integer ready to display to user """
    return int(amount/100)

def display_percentage(percentage):
    """ To be used to convert floats to percentages to store in the database """
    return float((percentage*100))

def fd_currency(amount):
    return format_currency(display_float(amount))

def fd_percentage(percentage):
    return format_percentage(display_percentage(percentage))

#functions for calculations

def get_week_number_sat_to_fri(date):
    """Returns the week number with Saturday as the start of the week."""
    """Returns a tuple of (year, week_number) with Saturday as week start."""
    adjusted_date = date - datetime.timedelta(days=2)
    year = adjusted_date.year
    week = adjusted_date.isocalendar().week
    return (year, week)

def get_saturday_to_friday_week_number_string(date):
    day_of_week = date.weekday()  # 0 for Monday, 6 for Sunday
    adjusted_date = date + datetime.timedelta(days=(day_of_week + 2) % 7)
    return int(adjusted_date.strftime('%W'))

def get_start_of_week(year, week_number):
    """Returns the start date of the week."""
    # Get January 1st of selected year
    year_start = datetime.date(year, 1, 1)
    # Calculate offset to previous Saturday
    saturday_offset = (year_start.weekday() + 2) % 7
    # Calculate days to add for desired week
    week_offset = (week_number - 1) * 7
    # Calculate final start date
    start_date = year_start + datetime.timedelta(days=week_offset - saturday_offset)
    return start_date

def get_start_end_of_week(year, week_number):
    """Returns the start and end dates of the week."""
    # Calculate the start date of the week
    start_date = get_start_of_week(year, week_number)
    # Calculate the end date of the week
    end_date = start_date + datetime.timedelta(days=6)
    return start_date, end_date

def get_weeks_for_period(day_query):
    """Returns a list of week numbers for the given period."""
    # Calculate week numbers for each day
    week_numbers = [get_week_number_sat_to_fri(day.date) for day in day_query]
    # Get unique week numbers
    available_weeks = sorted(set(week_numbers), reverse=True)
    return available_weeks

# functions for verification

def query_to_dict(historical_context, Table, filter_criteria=None, limit=5000, relevant_attributes=None):
    """
    Fetches and serializes data from a SQLAlchemy table to a dictionary.

    Args:
        historical_context: The dictionary to store the data.
        Table: The SQLAlchemy table model.
        filter_criteria: Optional SQLAlchemy filter criteria (e.g., (Table.id > 10,)), must be a tuple.
        limit: The maximum number of rows to fetch (to avoid excessive data).
        relevant_attributes: Optional list of attribute names to include in the dictionary.

    Returns:
        The updated historical_context dictionary.  Returns None on error.
    """
    set_name = Table.__tablename__ + "_data"
    if historical_context.get(set_name) is None:
        historical_context[set_name] = []

    try:
        query = Table.query
        if filter_criteria is not None:
            query = query.filter(*filter_criteria)
        if hasattr(Table, 'date'): #Check if 'date' column exists
            query = query.order_by(Table.date.desc()) #Order by date if it exists.
        query = query.limit(limit)  # Limit to avoid large data

        for entry in query.all():
            data = {}
            if relevant_attributes is None:
                attributes_to_include = [col.name for col in Table.__table__.columns]
            else:
                attributes_to_include = relevant_attributes
            
            for col_name in attributes_to_include:
                try:
                    value = getattr(entry, col_name)
                    if isinstance(value, (str, int, float, bool, type(None))):
                        if col_name == 'id':
                            # Prefix table id (payslip_id)
                            data[f"{Table.__tablename__}_id"] = value
                        elif col_name == 'fuel':
                            # Distinguish fuel field in day from fuel_data.
                            data["fuel_flag"] = value
                        elif col_name in ['start_mileage', 'end_mileage']:
                            data[col_name] = display_int(value)
                        else:
                            data[col_name] = value
                    elif isinstance(value, datetime.date):
                        data[col_name] = value.isoformat()
                    elif isinstance(value, datetime.datetime):
                        data[col_name] = value.isoformat() #Serialize datetime objects as ISO strings
                except AttributeError:
                    logging.exception(f"Warning: Attribute '{col_name}' not found in table '{Table.__tablename__}'.")
                    return None

            historical_context[set_name].append(data)
        return json.loads(json.dumps(historical_context))

    except Exception as e:
        logging.exception(f"Error in query_to_dict: {e}")
        return None


def is_within_acceptable_date_range(suggested_date: datetime.date, start_date: datetime.date) -> bool:
    """
    Checks if a suggested date is within an acceptable range.

    The acceptable range is defined as:
    - Not between today and one week (7 days) ago (exclusive).
    - Not older than the specified start_date.

    Args:
        suggested_date: The date suggested by the AI.
        start_date: The oldest acceptable date.

    Returns:
        True if the suggested date is within the acceptable range, False otherwise.
    """
    today = datetime.date.today()
    # one_week_ago = today - datetime.timedelta(days=7)
    one_week_ago = datetime.date(2024, 12, 20)

    return start_date <= suggested_date <= one_week_ago
