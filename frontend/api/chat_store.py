"""
In-memory store for chat sessions ("Talk to Ledger" history).

TODO: replace with real persistence (a table keyed by user id) once
there's more than one hardcoded admin account. Right now everything
lives in process memory and resets on server restart — fine for
frontend development, not for production.
"""

import uuid
from datetime import datetime

_SESSIONS = {}  # session_id -> {id, title, created_at, updated_at, messages: [...]}


def create_session():
    session_id = uuid.uuid4().hex
    now = datetime.utcnow().isoformat() + "Z"
    record = {
        "id": session_id,
        "title": "New chat",
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }
    _SESSIONS[session_id] = record
    return record


def list_sessions():
    return sorted(_SESSIONS.values(), key=lambda s: s["updated_at"], reverse=True)


def get_session(session_id):
    return _SESSIONS.get(session_id)


def delete_session(session_id):
    return _SESSIONS.pop(session_id, None) is not None


def append_message(session_id, role, content):
    session = _SESSIONS.get(session_id)
    if not session:
        return None

    session["messages"].append({"role": role, "content": content})
    session["updated_at"] = datetime.utcnow().isoformat() + "Z"

    # Auto-title the chat from the first user message, like Claude/ChatGPT do.
    if session["title"] == "New chat" and role == "user":
        title = content.strip().replace("\n", " ")
        session["title"] = (title[:48] + "…") if len(title) > 48 else title

    return session


def history_for_agent(session_id):
    """Return the session's messages in the {role, content} shape the
    agent's `conversation_history` argument expects."""
    session = _SESSIONS.get(session_id)
    if not session:
        return []
    return [{"role": m["role"], "content": m["content"]} for m in session["messages"]]
