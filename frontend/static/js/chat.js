/**
 * chat.js
 *
 * Talk to Ledger — full chat UI with persistent, server-backed history
 * (a session list in the sidebar, like Claude/ChatGPT), backed by
 * /api/chat/sessions/*. All grounding, tool-calling, and reasoning
 * happens server-side in agent/ledger_agent.py (Groq + the read-only
 * settlement_qa tools) — this file only renders sessions/messages and
 * calls LedgerApi. No Q&A logic is duplicated here.
 */

(function () {
  "use strict";

  let sessions = [];
  let activeSessionId = null;
  let sending = false;

  const GREETING_HTML =
    "Welcome to Ledger AI. I can analyze settlements, match bank transactions, and summarize reconciliation exceptions. How can I help you today?";

  function el(html) {
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    return template.content.firstChild;
  }

  function scrollToBottom(container) {
    container.scrollTop = container.scrollHeight;
  }

  // Very small, safe-ish markdown handling for the agent's replies: escapes
  // HTML first, then turns fenced markdown tables and **bold** into markup.
  // This is presentation only — it doesn't interpret or act on the content.
  function escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function renderMarkdownish(text) {
    const escaped = escapeHtml(text);
    const lines = escaped.split("\n");
    let html = "";
    let inTable = false;
    let tableRows = [];

    const flushTable = () => {
      if (tableRows.length === 0) return;
      const [headerLine, , ...bodyLines] = tableRows;
      const headers = headerLine.split("|").map((c) => c.trim()).filter(Boolean);
      html += "<table><thead><tr>" + headers.map((h) => `<th>${h}</th>`).join("") + "</tr></thead><tbody>";
      bodyLines.forEach((row) => {
        const cells = row.split("|").map((c) => c.trim()).filter(Boolean);
        if (cells.length === 0) return;
        html += "<tr>" + cells.map((c) => `<td>${c}</td>`).join("") + "</tr>";
      });
      html += "</tbody></table>";
      tableRows = [];
    };

    lines.forEach((line) => {
      const isTableLine = /^\s*\|.*\|\s*$/.test(line);
      if (isTableLine) {
        inTable = true;
        tableRows.push(line.trim());
        return;
      }
      if (inTable && !isTableLine) {
        flushTable();
        inTable = false;
      }
      const bolded = line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      html += bolded + "\n";
    });
    if (inTable) flushTable();

    return html.trim();
  }

  function appendMessage(role, content) {
    const container = document.getElementById("chatMessages");
    const roleClass = role === "user" ? "chat-msg-user" : role === "error" ? "chat-msg-error" : "chat-msg-agent";
    const bubbleHtml = role === "user" ? escapeHtml(content) : renderMarkdownish(content);
    const node = el(`<div class="chat-msg ${roleClass}"><div class="chat-bubble">${bubbleHtml}</div></div>`);
    container.appendChild(node);
    scrollToBottom(container);
    return node;
  }

  function appendTyping() {
    const container = document.getElementById("chatMessages");
    const node = el(
      '<div class="chat-msg chat-msg-agent" id="typingIndicator"><div class="chat-bubble"><span class="chat-typing"><span></span><span></span><span></span></span></div></div>'
    );
    container.appendChild(node);
    scrollToBottom(container);
    return node;
  }

  function clearMessages() {
    document.getElementById("chatMessages").innerHTML = "";
  }

  function showGreeting() {
    clearMessages();
    appendMessage("agent", GREETING_HTML);
  }

  // ------------------------------------------------------------------
  // Session list (sidebar)
  // ------------------------------------------------------------------

  function renderSessionList() {
    const list = document.getElementById("chatSessionList");
    list.innerHTML = "";

    if (sessions.length === 0) {
      list.appendChild(el('<div class="chat-session-empty">No conversations yet</div>'));
      return;
    }

    sessions.forEach((session) => {
      const item = el(`
        <div class="chat-session-item ${session.id === activeSessionId ? "active" : ""}" data-session-id="${session.id}">
          <svg class="chat-session-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <span class="chat-session-title">${escapeHtml(session.title || "New chat")}</span>
          <button type="button" class="chat-session-delete" aria-label="Delete chat" title="Delete chat">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
      `);

      item.addEventListener("click", (e) => {
        if (e.target.closest(".chat-session-delete")) return;
        openSession(session.id);
      });

      item.querySelector(".chat-session-delete").addEventListener("click", async (e) => {
        e.stopPropagation();
        await deleteSession(session.id);
      });

      list.appendChild(item);
    });
  }

  async function refreshSessionList() {
    try {
      const result = await window.LedgerApi.getChatSessions();
      sessions = result.sessions || [];
      renderSessionList();
    } catch (_) {
      // Leave whatever was last rendered.
    }
  }

  async function openSession(sessionId) {
    activeSessionId = sessionId;
    renderSessionList();

    const popover = document.getElementById("chatHistoryPopover");
    if (popover) popover.classList.remove("open");

    try {
      const result = await window.LedgerApi.getChatSession(sessionId);
      const messages = result.session.messages || [];
      clearMessages();
      if (messages.length === 0) {
        showGreeting();
      } else {
        messages.forEach((m) => appendMessage(m.role === "user" ? "user" : "agent", m.content));
      }
    } catch (_) {
      showGreeting();
    }
  }

  async function startNewSession() {
    try {
      const result = await window.LedgerApi.createChatSession();
      sessions.unshift(result.session);
      activeSessionId = result.session.id;
      renderSessionList();
      showGreeting();
      const popover = document.getElementById("chatHistoryPopover");
      if (popover) popover.classList.remove("open");
    } catch (_) {
      alert("Could not start a new chat. Please try again.");
    }
  }

  async function deleteSession(sessionId) {
    try {
      await window.LedgerApi.deleteChatSession(sessionId);
      sessions = sessions.filter((s) => s.id !== sessionId);

      if (sessionId === activeSessionId) {
        activeSessionId = null;
        if (sessions.length > 0) {
          await openSession(sessions[0].id);
        } else {
          clearMessages();
          showGreeting();
        }
      }
      renderSessionList();
    } catch (_) {
      alert("Could not delete this chat. Please try again.");
    }
  }

  // ------------------------------------------------------------------
  // Sending messages
  // ------------------------------------------------------------------

  async function ensureActiveSession() {
    if (activeSessionId) return activeSessionId;
    const result = await window.LedgerApi.createChatSession();
    sessions.unshift(result.session);
    activeSessionId = result.session.id;
    renderSessionList();
    return activeSessionId;
  }

  async function sendMessage(text) {
    if (!text.trim() || sending) return;
    sending = true;

    const input = document.getElementById("chatInput");
    const sendBtn = document.getElementById("chatSendBtn");
    input.value = "";
    sendBtn.disabled = true;

    try {
      const sessionId = await ensureActiveSession();

      appendMessage("user", text);
      const typingNode = appendTyping();

      const result = await window.LedgerApi.sendChatMessage(sessionId, text);
      typingNode.remove();
      appendMessage("agent", result.reply);

      // Refresh sidebar so the auto-generated title / ordering updates.
      await refreshSessionList();
    } catch (err) {
      const typingNode = document.getElementById("typingIndicator");
      if (typingNode) typingNode.remove();
      const message = err instanceof window.ApiError ? err.message : "Something went wrong reaching the agent.";
      appendMessage("error", message);
    } finally {
      sending = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  // ------------------------------------------------------------------
  // Init
  // ------------------------------------------------------------------

  async function initChat() {
    const form = document.getElementById("chatForm");
    const input = document.getElementById("chatInput");

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      sendMessage(input.value);
    });

    document.querySelectorAll(".chat-suggestion").forEach((btn) => {
      btn.addEventListener("click", () => sendMessage(btn.textContent));
    });

    const newChatBtn = document.getElementById("newChatBtn");
    if (newChatBtn) newChatBtn.addEventListener("click", startNewSession);

    const toggleBtn = document.getElementById("chatHistoryToggleBtn");
    const closeBtn = document.getElementById("chatHistoryCloseBtn");
    const popover = document.getElementById("chatHistoryPopover");

    if (toggleBtn && popover) {
      toggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        popover.classList.toggle("open");
      });
    }

    if (closeBtn && popover) {
      closeBtn.addEventListener("click", () => {
        popover.classList.remove("open");
      });
    }

    document.addEventListener("click", (e) => {
      if (popover && !popover.contains(e.target) && toggleBtn && !toggleBtn.contains(e.target)) {
        popover.classList.remove("open");
      }
    });

    await refreshSessionList();
    if (sessions.length > 0) {
      await openSession(sessions[0].id);
    } else {
      showGreeting();
    }
  }

  document.addEventListener("DOMContentLoaded", initChat);
})();
