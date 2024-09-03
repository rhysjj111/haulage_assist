from flask import Blueprint

drivers_bp = Blueprint('api', __name__, url_prefix='/drivers')

from . import routes
