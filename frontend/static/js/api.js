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
  importStatement(files, name, isPrimary, color, rules, useLlm = false) {
    const formData = new FormData();
    const fileList = Array.isArray(files) ? files : [files];
    fileList.forEach(f => formData.append("file", f));
    formData.append("name", name || "");
    formData.append("is_primary", isPrimary ? "true" : "false");
    formData.append("color", color || "");
    formData.append("rules", rules || "");
    formData.append("use_llm", useLlm ? "true" : "false");
    return fetch(`${API_BASE}/statements/import`, {
      method: "POST",
      body: formData,
    }).then(handleResponse);
  },

  getStatementDetail(statementId) {
    return getJson(`/statements/${encodeURIComponent(statementId)}`);
  },
  setPrimaryStatement(statementId) {
    return postJson(`/statements/${encodeURIComponent(statementId)}/set-primary`);
  },
  renameStatement(statementId, name) {
    return postJson(`/statements/${encodeURIComponent(statementId)}/rename`, { name });
  },
  updateStatementColor(statementId, color) {
    return postJson(`/statements/${encodeURIComponent(statementId)}/color`, { color });
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
  updateStatementRows(statementId, rows) {
    return postJson(`/statements/${encodeURIComponent(statementId)}/update-rows`, { rows });
  },
  deleteStatementColumns(statementId, columns) {
    return postJson(`/statements/${encodeURIComponent(statementId)}/delete-columns`, { columns });
  },
  realignStatementColumnsLLM(statementId) {
    return postJson(`/statements/${encodeURIComponent(statementId)}/realign-columns-llm`);
  },
  addStatementTransaction(statementId, payload) {
    return postJson(`/statements/${encodeURIComponent(statementId)}/add-transaction`, payload);
  },
  getSimilarPayments(primaryId, sourceType, amount, date, utr, description, sourceName, statementId) {
    const params = new URLSearchParams({
      primary_id: primaryId || "",
      source_type: sourceType || "",
      source_name: sourceName || "",
      statement_id: statementId || "",
      amount: amount != null ? amount : "",
      date: date || "",
      utr: utr || "",
      description: description || "",
    });
    return getJson(`/similar-payments?${params.toString()}`);
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

  // --- Reconciliation & Pipeline -------------------------------------------
  getPipelineStatus() {
    return getJson("/pipeline/status");
  },
  runReconciliation(options = {}) {
    return postJson("/reconcile", options);
  },
  getLatestReconciliation() {
    return getJson("/reconciliation");
  },
  getReconciliationRuns() {
    return getJson("/reconciliation/runs");
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
  resolveException(exceptionId, outcome = "confirmed_match", resolvedBy = "admin") {
    return postJson(`/exceptions/${encodeURIComponent(exceptionId)}/resolve`, {
      outcome,
      resolved_by: resolvedBy,
    });
  },

  flagManual(settlementId, reason, bankTransactionId, amount) {
    return postJson("/transactions/flag-manual", {
      settlement_id: settlementId,
      reason,
      bank_transaction_id: bankTransactionId,
      amount,
    });
  },

  rematchLlm(settlementId, bankTransactionId, amount) {
    return postJson("/transactions/rematch-llm", {
      settlement_id: settlementId,
      bank_transaction_id: bankTransactionId,
      amount,
    });
  },

  llmSmartMatch(exceptionId, settlementId, amount, date, description, sourceType, sourceName, statementId) {
    return postJson("/transactions/llm-smart-match", {
      exception_id: exceptionId,
      settlement_id: settlementId,
      amount,
      date,
      description,
      source_type: sourceType,
      source_name: sourceName,
      statement_id: statementId,
    });
  },

  overrideStatus(settlementId, bankTransactionId, targetStatus) {
    return postJson("/transactions/override-status", {
      settlement_id: settlementId,
      bank_transaction_id: bankTransactionId,
      target_status: targetStatus,
    });
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

  // --- Cash Forecast (Part 24) -------------------------------------------
  getCashForecast(days = 30) {
    return getJson(`/forecast?days=${encodeURIComponent(days)}`);
  },
  getForecastDayDetails(date) {
    return getJson(`/forecast/day-details?date=${encodeURIComponent(date)}`);
  },
  updateBeginningBalance(val) {
    return postJson(`/reconciliation/beginning_balance`, { beginning_balance: val });
  },
  getTestCases() {
    return getJson(`/testcases`);
  },
};

// Exposed as a global since the dashboard is plain JS (no bundler yet).
window.LedgerApi = LedgerApi;
window.ApiError = ApiError;
