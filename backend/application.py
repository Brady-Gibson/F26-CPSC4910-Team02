import os

from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import mysql.connector

load_dotenv()

application = Flask(__name__)
CORS(application)


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", 3306))
    )


@application.route("/")
def home():
    return "Team 02 Flask backend is running!"


@application.route("/api/about")
def about():
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                team_number,
                version_number,
                release_date,
                product_name,
                product_description
            FROM ABOUT_RELEASE
            WHERE team_number = 2
            ORDER BY release_id DESC
            LIMIT 1
        """)

        result = cursor.fetchone()

        if result is None:
            return jsonify({"error": "No Team 02 release found"}), 404

        return jsonify(result)

    except mysql.connector.Error as error:
        return jsonify({"error": str(error)}), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


if __name__ == "__main__":
    application.run(debug=True)