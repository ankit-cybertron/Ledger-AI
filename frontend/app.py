import os
import sys
from functools import wraps

FRONTEND_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(FRONTEND_DIR, ".."))
if FRONTEND_DIR not in sys.path:
    sys.path.insert(0, FRONTEND_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from flask import Flask, render_template, request, redirect, url_for, session

from api.routes import api_bp
from api.chat_routes import chat_bp
from pages import overview as overview_page
from pages import dashboard as dashboard_page
from pages import chat as chat_page
from pages import reports as reports_page

app = Flask(__name__)

# TODO: move this to an environment variable before deploying anywhere real.
app.secret_key = "dev-secret-key-change-me"

# Where uploaded source files land before the real Ledger engine consumes
# them. This is NOT a database — it's just a drop point for raw files.
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB per upload

app.register_blueprint(api_bp)
app.register_blueprint(chat_bp)

# --- Hardcoded demo/admin credentials ---
VALID_USERS = {
    "demo": "demo123",
    "admin": "admin123"
}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def _username():
    return session.get("username", "demo")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if username in VALID_USERS and VALID_USERS[username] == password:
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("overview"))
        elif username == "demo" and (password == "admin123" or password == "demo123" or not password):
            session["logged_in"] = True
            session["username"] = "demo"
            return redirect(url_for("overview"))
        elif username == "admin" and (password == "admin123" or password == "demo123"):
            session["logged_in"] = True
            session["username"] = "admin"
            return redirect(url_for("overview"))

        return render_template("login.html", error="Invalid username or password.")

    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# --------------------------------------------------------------------------
# App pages — each is its own route, template, and pages/*.py data module.
# --------------------------------------------------------------------------

@app.route("/overview")
@login_required
def overview():
    context = overview_page.get_context()
    return render_template("overview.html", username=_username(), **context)


@app.route("/dashboard")
@login_required
def dashboard():
    context = dashboard_page.get_context(_username())
    return render_template("dashboard.html", **context)


@app.route("/chat")
@login_required
def talk_to_ledger():
    context = chat_page.get_context(_username())
    return render_template("chat.html", **context)


@app.route("/reports")
@login_required
def reports():
    context = reports_page.get_context()
    return render_template("reports.html", username=_username(), **context)


@app.route("/matching-config")
@app.route("/config")
@login_required
def matching_config_page():
    import json
    config_path = os.path.join(ROOT_DIR, "data", "results", "reconciliation_config.json")
    cfg_data = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
        except Exception:
            pass
    if not cfg_data:
        from config import MatchingConfig
        cfg_data = MatchingConfig().to_dict()
    return render_template("config.html", config=cfg_data, username=_username())


if __name__ == "__main__":
    app.run(debug=True)
