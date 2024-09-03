from flask import Blueprint

fuel_bp = Blueprint('api', __name__, url_prefix='/fuel')

from . import routes
