from flask import Blueprint

fuel_bp = Blueprint('fuel', __name__, url_prefix='/fuel')

from . import routes
