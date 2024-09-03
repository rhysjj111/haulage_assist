from flask import Blueprint

wages_calculator_bp = Blueprint('api', __name__, url_prefix='/wages_calculator')

from . import routes
