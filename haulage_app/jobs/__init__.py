from flask import Blueprint

jobs_bp = Blueprint('api', __name__, url_prefix='/jobs')

from . import routes
