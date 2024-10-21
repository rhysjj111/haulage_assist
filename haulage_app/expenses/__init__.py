from flask import Blueprint

expenses_bp = Blueprint('expenses', __name__,url_prefix='/expenses', template_folder='../expenses/templates/')

from . import routes