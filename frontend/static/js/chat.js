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

  let chartCounter = 0;

  function extractChartDataFromTable(headers, rows) {
    const labels = [];
    const values = [];
    const colors = [];

    const colorMap = {
      SETTLED: "#10b981",
      MATCHED: "#3b82f6",
      SIMILAR: "#f59e0b",
      UNMATCHED: "#ef4444",
      EXCEPTION: "#ef4444",
    };

    const fallbackPalette = [
      "#3b82f6", // Vibrant Blue
      "#10b981", // Emerald Green
      "#8b5cf6", // Purple
      "#f59e0b", // Amber Gold
      "#ec4899", // Bright Pink
      "#06b6d4", // Cyan
      "#f97316", // Orange
      "#6366f1", // Indigo
      "#14b8a6", // Mint
      "#e11d48", // Rose Red
    ];

    rows.forEach((r) => {
      if (r.length >= 2) {
        const labelStr = r[0].replace(/<[^>]*>/g, "").replace(/[*_`]/g, "").trim();
        const rawVal = r[1].replace(/<[^>]*>/g, "").replace(/[^0-9.-]/g, "");
        const val = parseFloat(rawVal);
        if (labelStr && !isNaN(val) && val >= 0) {
          labels.push(labelStr);
          values.push(val);

          const upperLabel = labelStr.toUpperCase();
          let c = null;
          for (const [k, hex] of Object.entries(colorMap)) {
            if (upperLabel.includes(k)) {
              c = hex;
              break;
            }
          }
          if (!c) {
            c = fallbackPalette[colors.length % fallbackPalette.length];
          }
          colors.push(c);
        }
      }
    });

    if (labels.length >= 2 && values.some((v) => v > 0)) {
      return { labels, values, colors };
    }
    return null;
  }

  function initChatChart(canvasId, info) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !window.Chart) return;
    try {
      new window.Chart(canvas, {
        type: "doughnut",
        data: {
          labels: info.labels,
          datasets: [
            {
              data: info.values,
              backgroundColor: info.colors,
              borderWidth: 2,
              borderColor: "#111418",
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: "right",
              labels: { color: "#94a3b8", font: { size: 11, weight: "600" } },
            },
          },
          cutout: "65%",
        },
      });
    } catch (_) {}
  }

  function renderMarkdownish(text) {
    if (!text) return "";
    let escaped = escapeHtml(text);

    // 1. Label General vs Grounded AI answers (T23.1 Safety requirement)
    escaped = escaped.replace(
      /General answer &mdash; not verified against your ledger data/gi,
      '<div class="chat-callout callout-general"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> <span><strong>General answer</strong> — not verified against your ledger data</span></div>'
    );
    escaped = escaped.replace(
      /General answer — not verified against your ledger data/gi,
      '<div class="chat-callout callout-general"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> <span><strong>General answer</strong> — not verified against your ledger data</span></div>'
    );

    // 2. Format status keywords into colored badges
    escaped = escaped.replace(/\b(SETTLED)\b/g, '<span class="badge-status badge-settled">SETTLED</span>');
    escaped = escaped.replace(/\b(MATCHED)\b/g, '<span class="badge-status badge-matched">MATCHED</span>');
    escaped = escaped.replace(/\b(SIMILAR)\b/g, '<span class="badge-status badge-similar">SIMILAR</span>');
    escaped = escaped.replace(/\b(UNMATCHED)\b/g, '<span class="badge-status badge-unmatched">UNMATCHED</span>');

    const lines = escaped.split("\n");
    let html = "";
    let inTable = false;
    let tableRows = [];

    const flushTable = () => {
      if (tableRows.length === 0) return;
      const [headerLine, , ...bodyLines] = tableRows;
      const headers = headerLine.split("|").map((c) => c.trim()).filter(Boolean);
      html += "<table><thead><tr>" + headers.map((h) => `<th>${h}</th>`).join("") + "</tr></thead><tbody>";

      const tableData = [];

      bodyLines.forEach((row) => {
        const cells = row.split("|").map((c) => c.trim()).filter(Boolean);
        if (cells.length === 0) return;
        tableData.push(cells);
        html += "<tr>" + cells.map((c) => `<td>${c}</td>`).join("") + "</tr>";
      });
      html += "</tbody></table>";

      // 3. Auto-generate visual chart if table contains status / breakdown numbers
      if (window.Chart && tableData.length >= 2) {
        const chartId = `chatChart_${++chartCounter}`;
        const chartInfo = extractChartDataFromTable(headers, tableData);
        if (chartInfo) {
          html += `<div class="chat-chart-container"><div class="chat-chart-title"><span>Visual Breakdown</span> <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M18 9l-4 4-3-3-4 4"/></svg></div><canvas id="${chartId}" class="chat-chart-canvas"></canvas></div>`;
          setTimeout(() => initChatChart(chartId, chartInfo), 80);
        }
      }

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
      let lineHtml = line;
      if (/^###\s+/.test(lineHtml)) {
        lineHtml = `<h3>${lineHtml.replace(/^###\s+/, "")}</h3>`;
      } else if (/^##\s+/.test(lineHtml)) {
        lineHtml = `<h2>${lineHtml.replace(/^##\s+/, "")}</h2>`;
      } else if (/^#\s+/.test(lineHtml)) {
        lineHtml = `<h1>${lineHtml.replace(/^#\s+/, "")}</h1>`;
      } else {
        lineHtml = lineHtml.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
        lineHtml = lineHtml.replace(/`([^`]+)`/g, "<code>$1</code>");
      }

      // Inline progress bar for percentages (e.g. 85.5%)
      const pctMatch = lineHtml.match(/(\b\d+(\.\d+)?%\b)/);
      if (pctMatch && !inTable && !lineHtml.includes("<h")) {
        const pctVal = parseFloat(pctMatch[1]);
        if (!isNaN(pctVal) && pctVal >= 0 && pctVal <= 100) {
          lineHtml += `<div class="chat-progress-container"><div class="chat-progress-bg"><div class="chat-progress-fill" style="width:${pctVal}%"></div></div></div>`;
        }
      }

      html += lineHtml + "\n";
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
    if (!text || !text.trim() || sending) return;
    sending = true;

    const input = document.getElementById("chatInput");
    const sendBtn = document.getElementById("chatSendBtn");
    if (input) input.value = "";
    if (sendBtn) sendBtn.disabled = true;

    try {
      const sessionId = await ensureActiveSession();

      appendMessage("user", text);
      const typingNode = appendTyping();

      const result = await window.LedgerApi.sendChatMessage(sessionId, text);
      typingNode.remove();
      appendMessage("agent", result.reply);

      await refreshSessionList();
    } catch (err) {
      const typingNode = document.getElementById("typingIndicator");
      if (typingNode) typingNode.remove();
      const message = err instanceof window.ApiError ? err.message : "Something went wrong reaching the agent.";
      appendMessage("error", message);
    } finally {
      sending = false;
      if (sendBtn) sendBtn.disabled = false;
      if (input) input.focus();
    }
  }

  // ------------------------------------------------------------------
  // Floating Chat Widget & Global Quick Actions
  // ------------------------------------------------------------------

  async function sendFloatingChatMessage(text) {
    if (!text || !text.trim() || sending) return;
    sending = true;

    const input = document.getElementById("floatingChatInput");
    const sendBtn = document.getElementById("btnFloatingChatSend");
    const container = document.getElementById("floatingChatMessages");
    if (input) input.value = "";
    if (sendBtn) sendBtn.disabled = true;

    try {
      const sessionId = await ensureActiveSession();

      const userNode = el(`<div class="chat-msg chat-msg-user"><div class="chat-bubble">${escapeHtml(text)}</div></div>`);
      container.appendChild(userNode);
      scrollToBottom(container);

      const typingNode = el(
        '<div class="chat-msg chat-msg-agent" id="floatingTypingIndicator"><div class="chat-bubble"><span class="chat-typing"><span></span><span></span><span></span></span></div></div>'
      );
      container.appendChild(typingNode);
      scrollToBottom(container);

      const result = await window.LedgerApi.sendChatMessage(sessionId, text);
      typingNode.remove();

      const agentNode = el(`<div class="chat-msg chat-msg-agent"><div class="chat-bubble">${renderMarkdownish(result.reply)}</div></div>`);
      container.appendChild(agentNode);
      scrollToBottom(container);

      const mainBox = document.getElementById("chatMessages");
      if (mainBox) {
        appendMessage("user", text);
        appendMessage("agent", result.reply);
      }

      await refreshSessionList();
    } catch (err) {
      const typingNode = document.getElementById("floatingTypingIndicator");
      if (typingNode) typingNode.remove();
      const message = err instanceof window.ApiError ? err.message : "Error reaching agent.";
      const errNode = el(`<div class="chat-msg chat-msg-error"><div class="chat-bubble">${escapeHtml(message)}</div></div>`);
      container.appendChild(errNode);
      scrollToBottom(container);
    } finally {
      sending = false;
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  window.askLedgerAiAboutTx = function (txId) {
    if (!txId) return;
    const queryText = `Why is transaction ${txId} unmatched?`;
    
    const widget = document.getElementById("floatingChatWidget");
    if (widget) {
      widget.style.display = "flex";
      sendFloatingChatMessage(queryText);
      return;
    }

    if (window.activateSub) {
      window.activateSub("sub-talk-to-ledger");
    }
    const input = document.getElementById("chatInput");
    if (input) {
      input.value = queryText;
      sendMessage(queryText);
    }
  };

  function makeWidgetDraggable(widget, header) {
    let isDragging = false;
    let startX, startY, startLeft, startTop;

    header.addEventListener("mousedown", (e) => {
      if (e.target.closest("button")) return;
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;

      const rect = widget.getBoundingClientRect();
      startLeft = rect.left;
      startTop = rect.top;

      widget.style.right = "auto";
      widget.style.bottom = "auto";
      widget.style.left = `${startLeft}px`;
      widget.style.top = `${startTop}px`;

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    });

    function onMouseMove(e) {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;

      let newLeft = startLeft + dx;
      let newTop = startTop + dy;

      newLeft = Math.max(10, Math.min(window.innerWidth - widget.offsetWidth - 10, newLeft));
      newTop = Math.max(10, Math.min(window.innerHeight - widget.offsetHeight - 10, newTop));

      widget.style.left = `${newLeft}px`;
      widget.style.top = `${newTop}px`;
    }

    function onMouseUp() {
      isDragging = false;
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    }
  }

  function initFloatingChat() {
    const toggleBtn = document.getElementById("btnFloatingChatToggle");
    const closeBtn = document.getElementById("btnFloatingChatClose");
    const newBtn = document.getElementById("btnFloatingChatNew");
    const widget = document.getElementById("floatingChatWidget");
    const header = widget?.querySelector(".floating-chat-header");
    const form = document.getElementById("floatingChatForm");
    const input = document.getElementById("floatingChatInput");

    if (widget && header) {
      makeWidgetDraggable(widget, header);
    }

    if (toggleBtn && widget) {
      toggleBtn.addEventListener("click", () => {
        const isHidden = widget.style.display === "none" || !widget.style.display;
        widget.style.display = isHidden ? "flex" : "none";
      });
    }

    if (closeBtn && widget) {
      closeBtn.addEventListener("click", () => {
        widget.style.display = "none";
      });
    }

    if (newBtn) {
      newBtn.addEventListener("click", () => {
        startNewSession();
        const container = document.getElementById("floatingChatMessages");
        if (container) {
          container.innerHTML = `<div class="chat-msg chat-msg-agent"><div class="chat-bubble">${GREETING_HTML}</div></div>`;
        }
      });
    }

    if (form && input) {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        sendFloatingChatMessage(input.value);
      });
    }
  }

  // ------------------------------------------------------------------
  // Init
  // ------------------------------------------------------------------

  async function initChat() {
    initFloatingChat();

    const form = document.getElementById("chatForm");
    const input = document.getElementById("chatInput");

    if (form && input) {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        sendMessage(input.value);
      });
    }

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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initChat);
  } else {
    initChat();
  }
})();

