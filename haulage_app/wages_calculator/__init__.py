from flask import Blueprint

wages_calculator_bp = Blueprint('wages_calculator', __name__, url_prefix='/wages_calculator')

from . import routes
