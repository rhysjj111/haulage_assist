import datetime
import logging


#functions format to db
def date_to_db(date):
    """Converts a string to a date"""
    return datetime.datetime.strptime(date, "%d/%m/%Y")

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
    
def format_currency(amount, currency="£"):
    """ Formats a number to '£x.xx' from 'x.xx' ready to display to user """
    return f"{currency}{amount:.2f}"

def format_percentage(percentage):
    """ Formats a number from 'xx.xx%' to 'x.xx' ready to display to user """
    return f"{percentage:.0f}%"

def display_float(amount):
    """ Converts a number from integer to float ready to display to user """
    return float(amount/100)

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

# functions for ai_verification
# functions for ai_verification
# def query_to_dict(historical_context, Table):
#     set_name = Table.__tablename__+"_data"
    
#     if historical_context.get(set_name) is None:
#         historical_context[set_name] = {}

#     data_list = []
#     for entry in Table.query.all():
#         data = {
#             column.name: getattr(entry, column.name)
#             for column in Table.__table__.columns
#         }
#         data_list.append(data)
#     historical_context[set_name] = data_list
#     return historical_context

def query_to_dict(historical_context, Table, filter_criteria=None, limit=5000, relevant_attributes=None):
    """
    Fetches and serializes data from a SQLAlchemy table to a dictionary.

    Args:
        historical_context: The dictionary to store the data.
        Table: The SQLAlchemy table model.
        filter_criteria: Optional SQLAlchemy filter criteria (e.g., Table.id > 10).
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
        print(query.count())
        if filter_criteria:
            query = query.filter(filter_criteria)
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
                        data[col_name] = value
                    elif isinstance(value, datetime.date):
                        data[col_name] = value.isoformat()
                    elif isinstance(value, datetime.datetime):
                        data[col_name] = value.isoformat() #Serialize datetime objects as ISO strings
                except AttributeError:
                    logging.exception(f"Warning: Attribute '{col_name}' not found in table '{Table.__tablename__}'.")
                    return None

            historical_context[set_name].append(data)
        return historical_context

    except Exception as e:
        logging.exception(f"Error in query_to_dict: {e}")
        return None