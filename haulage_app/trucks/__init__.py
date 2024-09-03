from flask import Blueprint

trucks_bp = Blueprint('api', __name__, url_prefix='/trucks')

from . import routes
