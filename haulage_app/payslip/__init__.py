from flask import Blueprint

payslip_bp = Blueprint('payslip', __name__, url_prefix='/payslip')

from . import routes
