/**
 * api.js — frontend API service layer.
 *
 * This is the ONLY file that knows real endpoint paths. Every other script
 * calls the functions exported here instead of calling fetch() directly.
 * If/when the backend team finalizes different endpoint names, only this
 * file needs to change — dashboard.js and the rest of the UI stay the same.
 *
 * No reconciliation, matching, or scoring logic lives here. This module
 * only sends files/requests to Flask and hands back parsed JSON.
 */

const API_BASE = "/api";

class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

async function handleResponse(res) {
  let body = null;
  try {
    body = await res.json();
  } catch (_) {
    // non-JSON response — leave body as null
  }

  if (!res.ok) {
    const message = (body && body.error) || `Request failed with status ${res.status}`;
    throw new ApiError(message, res.status, body);
  }

  return body;
}

function postFile(path, file) {
  const formData = new FormData();
  formData.append("file", file);

  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    body: formData,
  }).then(handleResponse);
}

function postJson(path, payload) {
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  }).then(handleResponse);
}

function getJson(path) {
  return fetch(`${API_BASE}${path}`).then(handleResponse);
}

/* ---------------------------------------------------------------------- *
 * Public API — conceptual endpoints. Exact paths can change; callers
 * outside this file should never hardcode a URL string.
 * ---------------------------------------------------------------------- */

const LedgerApi = {
  // --- Statements Store ----------------------------------------------------
  getStatements() {
    return getJson("/statements");
  },
  importStatement(file, name, sourceType, color, statementTypeLabel, rules) {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("name", name || "");
    formData.append("source_type", sourceType || "bank");
    formData.append("color", color || "");
    formData.append("statement_type_label", statementTypeLabel || "");
    formData.append("rules", rules || "");
    return fetch(`${API_BASE}/statements/import`, {
      method: "POST",
      body: formData,
    }).then(handleResponse);
  },
  getStatementDetail(statementId) {
    return getJson(`/statements/${encodeURIComponent(statementId)}`);
  },
  renameStatement(statementId, name) {
    return postJson(`/statements/${encodeURIComponent(statementId)}/rename`, { name });
  },
  deleteStatement(statementId) {
    return fetch(`${API_BASE}/statements/${encodeURIComponent(statementId)}`, {
      method: "DELETE",
    }).then(handleResponse);
  },
  appendStatementData(statementId, file) {
    const formData = new FormData();
    formData.append("file", file);
    return fetch(`${API_BASE}/statements/${encodeURIComponent(statementId)}/append`, {
      method: "POST",
      body: formData,
    }).then(handleResponse);
  },

  // --- Uploads -----------------------------------------------------------
  uploadRazorpay(file) {
    return postFile("/upload/razorpay", file);
  },
  uploadBank(file) {
    return postFile("/upload/bank", file);
  },
  uploadOrders(file) {
    return postFile("/upload/orders", file);
  },

  // --- Reconciliation ------------------------------------------------------
  runReconciliation(options = {}) {
    return postJson("/reconcile", options);
  },
  getLatestReconciliation() {
    return getJson("/reconciliation");
  },
  getReconciliation(runId) {
    return getJson(`/reconciliation/${encodeURIComponent(runId)}`);
  },
  closePeriod(runId) {
    return postJson(`/reconciliation/${encodeURIComponent(runId)}/close`);
  },

  // --- Exceptions ----------------------------------------------------------
  getLatestExceptions() {
    return getJson("/exceptions");
  },
  getExceptions(runId) {
    return getJson(`/exceptions/${encodeURIComponent(runId)}`);
  },

  // --- Dashboard summary -----------------------------------------------
  getDashboardSummary(runId) {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return getJson(`/dashboard/summary${query}`);
  },

  // --- Talk to Ledger (Q&A agent, with persistent chat history) --------
  getChatSessions() {
    return getJson("/chat/sessions");
  },
  createChatSession() {
    return postJson("/chat/sessions");
  },
  getChatSession(sessionId) {
    return getJson(`/chat/sessions/${encodeURIComponent(sessionId)}`);
  },
  deleteChatSession(sessionId) {
    return fetch(`${API_BASE}/chat/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    }).then(handleResponse);
  },
  sendChatMessage(sessionId, message) {
    return postJson(`/chat/sessions/${encodeURIComponent(sessionId)}/messages`, { message });
  },
};

// Exposed as a global since the dashboard is plain JS (no bundler yet).
window.LedgerApi = LedgerApi;
window.ApiError = ApiError;
