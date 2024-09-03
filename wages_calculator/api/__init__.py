from flask import Blueprint
from flask import jsonify


api_bp = Blueprint('api', __name__, url_prefix='/api')


from . import drivers
# Import API endpoint modules after creating the blueprint
# from . import wages, drivers