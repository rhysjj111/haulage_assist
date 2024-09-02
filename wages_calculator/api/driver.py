from flask import jsonify
from wages_calculator.models import Driver
from . import api  # Import the api blueprint

@api.route('/drivers', methods=['GET'])
def get_drivers():
    drivers = Driver.query.all()
    driver_list = [{'id': driver.id, 'name': driver.full_name} for driver in drivers]
    return jsonify(driver_list)