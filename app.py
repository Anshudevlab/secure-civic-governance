
import csv
import io
import os
import secrets
import sqlite3
from pathlib import Path
from functools import wraps
from datetime import datetime, timezone

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    session,
    redirect,
    url_for,
    make_response,
)
from werkzeug.security import check_password_hash


# --------------------------------------------------
# APP CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

secret_key = os.environ.get("CIVIC_SECRET_KEY")

if not secret_key:
    raise RuntimeError(
        "CIVIC_SECRET_KEY is missing. Set it in PowerShell before starting Flask."
    )

app.config["SECRET_KEY"] = secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False  # Local HTTP development only

ADMIN_USERNAME = os.environ.get("CIVIC_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.environ.get("CIVIC_ADMIN_PASSWORD_HASH", "")

CATEGORIES = [
    "Roads and Transport",
    "Water Supply",
    "Electricity",
    "Waste Management",
    "Public Safety",
    "Other",
]

STATUSES = ["Submitted", "In Progress", "Resolved"]


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def get_db():
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS grievances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT UNIQUE NOT NULL,
                citizen_name TEXT NOT NULL,
                category TEXT NOT NULL,
                location TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Submitted',
                created_at TEXT NOT NULL
            )
        """)

        # Add created_at to older databases, if necessary.
        columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(grievances)").fetchall()
        }

        if "created_at" not in columns:
            db.execute(
                "ALTER TABLE grievances ADD COLUMN created_at TEXT"
            )
            db.execute("""
                UPDATE grievances
                SET created_at = ?
                WHERE created_at IS NULL
            """, (datetime.now(timezone.utc).isoformat(timespec="seconds"),))

        db.commit()


# --------------------------------------------------
# SECURITY HELPERS
# --------------------------------------------------

def csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]


def valid_csrf_token():
    submitted = request.form.get("csrf_token", "")
    stored = session.get("_csrf_token", "")

    return bool(
        submitted
        and stored
        and secrets.compare_digest(submitted, stored)
    )


app.jinja_env.globals["csrf_token"] = csrf_token


def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Admin login required."}), 401

            return redirect(url_for("admin_login"))

        return function(*args, **kwargs)

    return wrapper


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


# --------------------------------------------------
# CITIZEN HOME PAGE
# --------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# --------------------------------------------------
# ADMIN LOGIN
# --------------------------------------------------

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    error = None

    if request.method == "POST":
        if not valid_csrf_token():
            return render_template(
                "admin.html",
                error="Your session expired. Refresh the page and try again."
            ), 400

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        username_ok = secrets.compare_digest(
            username,
            ADMIN_USERNAME
        )

        password_ok = False

        if ADMIN_PASSWORD_HASH:
            try:
                password_ok = check_password_hash(
                    ADMIN_PASSWORD_HASH,
                    password
                )
            except (ValueError, TypeError):
                password_ok = False

        if username_ok and password_ok:
            session.clear()
            session["admin_logged_in"] = True
            session["_csrf_token"] = secrets.token_urlsafe(32)
            return redirect(url_for("admin_dashboard"))

        error = "Invalid username or password."

    return render_template("admin.html", error=error)


# --------------------------------------------------
# ADMIN DASHBOARD
# --------------------------------------------------

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    with get_db() as db:
        grievances = db.execute("""
            SELECT
                id,
                reference,
                citizen_name,
                category,
                location,
                description,
                status,
                created_at
            FROM grievances
            ORDER BY id DESC
        """).fetchall()

    total = len(grievances)
    submitted = sum(g["status"] == "Submitted" for g in grievances)
    in_progress = sum(g["status"] == "In Progress" for g in grievances)
    resolved = sum(g["status"] == "Resolved" for g in grievances)

    category_counts = {}

    for category in CATEGORIES:
        category_counts[category] = sum(
            g["category"] == category for g in grievances
        )

    return render_template(
        "dashboard.html",
        grievances=grievances,
        total=total,
        submitted=submitted,
        in_progress=in_progress,
        resolved=resolved,
        category_counts=category_counts,
        statuses=STATUSES,
    )


# --------------------------------------------------
# UPDATE GRIEVANCE STATUS
# --------------------------------------------------

@app.route("/admin/update-status", methods=["POST"])
@admin_required
def update_status():
    if not valid_csrf_token():
        return "Invalid or expired security token. Refresh the dashboard.", 400

    reference = request.form.get("reference", "").strip().upper()
    new_status = request.form.get("status", "").strip()

    if not reference or new_status not in STATUSES:
        return "Invalid grievance reference or status.", 400

    with get_db() as db:
        result = db.execute("""
            UPDATE grievances
            SET status = ?
            WHERE reference = ?
        """, (new_status, reference))

        db.commit()

        if result.rowcount == 0:
            return "Grievance not found.", 404

    return redirect(url_for("admin_dashboard"))


# --------------------------------------------------
# EXPORT GRIEVANCES AS CSV
# --------------------------------------------------

@app.route("/admin/export")
@admin_required
def export_grievances():
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Reference",
        "Citizen Name",
        "Category",
        "Location",
        "Description",
        "Status",
        "Created At",
    ])

    with get_db() as db:
        rows = db.execute("""
            SELECT
                reference,
                citizen_name,
                category,
                location,
                description,
                status,
                created_at
            FROM grievances
            ORDER BY id DESC
        """).fetchall()

    for row in rows:
        writer.writerow([
            row["reference"],
            row["citizen_name"],
            row["category"],
            row["location"],
            row["description"],
            row["status"],
            row["created_at"],
        ])

    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        "attachment; filename=secure_civic_grievances.csv"
    )

    return response


# --------------------------------------------------
# ADMIN LOGOUT
# --------------------------------------------------

@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():
    if not valid_csrf_token():
        return "Invalid or expired security token. Refresh the page.", 400

    session.clear()
    return redirect(url_for("admin_login"))


# --------------------------------------------------
# SUBMIT A CITIZEN GRIEVANCE
# --------------------------------------------------

@app.route("/api/grievances", methods=["POST"])
def create_grievance():
    if not request.is_json:
        return jsonify({
            "error": "Please submit the grievance using the correct form."
        }), 415

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Invalid request data."}), 400

    citizen_name = str(data.get("citizenName", "")).strip()
    category = str(data.get("category", "")).strip()
    location = str(data.get("location", "")).strip()
    description = str(data.get("description", "")).strip()

    if not all([citizen_name, category, location, description]):
        return jsonify({"error": "Please complete all required fields."}), 400

    if len(citizen_name) > 80:
        return jsonify({"error": "Citizen name is too long."}), 400

    if len(location) > 150:
        return jsonify({"error": "Location is too long."}), 400

    if len(description) > 2000:
        return jsonify({"error": "Description must be 2000 characters or fewer."}), 400

    if category not in CATEGORIES:
        return jsonify({"error": "Please select a valid category."}), 400

    reference = secrets.token_hex(4).upper()
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        with get_db() as db:
            db.execute("""
                INSERT INTO grievances (
                    reference,
                    citizen_name,
                    category,
                    location,
                    description,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, 'Submitted', ?)
            """, (
                reference,
                citizen_name,
                category,
                location,
                description,
                created_at,
            ))
            db.commit()

    except sqlite3.Error:
        app.logger.exception("Unable to save grievance")
        return jsonify({
            "error": "The grievance could not be saved. Please try again."
        }), 500

    return jsonify({
        "message": "Grievance submitted successfully.",
        "reference": reference,
        "status": "Submitted",
    }), 201


# --------------------------------------------------
# TRACK GRIEVANCE STATUS
# --------------------------------------------------

@app.route("/api/grievances/<reference>", methods=["GET"])
def track_grievance(reference):
    reference = reference.strip().upper()

    with get_db() as db:
        grievance = db.execute("""
            SELECT reference, category, location, status, created_at
            FROM grievances
            WHERE reference = ?
        """, (reference,)).fetchone()

    if grievance is None:
        return jsonify({"error": "No grievance found with that reference."}), 404

    return jsonify({
        "reference": grievance["reference"],
        "category": grievance["category"],
        "location": grievance["location"],
        "status": grievance["status"],
        "created_at": grievance["created_at"],
    }), 200


# --------------------------------------------------
# ERROR HANDLERS
# --------------------------------------------------

@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "The requested resource was not found."}), 404

    return "Page not found.", 404


@app.errorhandler(500)
def server_error(error):
    app.logger.exception("Unexpected server error")
    if request.path.startswith("/api/"):
        return jsonify({"error": "An internal server error occurred."}), 500

    return "An internal server error occurred. Check the Flask terminal.", 500


# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=8080, debug=True)
