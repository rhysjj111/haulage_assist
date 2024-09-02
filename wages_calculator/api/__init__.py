from flask import Blueprint

api = Blueprint('api', __name__, url_prefix='/api')

# Import API endpoint modules after creating the blueprint
from . import wages, drivers