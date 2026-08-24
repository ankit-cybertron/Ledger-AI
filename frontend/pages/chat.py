"""
pages/chat.py — assembles the context dict for templates/chat.html.

Chat sessions/messages are fetched client-side from /api/chat/* — see
api/chat_routes.py and api/chat_store.py. This module only supplies
what the template needs at render time.
"""


def get_context(username):
    return {
        "username": username,
    }
