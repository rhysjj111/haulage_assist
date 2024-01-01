from datetime import datetime
#functions format to db
def name_to_db(value):
    """ Converts a name to a string which is lowercase with no whitespace at start or end of string """
    return str(value).capitalize().strip()

def currency_to_db(value):
    """ To be used to convert £ to pence to store in the database """
    return float(value)*100

def percentage_to_db(value):
    """ To be used to convert percentages to decimals to store in the database """
    return float(value)/100

#functions format to display on web
def date_to_web(date):
    """ Formats a date to a string for display to the user """
    return datetime.strftime(date, "%d/%m/%Y")
    
def format_currency(amount, currency="£"):
    """ Formats a number to '£x.xx' from 'x.xx' ready to display to user """
    return f"{currency}{amount:.2f}"

def format_percentage(percentage):
    """ Formats a number from 'xx.xx%' to 'x.xx' ready to display to user """
    return f"{percentage:.0f}%"

def currency_to_web(amount):
    """ Formats a number from 'x.xx' to '£x.xx' ready to display to user """
    return float(amount/100)

def percentage_to_web(percentage):
    """ To be used to convert decimals to percentages to store in the database """
    return float((percentage*100))
