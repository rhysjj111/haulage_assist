from flask import Blueprint

verification_bp = Blueprint('verification', __name__, url_prefix='/verification', template_folder='../verification/templates/')
