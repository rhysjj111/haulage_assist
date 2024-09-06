from flask import Blueprint

job_bp = Blueprint('job', __name__, url_prefix='/job')

from . import routes
