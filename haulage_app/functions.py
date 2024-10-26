from datetime import datetime


#functions format to db
def date_to_db(date):
    """Converts a string to a date"""
    return datetime.strptime(date, "%d/%m/%Y")

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
    return datetime.strftime(date, "%d/%m/%Y")
    
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

def df_currency(amount):
    return format_currency(display_float(amount))

def df_percentage(percentage):
    return format_percentage(display_percentage(percentage))

