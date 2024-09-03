from flask import Blueprint

days_bp = Blueprint('api', __name__, url_prefix='/days')

from . import routes
