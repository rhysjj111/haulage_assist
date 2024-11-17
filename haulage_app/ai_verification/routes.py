from flask import render_template, request, url_for
from haulage_app import db, ai
from haulage_app.ai_verification.models import VerificationFeedback
from datetime import timedelta, date, datetime
from haulage_app.ai_verification import ai_verification_bp
from haulage_app.notification.models import Notification