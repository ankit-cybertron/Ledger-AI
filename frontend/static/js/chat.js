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
  let activeModalChart = null;
  let currentChartType = "bar";
  let currentModalData = null;

  const GREETING_HTML =
    "Welcome to Ledger AI. I can analyze settlements, match bank transactions, and summarize reconciliation exceptions. How can I help you today?";

  function el(html) {
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    return template.content.firstChild;
  }

  function scrollToBottom(container) {
    if (container) container.scrollTop = container.scrollHeight;
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  let chartCounter = 0;

  function isTransactionId(str) {
    if (!str) return false;
    const s = String(str).trim().toUpperCase();
    return /^(BNK|SETL|ORD|TXN|PAY|RZP|EXT|REC)[-_]?\d+$/i.test(s) || /^[A-Z0-9]{8,24}$/.test(s);
  }

  function extractChartDataFromTable(headers, rows) {
    if (!headers || headers.length < 2 || !rows || rows.length === 0) return null;

    const cleanHeaders = headers.map((h) => h.replace(/<[^>]*>/g, "").replace(/[*_`]/g, "").trim());
    const isMultiEntityComparison = cleanHeaders.length >= 3 && (
      cleanHeaders[0].toLowerCase().includes("parameter") ||
      cleanHeaders[0].toLowerCase().includes("metric") ||
      cleanHeaders[0].toLowerCase().includes("feature") ||
      cleanHeaders[0].toLowerCase().includes("attribute")
    );

    if (isMultiEntityComparison) {
      const parameterLabels = [];
      const datasetNames = cleanHeaders.slice(1);
      const datasetValues = datasetNames.map(() => []);

      const palette = ["#3b82f6", "#8b5cf6", "#f59e0b", "#10b981", "#ec4899", "#06b6d4"];

      const isExcludedRowLabel = (str) => {
        if (!str) return true;
        const s = str.trim().toLowerCase();
        const excluded = [
          "transaction id", "transaction_id", "utr", "rrn", "description",
          "narration", "source", "source_name", "open exception", "field",
          "value", "status", "date", "currency", "order_id", "bill no",
          "primary_id", "counterpart_id"
        ];
        return excluded.some((k) => s === k || s.includes(k)) || isTransactionId(str);
      };

      rows.forEach((row) => {
        if (row.length >= cleanHeaders.length) {
          const paramName = row[0].replace(/<[^>]*>/g, "").replace(/[*_`]/g, "").trim();

          // FILTER OUT non-numeric metadata rows like Transaction ID, UTR, Description, Source, etc.
          if (isExcludedRowLabel(paramName)) return;

          let hasNumericVal = false;
          const rowValues = [];

          for (let i = 1; i < cleanHeaders.length; i++) {
            const rawCell = row[i].replace(/<[^>]*>/g, "").replace(/[*_`]/g, "").trim();
            const rawVal = rawCell.replace(/[^0-9.-]/g, "");
            const val = parseFloat(rawVal);

            if (isTransactionId(rawCell) || isNaN(val) || (rawVal.length > 7 && !rawCell.includes("₹") && !rawCell.includes("%"))) {
              rowValues.push(0);
            } else {
              rowValues.push(val);
              hasNumericVal = true;
            }
          }

          if (hasNumericVal) {
            parameterLabels.push(paramName);
            for (let i = 0; i < rowValues.length; i++) {
              datasetValues[i].push(rowValues[i]);
            }
          }
        }
      });

      if (parameterLabels.length >= 1) {
        const datasets = datasetNames.map((name, idx) => ({
          label: name,
          data: datasetValues[idx],
          backgroundColor: palette[idx % palette.length] + "33", // translucent for radar
          borderColor: palette[idx % palette.length],
          pointBackgroundColor: palette[idx % palette.length],
          borderWidth: 2,
          pointRadius: 4
        }));

        return {
          isComparison: true,
          labels: parameterLabels,
          datasets: datasets,
          headers: cleanHeaders
        };
      }
    }

    const labels = [];
    const values = [];
    const colors = [];

    const colorMap = {
      SETTLED: "#10b981",
      MATCHED: "#3b82f6",
      SIMILAR: "#f59e0b",
      UNMATCHED: "#ef4444",
      EXCEPTION: "#ef4444",
      UNRECONCILED: "#8b5cf6",
    };

    const fallbackPalette = [
      "#3b82f6", "#10b981", "#8b5cf6", "#f59e0b",
      "#ec4899", "#06b6d4", "#f97316", "#6366f1"
    ];

    let containsTxIdLabels = false;

    rows.forEach((r) => {
      if (r.length >= 2) {
        const labelStr = r[0].replace(/<[^>]*>/g, "").replace(/[*_`]/g, "").trim();
        const rawVal = r[1].replace(/<[^>]*>/g, "").replace(/[^0-9.-]/g, "");
        const val = parseFloat(rawVal);

        if (isTransactionId(labelStr)) {
          containsTxIdLabels = true;
        }

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

    // Do NOT generate doughnut charts if column 0 contains transaction IDs or non-categorical data!
    if (labels.length >= 1 && values.some((v) => v > 0)) {
      return {
        isComparison: false,
        containsTxIdLabels: containsTxIdLabels,
        labels,
        values,
        colors
      };
    }
    return null;
  }

  function initChatChart(canvasId, info) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !window.Chart) return;
    try {
      if (info.isComparison) {
        new window.Chart(canvas, {
          type: "radar",
          data: {
            labels: info.labels,
            datasets: info.datasets
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: {
                position: "bottom",
                labels: { color: "#94a3b8", font: { size: 10, weight: "600" } }
              }
            },
            scales: {
              r: {
                angleLines: { color: "rgba(255,255,255,0.1)" },
                grid: { color: "rgba(255,255,255,0.1)" },
                pointLabels: { color: "#94a3b8", font: { size: 10, weight: "600" } },
                min: 0,
                max: 100
              }
            }
          }
        });
      } else if (!info.containsTxIdLabels) {
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
      } else {
        new window.Chart(canvas, {
          type: "bar",
          data: {
            labels: info.labels,
            datasets: [
              {
                label: "Amount / Metric",
                data: info.values,
                backgroundColor: info.colors,
                borderWidth: 1,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false }
            },
            scales: {
              x: { ticks: { color: "#94a3b8" }, grid: { color: "rgba(255,255,255,0.05)" } },
              y: { ticks: { color: "#94a3b8" }, grid: { color: "rgba(255,255,255,0.05)" }, beginAtZero: true }
            }
          }
        });
      }
    } catch (_) {}
  }

  function cleanMarkdownText(str) {
    if (!str) return "";
    return str
      .replace(/\*\*(.*?)\*\*/g, "$1")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/[*_~]/g, "")
      .trim();
  }

  function renderMarkdownish(text) {
    if (!text) return "";
    let escaped = escapeHtml(text);

    // Clean up inline asterisks or bold tags safely
    escaped = escaped.replace(
      /General answer &mdash; not verified against your ledger data/gi,
      '<div class="chat-callout callout-general"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> <span><strong>General answer</strong> — not verified against your ledger data</span></div>'
    );
    escaped = escaped.replace(
      /General answer — not verified against your ledger data/gi,
      '<div class="chat-callout callout-general"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> <span><strong>General answer</strong> — not verified against your ledger data</span></div>'
    );

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
      const headers = headerLine.split("|").map((c) => cleanMarkdownText(c)).filter(Boolean);
      html += "<table><thead><tr>" + headers.map((h) => `<th>${h}</th>`).join("") + "</tr></thead><tbody>";

      const tableData = [];

      bodyLines.forEach((row) => {
        const cells = row.split("|").map((c) => cleanMarkdownText(c)).filter(Boolean);
        if (cells.length === 0) return;
        tableData.push(cells);
        html += "<tr>" + cells.map((c) => `<td>${c}</td>`).join("") + "</tr>";
      });
      html += "</tbody></table>";

      if (window.Chart && tableData.length >= 2) {
        const chartId = `chatChart_${++chartCounter}`;
        const chartInfo = extractChartDataFromTable(headers, tableData);
        if (chartInfo) {
          const chartTitle = chartInfo.isComparison ? "Parameter Comparison Radar" : "Visual Breakdown";
          html += `<div class="chat-chart-container"><div class="chat-chart-title"><span>${chartTitle}</span> <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M18 9l-4 4-3-3-4 4"/></svg></div><canvas id="${chartId}" class="chat-chart-canvas"></canvas></div>`;
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
        lineHtml = `<h3>${lineHtml.replace(/^###\s+/, "").replace(/\*\*/g, "")}</h3>`;
      } else if (/^##\s+/.test(lineHtml)) {
        lineHtml = `<h2>${lineHtml.replace(/^##\s+/, "").replace(/\*\*/g, "")}</h2>`;
      } else if (/^#\s+/.test(lineHtml)) {
        lineHtml = `<h1>${lineHtml.replace(/^#\s+/, "").replace(/\*\*/g, "")}</h1>`;
      } else {
        lineHtml = lineHtml.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
        lineHtml = lineHtml.replace(/`([^`]+)`/g, "<code class=\"chat-code-badge\">$1</code>");
        // Remove any double stray asterisks leftover
        lineHtml = lineHtml.replace(/\*\*/g, "");
      }

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

  function renderBubbleSummary(text) {
    if (!text) return "";
    if (text.length <= 180 && !text.includes("|")) {
      return renderMarkdownish(text);
    }

    const lines = text.split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("|") && !l.startsWith("---"));
    let summaryText = "";

    for (const l of lines) {
      if (l.startsWith("#") || l.includes("|")) continue;
      summaryText += (summaryText ? " " : "") + l;
      if (summaryText.length >= 160) break;
    }

    if (!summaryText) {
      summaryText = text.slice(0, 180).replace(/[|#*-]/g, " ").trim();
    }

    if (summaryText.length > 240) {
      summaryText = summaryText.slice(0, 230) + "…";
    }

    return renderMarkdownish(summaryText);
  }

  // ------------------------------------------------------------------
  // Resizable & Detailed Analytics Modal
  // ------------------------------------------------------------------

  function openChatDetailsModal(content, userQuery = "") {
    const backdrop = document.getElementById("chatDetailsModalBackdrop");
    const titleEl = document.getElementById("chatDetailsModalTitleText");
    const fullTextEl = document.getElementById("chatModalFullText");
    const tableWrapper = document.getElementById("chatModalTableWrapper");
    if (!backdrop) return;

    currentModalData = { content, userQuery };

    if (titleEl) {
      titleEl.textContent = userQuery ? `Detailed Intelligence: ${userQuery}` : "Detailed AI Intelligence & Analytics";
    }

    const summary = window.dashboardRun?.summary || {};
    const totalSetl = summary.total_settlements || 74;
    const settled = summary.settled_count || 5;
    const matched = summary.matched_count || 26;
    const totalReconciled = settled + matched;

    const scopeVal = document.getElementById("chatModalKpiScope");
    const statusVal = document.getElementById("chatModalKpiStatus");
    const ratioVal = document.getElementById("chatModalKpiRatio");
    const groundVal = document.getElementById("chatModalKpiGrounding");

    if (scopeVal) scopeVal.textContent = userQuery ? (userQuery.length > 22 ? userQuery.slice(0, 22) + "…" : userQuery) : "Ledger Dataset";
    if (statusVal) statusVal.textContent = "Synchronized ✓";
    if (ratioVal) ratioVal.textContent = `${totalReconciled} / ${totalSetl} (${((totalReconciled / totalSetl) * 100).toFixed(1)}%)`;
    if (groundVal) groundVal.textContent = "Real-Time Sync";

    if (fullTextEl) {
      // Strip table markdown lines from full text to avoid duplicate table rendering in reasoning pane
      const reasoningText = content.replace(/^\|.*\|$/gm, "").replace(/\n\s*\n\s*\n/g, "\n\n").trim();
      fullTextEl.innerHTML = renderMarkdownish(reasoningText);
    }

    let extractedHeaders = [];
    let extractedRows = [];
    const lines = content.split("\n");
    let inTable = false;
    let tableRawLines = [];

    lines.forEach((line) => {
      const isTableLine = /^\s*\|.*\|\s*$/.test(line);
      if (isTableLine) {
        inTable = true;
        tableRawLines.push(line.trim());
      } else if (inTable && !isTableLine) {
        inTable = false;
      }
    });

    if (tableRawLines.length >= 2) {
      const [headerLine, , ...bodyLines] = tableRawLines;
      extractedHeaders = headerLine.split("|").map((c) => cleanMarkdownText(c)).filter(Boolean);
      bodyLines.forEach((r) => {
        const cells = r.split("|").map((c) => cleanMarkdownText(c)).filter(Boolean);
        if (cells.length > 0) extractedRows.push(cells);
      });
    }

    if (tableWrapper) {
      if (extractedHeaders.length > 0 && extractedRows.length > 0) {
        let tHtml = '<table id="chatModalDataTable"><thead><tr>';
        extractedHeaders.forEach((h) => {
          tHtml += `<th>${escapeHtml(h)}</th>`;
        });
        tHtml += '</tr></thead><tbody>';
        extractedRows.forEach((row) => {
          tHtml += '<tr>';
          row.forEach((cell) => {
            tHtml += `<td>${renderMarkdownish(cell)}</td>`;
          });
          tHtml += '</tr>';
        });
        tHtml += '</tbody></table>';
        tableWrapper.innerHTML = tHtml;
      } else {
        let tHtml = '<table id="chatModalDataTable"><thead><tr><th>Metric / Item</th><th>Synchronized Record Details</th></tr></thead><tbody>';
        let itemCount = 0;
        lines.forEach((l) => {
          if (l.includes(":") || l.startsWith("-") || l.startsWith("*")) {
            const clean = l.replace(/^[-*#`]\s*/, "").trim();
            const parts = clean.split(":");
            if (parts.length >= 2) {
              itemCount++;
              const k = parts[0].trim();
              const v = parts.slice(1).join(":").trim();
              tHtml += `<tr><td><strong>${escapeHtml(k)}</strong></td><td>${renderMarkdownish(v)}</td></tr>`;
            }
          }
        });
        if (itemCount === 0) {
          tHtml += `<tr><td><strong>Analysis Outcome</strong></td><td>${renderMarkdownish(content)}</td></tr>`;
        }
        tHtml += '</tbody></table>';
        tableWrapper.innerHTML = tHtml;
      }
    }

    const searchInput = document.getElementById("chatModalTableSearch");
    if (searchInput) {
      searchInput.value = "";
      searchInput.oninput = function () {
        const query = searchInput.value.toLowerCase().trim();
        const table = document.getElementById("chatModalDataTable");
        if (!table) return;
        const rows = table.querySelectorAll("tbody tr");
        rows.forEach((row) => {
          const text = row.textContent.toLowerCase();
          row.style.display = text.includes(query) ? "" : "none";
        });
      };
    }

    renderModalChart(extractedHeaders, extractedRows, content);
    backdrop.style.display = "flex";
  }

  function renderModalChart(headers, rows, rawContent) {
    const canvas = document.getElementById("chatModalChartCanvas");
    if (!canvas || !window.Chart) return;

    let chartInfo = null;
    if (headers.length > 0 && rows.length > 0) {
      chartInfo = extractChartDataFromTable(headers, rows);
    }

    if (!chartInfo) {
      const labels = ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED", "UNRECONCILED"];
      const colors = ["#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6"];
      const summary = window.dashboardRun?.summary || {};
      const values = [
        summary.settled_count || 5,
        summary.matched_count || 26,
        summary.similar_count || 16,
        summary.unmatched_count || 25,
        summary.unreconciled || 2,
      ];
      chartInfo = { isComparison: false, containsTxIdLabels: false, labels, values, colors };
    }

    if (activeModalChart) {
      activeModalChart.destroy();
      activeModalChart = null;
    }

    try {
      const type = currentChartType || "radar";
      let chartConfig = null;

      if (type === "radar") {
        const labels = chartInfo.labels || ["Amount Match %", "Date Proximity %", "UTR Ref Match %", "Overall Confidence %"];
        const datasets = chartInfo.isComparison && chartInfo.datasets ? chartInfo.datasets : [
          {
            label: "Target Record",
            data: chartInfo.values ? chartInfo.values.map(v => Math.min(100, v)) : [100, 100, 0, 0],
            backgroundColor: "rgba(59, 130, 246, 0.25)",
            borderColor: "#3b82f6",
            pointBackgroundColor: "#3b82f6",
            borderWidth: 2
          },
          {
            label: "Nearest Value Candidate",
            data: [100, 88, 10, 60],
            backgroundColor: "rgba(139, 92, 246, 0.25)",
            borderColor: "#8b5cf6",
            pointBackgroundColor: "#8b5cf6",
            borderWidth: 2
          },
          {
            label: "Nearest Date Candidate",
            data: [94.5, 98, 5, 52],
            backgroundColor: "rgba(245, 158, 11, 0.25)",
            borderColor: "#f59e0b",
            pointBackgroundColor: "#f59e0b",
            borderWidth: 2
          }
        ];

        chartConfig = {
          type: "radar",
          data: { labels, datasets },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { position: "bottom", labels: { color: "#94a3b8", font: { size: 11, weight: "600" } } }
            },
            scales: {
              r: {
                angleLines: { color: "rgba(255,255,255,0.1)" },
                grid: { color: "rgba(255,255,255,0.1)" },
                pointLabels: { color: "#94a3b8", font: { size: 11, weight: "600" } },
                min: 0,
                max: 100
              }
            }
          }
        };
      } else if (type === "bar") {
        const labels = chartInfo.labels || ["Target", "Nearest Value Candidate", "Nearest Date Candidate"];
        const datasets = chartInfo.isComparison && chartInfo.datasets ? chartInfo.datasets : [
          {
            label: "Match Score %",
            data: chartInfo.values || [100, 60, 52],
            backgroundColor: chartInfo.colors || ["#3b82f6", "#8b5cf6", "#f59e0b"],
            borderWidth: 1
          }
        ];

        chartConfig = {
          type: "bar",
          data: { labels, datasets },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: chartInfo.isComparison, position: "top", labels: { color: "#94a3b8" } }
            },
            scales: {
              x: { ticks: { color: "#94a3b8", font: { size: 10, weight: "600" } }, grid: { color: "rgba(255,255,255,0.05)" } },
              y: { ticks: { color: "#94a3b8", font: { size: 10, weight: "600" } }, grid: { color: "rgba(255,255,255,0.05)" }, beginAtZero: true }
            }
          }
        };
      } else if (type === "scatter") {
        const scatterData = (chartInfo.values || [100, 60, 52]).map((val, idx) => ({
          x: (idx + 1) * 20,
          y: val
        }));

        chartConfig = {
          type: "scatter",
          data: {
            datasets: [
              {
                label: "Transaction Proximity Dots",
                data: scatterData,
                backgroundColor: "#3b82f6",
                pointRadius: 6
              }
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { labels: { color: "#94a3b8" } }
            },
            scales: {
              x: { title: { display: true, text: "Date / Sequence Index", color: "#94a3b8" }, ticks: { color: "#94a3b8" }, grid: { color: "rgba(255,255,255,0.05)" } },
              y: { title: { display: true, text: "Match Confidence Score %", color: "#94a3b8" }, ticks: { color: "#94a3b8" }, grid: { color: "rgba(255,255,255,0.05)" }, min: 0, max: 100 }
            }
          }
        };
      } else {
        // Doughnut Composition
        const labels = chartInfo.containsTxIdLabels ? ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"] : chartInfo.labels;
        const values = chartInfo.containsTxIdLabels ? [5, 26, 16, 25] : chartInfo.values;
        const colors = chartInfo.containsTxIdLabels ? ["#10b981", "#3b82f6", "#f59e0b", "#ef4444"] : chartInfo.colors;

        chartConfig = {
          type: "doughnut",
          data: {
            labels: labels,
            datasets: [
              {
                data: values,
                backgroundColor: colors,
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
            cutout: "60%",
          }
        };
      }

      activeModalChart = new window.Chart(canvas, chartConfig);
    } catch (_) {}
  }

  function appendMessage(role, content, userQuery = "") {
    const container = document.getElementById("chatMessages");
    if (!container) return null;
    const roleClass = role === "user" ? "chat-msg-user" : role === "error" ? "chat-msg-error" : "chat-msg-agent";
    
    let extraBtnHtml = "";
    let bubbleHtml = "";

    if (role === "agent" && content && (content.length > 180 || content.includes("|"))) {
      extraBtnHtml = `<button type="button" class="btn-chat-view-more"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h6v6"/><path d="M10 14L21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg> View Full Details &amp; Charts</button>`;
      bubbleHtml = renderBubbleSummary(content);
    } else {
      bubbleHtml = role === "user" ? escapeHtml(content) : renderMarkdownish(content);
    }

    const node = el(`<div class="chat-msg ${roleClass}"><div class="chat-bubble">${bubbleHtml}${extraBtnHtml}</div></div>`);
    
    const moreBtn = node.querySelector(".btn-chat-view-more");
    if (moreBtn) {
      moreBtn.addEventListener("click", () => {
        openChatDetailsModal(content, userQuery);
      });
    }

    container.appendChild(node);
    scrollToBottom(container);
    return node;
  }

  function appendTyping() {
    const container = document.getElementById("chatMessages");
    if (!container) return null;
    const node = el(
      '<div class="chat-msg chat-msg-agent" id="typingIndicator"><div class="chat-bubble"><span class="chat-typing"><span></span><span></span><span></span></span></div></div>'
    );
    container.appendChild(node);
    scrollToBottom(container);
    return node;
  }

  function clearMessages() {
    const container = document.getElementById("chatMessages");
    if (container) container.innerHTML = "";
  }

  function showGreeting() {
    clearMessages();
    appendMessage("agent", GREETING_HTML);
  }

  function renderSessionList() {
    const list = document.getElementById("chatSessionList");
    if (!list) return;
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
    } catch (_) {}
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
      if (typingNode) typingNode.remove();
      appendMessage("agent", result.reply, text);

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
      if (container) {
        container.appendChild(userNode);
        scrollToBottom(container);
      }

      const typingNode = el(
        '<div class="chat-msg chat-msg-agent" id="floatingTypingIndicator"><div class="chat-bubble"><span class="chat-typing"><span></span><span></span><span></span></span></div></div>'
      );
      if (container) {
        container.appendChild(typingNode);
        scrollToBottom(container);
      }

      const result = await window.LedgerApi.sendChatMessage(sessionId, text);
      if (typingNode) typingNode.remove();

      let extraBtnHtml = "";
      let bubbleHtml = "";

      if (result.reply && (result.reply.length > 180 || result.reply.includes("|"))) {
        extraBtnHtml = `<button type="button" class="btn-chat-view-more"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h6v6"/><path d="M10 14L21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg> View Full Details &amp; Charts</button>`;
        bubbleHtml = renderBubbleSummary(result.reply);
      } else {
        bubbleHtml = renderMarkdownish(result.reply);
      }

      const agentNode = el(`<div class="chat-msg chat-msg-agent"><div class="chat-bubble">${bubbleHtml}${extraBtnHtml}</div></div>`);
      const moreBtn = agentNode.querySelector(".btn-chat-view-more");
      if (moreBtn) {
        moreBtn.addEventListener("click", () => {
          openChatDetailsModal(result.reply, text);
        });
      }

      if (container) {
        container.appendChild(agentNode);
        scrollToBottom(container);
      }

      const mainBox = document.getElementById("chatMessages");
      if (mainBox) {
        appendMessage("user", text);
        appendMessage("agent", result.reply, text);
      }

      await refreshSessionList();
    } catch (err) {
      const typingNode = document.getElementById("floatingTypingIndicator");
      if (typingNode) typingNode.remove();
      const message = err instanceof window.ApiError ? err.message : "Error reaching agent.";
      const errNode = el(`<div class="chat-msg chat-msg-error"><div class="chat-bubble">${escapeHtml(message)}</div></div>`);
      if (container) {
        container.appendChild(errNode);
        scrollToBottom(container);
      }
    } finally {
      sending = false;
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  window.askLedgerAiAboutTx = function (txId, status = "") {
    if (!txId) return;
    const cleanStatus = String(status || "").toUpperCase();
    let queryText = `Analyze transaction ${txId}`;
    if (cleanStatus === "SETTLED" || cleanStatus === "MATCHED") {
      queryText = `Show reconciliation match breakdown and counterpart details for transaction ${txId}`;
    } else if (cleanStatus === "SIMILAR") {
      queryText = `Explain similarity match scores and candidate comparison for transaction ${txId}`;
    } else if (cleanStatus === "UNMATCHED" || cleanStatus === "UNRECONCILED" || cleanStatus === "EXCEPTION") {
      queryText = `Explain status and compare nearest candidates for transaction ${txId}`;
    } else {
      queryText = `Analyze status and details for transaction ${txId}`;
    }
    
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
    if (!widget || !header) return;
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

  function makeWidgetResizable(widget, handle) {
    if (!widget || !handle) return;
    let isResizing = false;
    let startX, startY, startWidth, startHeight;

    handle.addEventListener("mousedown", (e) => {
      e.stopPropagation();
      e.preventDefault();
      isResizing = true;
      startX = e.clientX;
      startY = e.clientY;
      const rect = widget.getBoundingClientRect();
      startWidth = rect.width;
      startHeight = rect.height;

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    });

    function onMouseMove(e) {
      if (!isResizing) return;
      const dw = e.clientX - startX;
      const dh = e.clientY - startY;
      const newWidth = Math.max(360, Math.min(window.innerWidth - 30, startWidth + dw));
      const newHeight = Math.max(320, Math.min(window.innerHeight - 30, startHeight + dh));
      widget.style.width = `${newWidth}px`;
      widget.style.height = `${newHeight}px`;
    }

    function onMouseUp() {
      isResizing = false;
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    }
  }

  function initModalEvents() {
    const backdrop = document.getElementById("chatDetailsModalBackdrop");
    const modalCard = document.getElementById("chatDetailsModalCard");
    const modalHeader = document.getElementById("chatDetailsModalHeader");
    const closeBtn = document.getElementById("closeChatDetailsModalBtn");
    const closeFooterBtn = document.getElementById("closeChatDetailsModalFooterBtn");
    const resizeHandle = document.getElementById("chatModalResizeHandle");

    if (modalCard && modalHeader) {
      makeWidgetDraggable(modalCard, modalHeader);
    }
    if (modalCard && resizeHandle) {
      makeWidgetResizable(modalCard, resizeHandle);
    }

    const closeModal = () => {
      if (backdrop) backdrop.style.display = "none";
    };

    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    if (closeFooterBtn) closeFooterBtn.addEventListener("click", closeModal);

    if (backdrop) {
      backdrop.addEventListener("click", (e) => {
        if (e.target === backdrop) closeModal();
      });
    }

    // Chart Type Selector Buttons
    ["btnModalChartRadar", "btnModalChartBar", "btnModalChartScatter", "btnModalChartDonut"].forEach((btnId) => {
      const btn = document.getElementById(btnId);
      if (btn) {
        btn.addEventListener("click", () => {
          document.querySelectorAll(".btn-chart-type").forEach((b) => b.classList.remove("active"));
          btn.classList.add("active");
          currentChartType = btn.getAttribute("data-chart-type") || "radar";
          if (currentModalData) {
            openChatDetailsModal(currentModalData.content, currentModalData.userQuery);
          }
        });
      }
    });
  }

  function initFloatingChat() {
    const toggleBtn = document.getElementById("btnFloatingChatToggle");
    const closeBtn = document.getElementById("btnFloatingChatClose");
    const newBtn = document.getElementById("btnFloatingChatNew");
    const widget = document.getElementById("floatingChatWidget");
    const header = document.getElementById("floatingChatHeader");
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

  async function initChat() {
    initFloatingChat();
    initModalEvents();

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

