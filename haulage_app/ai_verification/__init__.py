from flask import Blueprint

ai_verification_bp = Blueprint('ai_verification', __name__, url_prefix='/ai_verification', template_folder='../ai_verification/templates/')

from . import routes