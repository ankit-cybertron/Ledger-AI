"""
pages/dashboard.py — assembles the context dict for templates/dashboard.html.

The Dashboard page's actual reconciliation numbers (auto/manual/
unreconciled counts, transaction rows, exceptions) are fetched
client-side from /api/reconciliation, /api/exceptions, etc. — see
api/routes.py. This module only supplies what the template needs at
render time.
"""


def get_context(username):
    return {
        "username": username,
    }
