"""
run.py — Main entrypoint for running the integrated Ledger application.

Usage:
    python run.py
"""

import os
import sys

# Ensure repository root is on sys.path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
if FRONTEND_DIR not in sys.path:
    sys.path.insert(0, FRONTEND_DIR)

# Import the Flask application from frontend/app.py
from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print("=" * 60)
    print("Starting Ledger Web Application...")
    print(f"Open your browser at: http://127.0.0.1:{port}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=True)
