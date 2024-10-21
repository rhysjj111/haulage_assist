from flask import Blueprint

expense_bp = Blueprint('expense', __name__,url_prefix='/expense', template_folder='../expense/templates/')

from . import routes