from flask import Blueprint

payslips_bp = Blueprint('api', __name__, url_prefix='/payslips')

from . import routes
