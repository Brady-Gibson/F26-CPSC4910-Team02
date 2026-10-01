"""Team 02 Flask backend. Run: python application.py   then open http://localhost:5000

Keep the file name application.py and the variable name `application`:
AWS Elastic Beanstalk looks for exactly that by default.
"""
import os
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()  # must run before importing modules that read env vars

import mysql.connector
from flask import Flask, jsonify, request
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS

import auth
from db import query
from routes import dev

IS_PROD = os.getenv("APP_ENV", "development") == "production"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Pages live in ../frontend in the repo, and in ./frontend inside the Beanstalk deploy zip
_frontend_options = [os.getenv("FRONTEND_DIR"), os.path.join(BASE_DIR, "..", "frontend"), os.path.join(BASE_DIR, "frontend")]
FRONTEND_DIR = next((os.path.abspath(p) for p in _frontend_options if p and os.path.isdir(p)),
                    os.path.join(BASE_DIR, "frontend"))


class Team02JSON(DefaultJSONProvider):
    """Send DATETIME as 'YYYY-MM-DD HH:MM:SS' and DECIMAL as a number (Flask's defaults break the front end)."""
    @staticmethod
    def default(o):
        if isinstance(o, datetime):
            return o.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        return DefaultJSONProvider.default(o)


# Serves the pages in ../frontend, so /login.html, /driver/dashboard.html, etc. all work
application = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
application.json = Team02JSON(application)

secret = os.getenv("SECRET_KEY")
if not secret:
    if IS_PROD:
        raise RuntimeError("SECRET_KEY must be set in production")
    secret = secrets.token_hex(32)
    print("WARNING: SECRET_KEY not set; using a temporary one. Everyone gets signed out when the server restarts.")

application.config.update(
    SECRET_KEY=secret,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PROD,  # HTTPS-only cookie once deployed
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

# Only needed if the pages are served from somewhere other than this Flask app
CORS(application, resources={r"/api/*": {"origins": os.getenv("CORS_ORIGINS", "http://localhost:5000").split(",")}},
     supports_credentials=True)

application.register_blueprint(auth.bp)
application.register_blueprint(dev.bp)

# Role routes: uncomment your two lines when you add your routes file.
from routes import driver
application.register_blueprint(driver.bp)
from routes import sponsor
application.register_blueprint(sponsor.bp)
from routes import admin
application.register_blueprint(admin.bp)


@application.route("/")
def home():
    return application.send_static_file("index.html")  # redirects to login.html


@application.route("/api/health")
def health():
    row = query("SELECT NOW() AS db_time, DATABASE() AS db_name", one=True)
    return jsonify(ok=True, message="Team 02 Flask backend is running!", **row)


@application.route("/api/about")
def about():
    result = query(
        """SELECT team_number, version_number, release_date, product_name, product_description
             FROM ABOUT_RELEASE
            WHERE team_number = 2
            ORDER BY release_id DESC
            LIMIT 1""", one=True)
    if result is None:
        return jsonify(error="No Team 02 release found"), 404
    return jsonify(result)


@application.errorhandler(mysql.connector.Error)
def db_error(error):
    application.logger.exception("Database error")
    return jsonify(error="Database error" if IS_PROD else str(error)), 500


@application.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify(error="Not found"), 404
    return error


if __name__ == "__main__":
    application.run(debug=not IS_PROD)
