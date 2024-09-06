from flask import Blueprint

truck_bp = Blueprint('truck', __name__, url_prefix='/truck')

from . import routes
