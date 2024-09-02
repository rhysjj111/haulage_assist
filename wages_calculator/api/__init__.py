from flask import Blueprint

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('drivers', methods=['GET'])
def get_drivers():
    drivers = Driver.query.all()
    driver_list = [{'id': driver.id, 'name': driver.full_name} for driver in drivers]
    return jsonify(driver_list)

# Import API endpoint modules after creating the blueprint
# from . import wages, drivers