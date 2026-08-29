"""
In-memory session store for 'Talk to Ledger' conversation history.
"""

import uuid
from datetime import datetime

import json
from pathlib import Path

def _load_ui_config() -> dict:
    cfg_path = Path(__file__).resolve().parent.parent.parent / "config" / "ui_config.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

TITLE_TRUNCATION_LENGTH = _load_ui_config().get("title_truncation_length", 48)

_SESSIONS = {}  # session_id -> {id, title, created_at, updated_at, messages: [...]}


def create_session():
    """Creates and registers a new chat session."""
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
    """Lists all active chat sessions sorted by latest update timestamp."""
    return sorted(_SESSIONS.values(), key=lambda s: s["updated_at"], reverse=True)


def get_session(session_id):
    """Retrieves a chat session record by ID."""
    return _SESSIONS.get(session_id)


def delete_session(session_id):
    """Deletes a chat session record by ID."""
    return _SESSIONS.pop(session_id, None) is not None


def append_message(session_id, role, content):
    """Appends a message to an active chat session and updates the session title if appropriate."""
    session = _SESSIONS.get(session_id)
    if not session:
        return None

    session["messages"].append({"role": role, "content": content})
    session["updated_at"] = datetime.utcnow().isoformat() + "Z"

    if session["title"] == "New chat" and role == "user":
        title = content.strip().replace("\n", " ")
        max_len = TITLE_TRUNCATION_LENGTH
        session["title"] = (title[:max_len] + "…") if len(title) > max_len else title

    return session


def history_for_agent(session_id):
    """Returns conversation history formatted for LLM agent interaction."""
    session = _SESSIONS.get(session_id)
    if not session:
        return []
    return [{"role": m["role"], "content": m["content"]} for m in session["messages"]]
