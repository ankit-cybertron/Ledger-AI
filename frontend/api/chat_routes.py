"""
API routes for "Talk to Ledger" — the settlement Q&A chat.

This module is a thin bridge: it stores chat history and hands each
question to `agent.ledger_agent.answer_question`, which does all the
actual reasoning/tool-calling against the read-only settlement data
layer. No Q&A logic lives here.
"""

from flask import Blueprint, jsonify, request

from api import chat_store
from agents.settlement_qa_agent import answer_question

chat_bp = Blueprint("chat", __name__, url_prefix="/api/chat")


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _serialize_session_summary(session):
    return {
        "id": session["id"],
        "title": session["title"],
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "message_count": len(session["messages"]),
    }


@chat_bp.route("/sessions", methods=["GET"])
def get_sessions():
    """Returns list of active chat sessions."""
    sessions = [_serialize_session_summary(s) for s in chat_store.list_sessions()]
    return jsonify({"ok": True, "sessions": sessions})


@chat_bp.route("/sessions", methods=["POST"])
def create_session():
    """Creates a new chat session."""
    session = chat_store.create_session()
    return jsonify({"ok": True, "session": _serialize_session_summary(session)})


@chat_bp.route("/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    """Retrieves chat session details by ID."""
    session = chat_store.get_session(session_id)
    if not session:
        return _error("Chat session not found.", 404)
    return jsonify({"ok": True, "session": session})


@chat_bp.route("/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id):
    """Deletes a chat session by ID."""
    if not chat_store.delete_session(session_id):
        return _error("Chat session not found.", 404)
    return jsonify({"ok": True})


@chat_bp.route("/sessions/<session_id>/messages", methods=["POST"])
def post_message(session_id):
    """Processes user query through Settlement QA Agent and appends response to session history."""
    session = chat_store.get_session(session_id)
    if not session:
        return _error("Chat session not found.", 404)

    payload = request.get_json(silent=True) or {}
    question = (payload.get("message") or "").strip()
    if not question:
        return _error("Message cannot be empty.")

    # History BEFORE this turn — the agent expects prior turns, then
    # appends the new question itself.
    history = chat_store.history_for_agent(session_id)
    chat_store.append_message(session_id, "user", question)

    try:
        reply = answer_question(question, conversation_history=history)
    except RuntimeError as exc:
        # Most likely GROQ_API_KEY isn't set — surface a clear message
        # instead of a raw 500, without leaking internals.
        reply = (
            "Talk to Ledger isn't configured yet on the server "
            f"(configuration error: {exc}). Set GROQ_API_KEY and try again."
        )
    except Exception:
        reply = "I could not safely complete this query. Please try again."

    chat_store.append_message(session_id, "assistant", reply)
    session = chat_store.get_session(session_id)

    return jsonify({
        "ok": True,
        "reply": reply,
        "session": _serialize_session_summary(session),
    })
