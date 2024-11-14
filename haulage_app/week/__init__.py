from flask import Blueprint

week_bp = Blueprint('week', __name__, url_prefix='/week', template_folder='../week/templates/')

from . import routes
