from flask import Blueprint

day_bp = Blueprint('day', __name__, url_prefix='/day')

from . import routes
