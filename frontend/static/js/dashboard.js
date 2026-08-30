/**
 * dashboard.js
 *
 * Restored original clean dashboard interaction flow while integrating backend
 * statement store, 3-dot menus, incremental updates, and dynamic data tables.
 */

(function () {
  "use strict";

  // Helper: Format any date into DD/MM/YYYY
  window.formatDateDDMMYYYY = function formatDateDDMMYYYY(dateStr) {
    if (!dateStr || dateStr === "—" || dateStr === "Today") return dateStr || "—";
    const str = String(dateStr).trim();
    const isoMatch = str.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
    if (isoMatch) {
      const year = isoMatch[1];
      const month = isoMatch[2].padStart(2, "0");
      const day = isoMatch[3].padStart(2, "0");
      return `${day}/${month}/${year}`;
    }
    return str;
  };

  // Helper: Format period label date ranges to DD/MM/YYYY
  window.formatPeriodLabel = function formatPeriodLabel(str) {
    if (!str || str === "—") return "No Data";
    return String(str).replace(/\b(\d{4})-(\d{2})-(\d{2})(?:[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?\b/g, (match, y, m, d) => {
      return `${d}/${m}/${y}`;
    });
  };

  // Helper: Derive accurate source category badge label
  function getSourceTypeBadgeLabel(stmt) {
    if (!stmt) return "DATA SOURCE";
    const typeStr = (stmt.source_type || stmt.type || "").toLowerCase();
    const nameStr = (stmt.name || stmt.filename || "").toLowerCase();
    if (typeStr.includes("razorpay") || nameStr.includes("razorpay") || nameStr.includes("settlement")) {
      return "RAZORPAY SETTLEMENT";
    }
    if (typeStr.includes("internal") || nameStr.includes("internal") || nameStr.includes("order") || nameStr.includes("v2")) {
      return "INTERNAL ORDERS";
    }
    if (typeStr.includes("cash") || nameStr.includes("cash")) {
      return "CASH BOOK";
    }
    if (typeStr.includes("bank") || nameStr.includes("bank") || nameStr.includes("hdfc") || nameStr.includes("icici")) {
      return "BANK STATEMENT";
    }
    return (stmt.source_type || "STATEMENT SOURCE").replace(/_/g, " ").toUpperCase();
  }

  let currentRunId = null;
  let activeStatementId = null;

  function el(html) {
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    return template.content.firstChild;
  }

  function formatMoney(value, includePlus = true) {
    const n = Number(value) || 0;
    if (n > 0) {
      return `${includePlus ? "+" : ""}₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    } else if (n < 0) {
      return `-₹${Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return `₹${Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }


  // ------------------------------------------------------------------
  // Sub-tabs: Import Bank / Razorpay / Orders / Auto-Match / Close / Stmt View
  // ------------------------------------------------------------------

  function activateSub(subId) {
    if (subId === "sub-reconciliation") subId = "sub-reconcile";
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === subId));
    document.querySelectorAll(".sub-tab").forEach((t) => t.classList.toggle("active", t.dataset.sub === subId));
    document.querySelectorAll(".source-item").forEach((s) => s.classList.toggle("active", s.dataset.sub === subId));

    // ── Sidebar module highlighting ────────────────────────────────────
    const panelToNav = {
      "sub-current-period": "navCurrentPeriod",
      "sub-upload-bank": "navCurrentPeriod",
      "sub-reconcile": "navReconciliation",
      "sub-manual-review": "navManualReview",
      "sub-close": "navClosePeriod",
      "sub-overview": "navOverview",
      "sub-talk-to-ledger": "navTalkToLedger",
      "sub-reports": "navReports",
      "sub-config": "navConfig",
    };
    Object.entries(panelToNav).forEach(([panelId, navId]) => {
      const el = document.getElementById(navId);
      if (el) el.classList.toggle("active", subId === panelId);
    });

    // ── Topbar navigation active state highlighting ──────────────────────
    const tbReconcile = document.getElementById("topbarReconcileBtn") || document.querySelector("#topbarReconcileDropdown > .topbar-dropdown-btn");
    const tbReports = document.getElementById("topbarReportsBtn") || document.querySelector("#topbarExportsDropdown > .topbar-dropdown-btn");
    const tbAsk = document.getElementById("topbarAskBtn") || document.querySelector("a[href*='sub-talk-to-ledger']");

    if (tbReconcile) tbReconcile.classList.toggle("active", ["sub-reconcile", "sub-manual-review", "sub-config"].includes(subId));
    if (tbReports) tbReports.classList.toggle("active", subId === "sub-reports");
    if (tbAsk) tbAsk.classList.toggle("active", subId === "sub-talk-to-ledger");

    // ── Auto-accordion: open group containing active tab, collapse others ─────
    const subToGroup = {
      "sub-current-period": "groupSources",
      "sub-upload-bank": "groupSources",
      "sub-statement-view": "groupSources",
      "sub-reconcile": "groupReconciliation",
      "sub-manual-review": "groupReconciliation",
      "sub-config": "groupReconciliation",
      "sub-reports": "groupExports",
    };
    const activeGroup = subToGroup[subId] || null;
    ["groupSources", "groupReconciliation", "groupExports"].forEach((gId) => {
      const gEl = document.getElementById(gId);
      if (gEl) {
        if (activeGroup) {
          gEl.classList.toggle("open", gId === activeGroup);
        }
      }
    });

    // ── Real-time tab data refresh on activate (T13.1) ─────────────────
    if (subId === "sub-overview") {
      _loadOverviewPanel(true);
    } else if (subId === "sub-reconcile" || subId === "sub-manual-review") {
      if (currentRunId) {
        loadRun(currentRunId);
      } else {
        hydrateExistingRun();
      }
    } else if (subId === "sub-current-period" || subId === "sub-upload-bank") {
      loadSidebarSources();
      loadStatementsTable();
    } else if (subId === "sub-reports") {
      _loadReportsPanel(true);
    } else if (subId === "sub-config") {
      _loadConfigPanel(true);
    }
  }

  // ── Shared Reconciliation & System State Manager (T13.3) ────────────────
  const _panelLoaded = {};

  const stateManager = {
    isStale: true,

    invalidate() {
      this.isStale = true;
      _panelLoaded.overview = false;
      _panelLoaded.reports = false;
      _panelLoaded.config = false;
    },

    async syncAll(force = true) {
      this.invalidate();
      const activeSub = document.querySelector(".sub-tab.active")?.dataset?.sub || "sub-overview";

      await Promise.all([
        loadSidebarSources().catch(() => { }),
        loadStatementsTable().catch(() => { })
      ]);

      try {
        const latest = await window.LedgerApi.getLatestReconciliation();
        if (latest && latest.run) {
          currentRunId = latest.run.run_id;
          await loadRun(currentRunId);
        }
      } catch (_) { }

      if (activeSub === "sub-overview") {
        _loadOverviewPanel(true);
      } else if (activeSub === "sub-reports") {
        _loadReportsPanel(true);
      } else if (activeSub === "sub-config") {
        _loadConfigPanel(true);
      }

      this.isStale = false;
    }
  };

  window.stateManager = stateManager;

  function _loadReportsPanel(force) {
    if (_panelLoaded.reports && !force) return;
    const el = document.getElementById("reportsContent");
    if (!el) return;
    el.innerHTML = '<div style="text-align:center;padding:50px;color:var(--text-muted);font-size:var(--text-sm);"><svg class="spin-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg><br><br>Generating audit report & export configuration…</div>';

    Promise.all([
      fetch("/api/report-html").then(r => r.json()).catch(() => ({})),
      fetch("/api/statements").then(r => r.json()).catch(() => ({ statements: [] }))
    ]).then(([reportRes, stData]) => {
      _panelLoaded.reports = true;
      const reportData = reportRes.data || {};
      const summary = reportData.summary || {};
      const transactions = reportData.transactions || [];
      const exceptions = reportData.exceptions || [];
      const integrity = reportData.integrity || {};

      // Populate statements dropdown
      const stList = stData.statements || [];
      let stOptionsHtml = '<option value="all">All Statement Sources (Default)</option>';
      stList.forEach(s => {
        stOptionsHtml += `<option value="${s.id}">${s.name || s.id} (${(s.source_type || 'statement').toUpperCase()})</option>`;
      });

      // Filter Options UI Header
      const exportOptionsUI = `
        <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:22px 26px; margin-bottom:24px; box-shadow:var(--shadow-sm);">
          <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:16px; padding-bottom:14px; border-bottom:1px solid var(--border);">
            <h3 style="font-size:1.1rem; font-weight:700; color:var(--text-primary); margin:0; display:flex; align-items:center; gap:8px;">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
              <span>Export & Reporting Configuration</span>
            </h3>
            
            <!-- View Mode Switcher -->
            <div style="display:flex; background:var(--bg-elevated); border:1px solid var(--border); border-radius:var(--radius-md); padding:3px;">
              <button type="button" id="btnViewReportExec" onclick="window.switchReportViewMode('exec')" style="padding:6px 14px; border:none; border-radius:var(--radius-sm); background:var(--accent-blue); color:#fff; font-size:0.8rem; font-weight:600; cursor:pointer; display:inline-flex; align-items:center; gap:6px;">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
                <span>Executive Dashboard</span>
              </button>
              <button type="button" id="btnViewReportPdf" onclick="window.switchReportViewMode('pdf')" style="padding:6px 14px; border:none; border-radius:var(--radius-sm); background:transparent; color:var(--text-secondary); font-size:0.8rem; font-weight:600; cursor:pointer; display:inline-flex; align-items:center; gap:6px;">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <span>Live PDF Preview</span>
              </button>
            </div>
          </div>
          
          <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:18px;">
            <!-- Status Filter -->
            <div>
              <label style="font-size:0.82rem; font-weight:600; color:var(--text-secondary); display:block; margin-bottom:8px;">Included Statuses</label>
              <div style="display:flex; flex-wrap:wrap; gap:10px;">
                <label style="font-size:0.8rem; color:var(--text-primary); cursor:pointer;"><input type="checkbox" class="export-status-cb" value="SETTLED" checked> <span style="color:#10b981; font-weight:600;">SETTLED</span></label>
                <label style="font-size:0.8rem; color:var(--text-primary); cursor:pointer;"><input type="checkbox" class="export-status-cb" value="MATCHED" checked> <span style="color:#3b82f6; font-weight:600;">MATCHED</span></label>
                <label style="font-size:0.8rem; color:var(--text-primary); cursor:pointer;"><input type="checkbox" class="export-status-cb" value="SIMILAR" checked> <span style="color:#f59e0b; font-weight:600;">SIMILAR</span></label>
                <label style="font-size:0.8rem; color:var(--text-primary); cursor:pointer;"><input type="checkbox" class="export-status-cb" value="UNMATCHED" checked> <span style="color:#ef4444; font-weight:600;">EXCEPTION</span></label>
              </div>
            </div>

            <!-- Statement Source Filter -->
            <div>
              <label style="font-size:0.82rem; font-weight:600; color:var(--text-secondary); display:block; margin-bottom:8px;">Statement Source Filter</label>
              <select id="exportSourceSelect" style="width:100%; padding:7px 10px; border:1px solid var(--border); border-radius:var(--radius-md); background:var(--bg-elevated); color:var(--text-primary); font-size:0.82rem;">
                ${stOptionsHtml}
              </select>
            </div>

            <!-- Date Range Picker -->
            <div>
              <label style="font-size:0.82rem; font-weight:600; color:var(--text-secondary); display:block; margin-bottom:8px;">Date Range Filter</label>
              <div style="display:flex; gap:6px; align-items:center;">
                <input type="date" id="exportStartDate" style="flex:1; padding:5px 8px; border:1px solid var(--border); border-radius:var(--radius-md); background:var(--bg-elevated); color:var(--text-primary); font-size:0.78rem;">
                <span style="color:var(--text-muted); font-size:0.78rem;">to</span>
                <input type="date" id="exportEndDate" style="flex:1; padding:5px 8px; border:1px solid var(--border); border-radius:var(--radius-md); background:var(--bg-elevated); color:var(--text-primary); font-size:0.78rem;">
              </div>
            </div>
          </div>

          <!-- Included Sections -->
          <div style="margin-top:16px; padding-top:14px; border-top:1px dashed var(--border);">
            <label style="font-size:0.82rem; font-weight:600; color:var(--text-secondary); display:block; margin-bottom:8px;">Included Report Sections</label>
            <div style="display:flex; flex-wrap:wrap; gap:16px;">
              <label style="font-size:0.8rem; color:var(--text-primary); cursor:pointer;"><input type="checkbox" class="export-section-cb" value="summary" checked> Executive Summary</label>
              <label style="font-size:0.8rem; color:var(--text-primary); cursor:pointer;"><input type="checkbox" class="export-section-cb" value="charts" checked> Analytics Data</label>
              <label style="font-size:0.8rem; color:var(--text-primary); cursor:pointer;"><input type="checkbox" class="export-section-cb" value="transactions" checked> Transaction Table</label>
              <label style="font-size:0.8rem; color:var(--text-primary); cursor:pointer;"><input type="checkbox" class="export-section-cb" value="exceptions" checked> Exception Ledger</label>
              <label style="font-size:0.8rem; color:var(--text-primary); cursor:pointer;"><input type="checkbox" class="export-section-cb" value="integrity" checked> System Integrity</label>
            </div>
          </div>

          <!-- Multi-Format Export Action Bar -->
          <div style="margin-top:18px; padding:14px 18px; background:var(--bg-elevated); border:1px solid var(--border); border-radius:var(--radius-md); display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px;">
            <div id="exportPreviewSummary" style="font-size:0.82rem; font-weight:600; color:var(--text-primary);">
              Filter Scope: <b>All 4 statuses</b>, <b>All statements</b>, <b>5 sections</b> selected.
            </div>
            <div style="display:flex; flex-wrap:wrap; gap:8px;">
              <button type="button" onclick="window.downloadReportExport('xlsx')" style="display:inline-flex; align-items:center; gap:6px; padding:8px 14px; background:#10b981; color:#fff; border:none; border-radius:var(--radius-md); font-size:0.82rem; font-weight:600; cursor:pointer;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>
                <span>Export Excel (.xlsx)</span>
              </button>
              <button type="button" onclick="window.downloadReportExport('pdf')" style="display:inline-flex; align-items:center; gap:6px; padding:8px 14px; background:var(--accent-blue); color:#fff; border:none; border-radius:var(--radius-md); font-size:0.82rem; font-weight:600; cursor:pointer;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <span>Download PDF</span>
              </button>
              <button type="button" onclick="window.downloadReportExport('csv')" style="display:inline-flex; align-items:center; gap:6px; padding:8px 14px; background:var(--bg-surface); color:var(--text-primary); border:1px solid var(--border); border-radius:var(--radius-md); font-size:0.82rem; font-weight:600; cursor:pointer;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                <span>CSV</span>
              </button>
              <button type="button" onclick="window.downloadReportExport('markdown')" style="display:inline-flex; align-items:center; gap:6px; padding:8px 14px; background:var(--bg-surface); color:var(--text-primary); border:1px solid var(--border); border-radius:var(--radius-md); font-size:0.82rem; font-weight:600; cursor:pointer;">
                <span>Markdown</span>
              </button>
            </div>
          </div>
        </div>`;

      // Formatted Executive Dashboard Card & Table View HTML
      const totalTxns = summary.total_transactions || 0;
      const matchPct = (summary.percent_reconciled || 0).toFixed(1);
      const varAmt = (summary.variance || 0).toLocaleString('en-IN', { style: 'currency', currency: 'INR' });
      const excCount = summary.unmatched_count || 0;
      const settledCount = summary.settled_count || 0;
      const matchedCount = summary.matched_count || 0;
      const similarCount = summary.similar_count || 0;

      const reportExecUI = `
        <div id="reportExecView" style="display:block;">
          <!-- KPI Summary Row -->
          <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:16px; margin-bottom:24px;">
            <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:18px 20px;">
              <div style="font-size:0.78rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px;">Transactions Processed</div>
              <div style="font-size:1.6rem; font-weight:700; color:var(--text-primary);">${totalTxns.toLocaleString()}</div>
              <div style="font-size:0.75rem; color:var(--text-secondary); margin-top:4px;">Authoritative Reconciliation Scope</div>
            </div>

            <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:18px 20px;">
              <div style="font-size:0.78rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px;">Parity Reconciliation Rate</div>
              <div style="font-size:1.6rem; font-weight:700; color:#10b981;">${matchPct}%</div>
              <div style="font-size:0.75rem; color:var(--text-secondary); margin-top:4px;">Zero-variance parity match</div>
            </div>

            <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:18px 20px;">
              <div style="font-size:0.78rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px;">Net Discrepancy Variance</div>
              <div style="font-size:1.6rem; font-weight:700; color:#3b82f6;">${varAmt}</div>
              <div style="font-size:0.75rem; color:var(--text-secondary); margin-top:4px;">Deposits vs Payments net diff</div>
            </div>

            <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:18px 20px;">
              <div style="font-size:0.78rem; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px;">Open Audit Exceptions</div>
              <div style="font-size:1.6rem; font-weight:700; color:#ef4444;">${excCount}</div>
              <div style="font-size:0.75rem; color:var(--text-secondary); margin-top:4px;">Flagged for review in Exception Ledger</div>
            </div>
          </div>

          <!-- Status Outcomes & Integrity Section -->
          <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap:20px; margin-bottom:24px;">
            <!-- Status Breakdown -->
            <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:20px;">
              <h4 style="font-size:0.95rem; font-weight:700; color:var(--text-primary); margin:0 0 14px;">Settlement Taxonomy Outcomes</h4>
              <div style="display:flex; flex-direction:column; gap:10px;">
                <div style="display:flex; align-items:center; justify-content:space-between; padding:10px 12px; background:var(--bg-elevated); border-radius:var(--radius-md);">
                  <div style="display:flex; align-items:center; gap:8px;">
                    <span style="width:10px; height:10px; border-radius:50%; background:#10b981; display:inline-block;"></span>
                    <span style="font-size:0.85rem; font-weight:600; color:var(--text-primary);">SETTLED</span>
                  </div>
                  <span style="font-size:0.9rem; font-weight:700; color:var(--text-primary);">${settledCount}</span>
                </div>

                <div style="display:flex; align-items:center; justify-content:space-between; padding:10px 12px; background:var(--bg-elevated); border-radius:var(--radius-md);">
                  <div style="display:flex; align-items:center; gap:8px;">
                    <span style="width:10px; height:10px; border-radius:50%; background:#3b82f6; display:inline-block;"></span>
                    <span style="font-size:0.85rem; font-weight:600; color:var(--text-primary);">MATCHED</span>
                  </div>
                  <span style="font-size:0.9rem; font-weight:700; color:var(--text-primary);">${matchedCount}</span>
                </div>

                <div style="display:flex; align-items:center; justify-content:space-between; padding:10px 12px; background:var(--bg-elevated); border-radius:var(--radius-md);">
                  <div style="display:flex; align-items:center; gap:8px;">
                    <span style="width:10px; height:10px; border-radius:50%; background:#f59e0b; display:inline-block;"></span>
                    <span style="font-size:0.85rem; font-weight:600; color:var(--text-primary);">SIMILAR</span>
                  </div>
                  <span style="font-size:0.9rem; font-weight:700; color:var(--text-primary);">${similarCount}</span>
                </div>

                <div style="display:flex; align-items:center; justify-content:space-between; padding:10px 12px; background:var(--bg-elevated); border-radius:var(--radius-md);">
                  <div style="display:flex; align-items:center; gap:8px;">
                    <span style="width:10px; height:10px; border-radius:50%; background:#ef4444; display:inline-block;"></span>
                    <span style="font-size:0.85rem; font-weight:600; color:var(--text-primary);">EXCEPTION / UNMATCHED</span>
                  </div>
                  <span style="font-size:0.9rem; font-weight:700; color:var(--text-primary);">${excCount}</span>
                </div>
              </div>
            </div>

            <!-- Integrity Card -->
            <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:20px; display:flex; flex-direction:column; justify-content:space-between;">
              <div>
                <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
                  <h4 style="font-size:0.95rem; font-weight:700; color:var(--text-primary); margin:0;">Integrity Audit Verification</h4>
                  <span style="padding:4px 10px; border-radius:12px; background:rgba(16,185,129,0.15); color:#10b981; font-size:0.75rem; font-weight:700; letter-spacing:0.5px;">
                    ${integrity.pass ? 'AUDIT VERIFIED PASS' : 'ATTENTION REQUIRED'}
                  </span>
                </div>
                <p style="font-size:0.82rem; color:var(--text-secondary); line-height:1.5; margin:0 0 16px;">
                  Ensures 100% accounting completeness. Total accounted records match input dataset count with zero floating discrepancy loss.
                </p>
                <div style="font-size:0.85rem; color:var(--text-primary);">
                  Accounted Records: <b>${integrity.accounted_for || 0} / ${integrity.total_transactions || 0}</b>
                </div>
              </div>
              <div style="margin-top:16px; padding-top:12px; border-top:1px solid var(--border); font-size:0.78rem; color:var(--text-muted);">
                Audited at ${reportData.meta?.generated_at || 'Just now'} by Ledger AI Engine.
              </div>
            </div>
          </div>

          <!-- Transaction Records Audit Table Preview -->
          <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:20px; margin-bottom:24px;">
            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; flex-wrap:wrap; gap:10px;">
              <h4 style="font-size:0.95rem; font-weight:700; color:var(--text-primary); margin:0;">
                Transaction Audit Records (${transactions.length})
              </h4>
              <input type="text" id="reportTxSearch" onkeyup="window.filterReportTxTable()" placeholder="Search transactions…" style="padding:6px 12px; border:1px solid var(--border); border-radius:var(--radius-md); background:var(--bg-elevated); color:var(--text-primary); font-size:0.8rem; width:220px;">
            </div>

            <div style="overflow-x:auto; max-height:420px; overflow-y:auto; border:1px solid var(--border); border-radius:var(--radius-md);">
              <table id="reportTxTable" style="width:100%; border-collapse:collapse; font-size:0.82rem; text-align:left;">
                <thead>
                  <tr style="background:var(--bg-elevated); border-bottom:1px solid var(--border); color:var(--text-muted); position:sticky; top:0; z-index:2;">
                    <th style="padding:10px 14px; font-weight:600;">Date</th>
                    <th style="padding:10px 14px; font-weight:600;">Primary ID</th>
                    <th style="padding:10px 14px; font-weight:600;">Description</th>
                    <th style="padding:10px 14px; font-weight:600;">Source</th>
                    <th style="padding:10px 14px; font-weight:600; text-align:right;">Amount (₹)</th>
                    <th style="padding:10px 14px; font-weight:600;">Taxonomy</th>
                    <th style="padding:10px 14px; font-weight:600;">Engine Rule</th>
                  </tr>
                </thead>
                <tbody>
                  ${transactions.length === 0 ? `<tr><td colspan="7" style="text-align:center; padding:30px; color:var(--text-muted);">No transaction records match the selected scope.</td></tr>` :
          transactions.slice(0, 100).map(t => {
            const st = (t.taxonomy_status || t.status || 'UNMATCHED').toUpperCase();
            let badgeBg = 'rgba(239, 68, 68, 0.15)', badgeColor = '#ef4444';
            if (st === 'SETTLED') { badgeBg = 'rgba(16, 185, 129, 0.15)'; badgeColor = '#10b981'; }
            else if (st === 'MATCHED') { badgeBg = 'rgba(59, 130, 246, 0.15)'; badgeColor = '#3b82f6'; }
            else if (st === 'SIMILAR') { badgeBg = 'rgba(245, 158, 11, 0.15)'; badgeColor = '#f59e0b'; }

            const amtStr = (t.amount || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            return `
                        <tr style="border-bottom:1px solid var(--border); color:var(--text-secondary);">
                          <td style="padding:8px 14px; white-space:nowrap;">${t.date || 'N/A'}</td>
                          <td style="padding:8px 14px; font-family:var(--font-mono); font-size:0.78rem;">${t.settlement_id || t.id || 'N/A'}</td>
                          <td style="padding:8px 14px; max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${t.description || ''}</td>
                          <td style="padding:8px 14px;">${t.source_name || t.source_type || 'Statement'}</td>
                          <td style="padding:8px 14px; text-align:right; font-weight:600; color:var(--text-primary);">₹${amtStr}</td>
                          <td style="padding:8px 14px;"><span style="padding:3px 8px; border-radius:10px; background:${badgeBg}; color:${badgeColor}; font-size:0.72rem; font-weight:700;">${st}</span></td>
                          <td style="padding:8px 14px; font-size:0.78rem; color:var(--text-muted);">${t.reason || t.stage || 'Pipeline Engine'}</td>
                        </tr>
                      `;
          }).join('')
        }
                </tbody>
              </table>
            </div>
            ${transactions.length > 100 ? `<div style="font-size:0.75rem; color:var(--text-muted); margin-top:8px; text-align:right;">Displaying top 100 of ${transactions.length} records in web preview. Use Export Excel for complete dataset.</div>` : ''}
          </div>

          <!-- Exception Detail Table -->
          ${exceptions.length > 0 ? `
            <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:20px;">
              <h4 style="font-size:0.95rem; font-weight:700; color:var(--text-primary); margin:0 0 14px;">
                Exception Ledger Audit Log (${exceptions.length})
              </h4>
              <div style="overflow-x:auto; border:1px solid var(--border); border-radius:var(--radius-md);">
                <table style="width:100%; border-collapse:collapse; font-size:0.82rem; text-align:left;">
                  <thead>
                    <tr style="background:var(--bg-elevated); border-bottom:1px solid var(--border); color:var(--text-muted);">
                      <th style="padding:10px 14px; font-weight:600;">Exception ID</th>
                      <th style="padding:10px 14px; font-weight:600;">Settlement ID</th>
                      <th style="padding:10px 14px; font-weight:600;">Bank Transaction ID</th>
                      <th style="padding:10px 14px; font-weight:600;">Exception Type</th>
                      <th style="padding:10px 14px; font-weight:600;">Priority</th>
                      <th style="padding:10px 14px; font-weight:600;">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${exceptions.map(e => `
                      <tr style="border-bottom:1px solid var(--border); color:var(--text-secondary);">
                        <td style="padding:8px 14px; font-family:var(--font-mono); font-size:0.78rem;">${e.exception_id || e.id || 'EXC-001'}</td>
                        <td style="padding:8px 14px; font-family:var(--font-mono); font-size:0.78rem;">${e.settlement_id || 'N/A'}</td>
                        <td style="padding:8px 14px; font-family:var(--font-mono); font-size:0.78rem;">${e.bank_transaction_id || 'N/A'}</td>
                        <td style="padding:8px 14px;">${e.exception_type || 'automated_unmatched'}</td>
                        <td style="padding:8px 14px;"><span style="padding:2px 6px; border-radius:4px; background:rgba(245,158,11,0.15); color:#f59e0b; font-size:0.72rem; font-weight:700;">${(e.priority || 'medium').toUpperCase()}</span></td>
                        <td style="padding:8px 14px;"><span style="padding:2px 6px; border-radius:4px; background:rgba(239,68,68,0.15); color:#ef4444; font-size:0.72rem; font-weight:700;">${(e.resolution_status || 'open').toUpperCase()}</span></td>
                      </tr>
                    `).join('')}
                  </tbody>
                </table>
              </div>
            </div>
          ` : ''}
        </div>

        <!-- Embedded PDF Viewer Panel -->
        <div id="reportPdfView" style="display:none;">
          <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; padding:10px 16px; background:var(--bg-elevated); border:1px solid var(--border); border-radius:var(--radius-md);">
            <div style="font-size:0.85rem; font-weight:600; color:var(--text-primary); display:flex; align-items:center; gap:8px;">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              <span>Live Executive Audit PDF Preview</span>
            </div>
            <div style="display:flex; gap:8px;">
              <a id="btnReportPdfOpenTab" href="/api/reports/export?format=pdf&inline=true" target="_blank" style="padding:5px 12px; background:var(--bg-surface); color:var(--text-primary); border:1px solid var(--border); border-radius:var(--radius-sm); font-size:0.78rem; font-weight:600; text-decoration:none; display:inline-flex; align-items:center; gap:6px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                <span>Open in New Tab</span>
              </a>
              <button type="button" onclick="window.downloadReportExport('pdf')" style="padding:5px 12px; background:var(--accent-blue); color:#fff; border:none; border-radius:var(--radius-sm); font-size:0.78rem; font-weight:600; cursor:pointer; display:inline-flex; align-items:center; gap:6px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                <span>Download PDF File</span>
              </button>
            </div>
          </div>
          <object id="reportPdfObject" data="/api/reports/export?format=pdf&inline=true#toolbar=1&navpanes=0&view=FitH" type="application/pdf" style="width:100%; height:820px; border:1px solid var(--border); border-radius:var(--radius-lg); background:#0f172a;">
            <iframe id="reportPdfIframe" src="/api/reports/export?format=pdf&inline=true#toolbar=1&navpanes=0&view=FitH" style="width:100%; height:820px; border:none; border-radius:var(--radius-lg); background:#0f172a;"></iframe>
          </object>
        </div>
      `;

      el.innerHTML = exportOptionsUI + reportExecUI;
      _bindExportPreviewEvents();
    }).catch(err => {
      console.error(err);
      el.innerHTML = '<div style="color:var(--color-danger);padding:20px;text-align:center;">Failed to load audit report. Check server connection.</div>';
    });
  }

  function _bindExportPreviewEvents() {
    const updatePreview = () => {
      const statuses = Array.from(document.querySelectorAll(".export-status-cb:checked")).map(cb => cb.value);
      const stSelect = document.getElementById("exportSourceSelect");
      const srcText = stSelect ? stSelect.options[stSelect.selectedIndex].text : "All Statements";
      const sections = Array.from(document.querySelectorAll(".export-section-cb:checked")).map(cb => cb.value);
      const previewEl = document.getElementById("exportPreviewSummary");
      if (previewEl) {
        previewEl.innerHTML = `Filter Scope: <b>${statuses.length} statuses</b> (${statuses.join(", ") || "None"}), <b>Source: ${srcText}</b>, <b>${sections.length} sections</b> selected.`;
      }
    };

    document.querySelectorAll(".export-status-cb, .export-section-cb").forEach(cb => cb.addEventListener("change", updatePreview));
    const stSel = document.getElementById("exportSourceSelect");
    if (stSel) stSel.addEventListener("change", updatePreview);
    const startInp = document.getElementById("exportStartDate");
    const endInp = document.getElementById("exportEndDate");
    if (startInp) startInp.addEventListener("change", updatePreview);
    if (endInp) endInp.addEventListener("change", updatePreview);
  }

  window.switchReportViewMode = function (mode) {
    const execView = document.getElementById("reportExecView");
    const pdfView = document.getElementById("reportPdfView");
    const btnExec = document.getElementById("btnViewReportExec");
    const btnPdf = document.getElementById("btnViewReportPdf");

    if (mode === "pdf") {
      if (execView) execView.style.display = "none";
      if (pdfView) pdfView.style.display = "block";
      if (btnExec) { btnExec.style.background = "transparent"; btnExec.style.color = "var(--text-secondary)"; }
      if (btnPdf) { btnPdf.style.background = "var(--accent-blue)"; btnPdf.style.color = "#fff"; }

      const statuses = Array.from(document.querySelectorAll(".export-status-cb:checked")).map(cb => cb.value);
      const sourceVal = document.getElementById("exportSourceSelect")?.value || "all";
      const startDate = document.getElementById("exportStartDate")?.value || "";
      const endDate = document.getElementById("exportEndDate")?.value || "";
      const sections = Array.from(document.querySelectorAll(".export-section-cb:checked")).map(cb => cb.value);

      const params = new URLSearchParams({
        format: "pdf",
        inline: "true",
        source: sourceVal,
        start_date: startDate,
        end_date: endDate,
        statuses: statuses.join(","),
        sections: sections.join(",")
      });

      const pdfUrl = `/api/reports/export?${params.toString()}#toolbar=1&navpanes=0&view=FitH`;
      const openTabBtn = document.getElementById("btnReportPdfOpenTab");
      if (openTabBtn) openTabBtn.href = `/api/reports/export?${params.toString()}`;

      const pdfObj = document.getElementById("reportPdfObject");
      const pdfIframe = document.getElementById("reportPdfIframe");
      if (pdfObj) pdfObj.data = pdfUrl;
      if (pdfIframe) pdfIframe.src = pdfUrl;
    } else {
      if (execView) execView.style.display = "block";
      if (pdfView) pdfView.style.display = "none";
      if (btnExec) { btnExec.style.background = "var(--accent-blue)"; btnExec.style.color = "#fff"; }
      if (btnPdf) { btnPdf.style.background = "transparent"; btnPdf.style.color = "var(--text-secondary)"; }
    }
  };

  window.filterReportTxTable = function () {
    const input = document.getElementById("reportTxSearch");
    const filter = input ? input.value.toLowerCase() : "";
    const table = document.getElementById("reportTxTable");
    if (!table) return;
    const trs = table.getElementsByTagName("tr");
    for (let i = 1; i < trs.length; i++) {
      const text = trs[i].textContent || trs[i].innerText;
      trs[i].style.display = text.toLowerCase().indexOf(filter) > -1 ? "" : "none";
    }
  };

  window.downloadReportExport = function (format) {
    const statuses = Array.from(document.querySelectorAll(".export-status-cb:checked")).map(cb => cb.value);
    const sourceVal = document.getElementById("exportSourceSelect")?.value || "all";
    const startDate = document.getElementById("exportStartDate")?.value || "";
    const endDate = document.getElementById("exportEndDate")?.value || "";
    const sections = Array.from(document.querySelectorAll(".export-section-cb:checked")).map(cb => cb.value);

    const payload = {
      format: format,
      statuses: statuses,
      sources: [sourceVal],
      start_date: startDate,
      end_date: endDate,
      sections: sections
    };

    fetch("/api/reports/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(res => {
        if (!res.ok) throw new Error("Server returned status " + res.status);
        return res.blob();
      })
      .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        let filename = "ledger_reconciliation_report.pdf";
        if (format === "xlsx" || format === "excel") filename = "ledger_reconciliation_report.xlsx";
        else if (format === "csv") filename = "ledger_reconciliation_report.csv";
        else if (format === "markdown" || format === "md") filename = "ledger_reconciliation_report.md";
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
      })
      .catch(err => {
        alert("Failed to download report: " + err.message);
      });
  };


  function _loadConfigPanel(force) {
    if (_panelLoaded.config && !force) return;
    const el = document.getElementById("configContent");
    if (!el) return;
    fetch("/api/config").then(r => r.json()).then(data => {
      _panelLoaded.config = true;
      const cfg = data.config || {};
      const groups = [
        { title: "Amount Tolerances & Fees", icon: "", keys: ["absolute_amount_tolerance", "percentage_tolerance", "max_tolerance_cap", "default_fee_percentage", "default_tax_rate"] },
        { title: "Date Windows & Quality", icon: "", keys: ["max_date_difference_days", "settlement_window_days", "min_narration_similarity", "column_mapping_confidence_floor"] },
        { title: "ML & LLM Decision Gates", icon: "", keys: ["ml_match_threshold", "ml_review_threshold", "minimum_score_margin", "llm_match_threshold"] },
      ];
      const fmtKey = k => k.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());
      const fmtVal = (k, v) => {
        if (v === null || v === undefined) return "—";
        if (k.includes("percentage") || k.includes("threshold") || k.includes("similarity") || k.includes("floor") || k.includes("margin") || k.includes("tax_rate") || k.includes("fee_pct")) {
          const pct = parseFloat(v);
          return isNaN(pct) ? v : (pct <= 1 ? (pct * 100).toFixed(2) + "%" : v);
        }
        if (k.includes("tolerance") || k.includes("cap")) return "₹" + parseFloat(v).toFixed(2);
        if (k.includes("days")) return v + " days";
        return v;
      };

      const mlGate = cfg.ml_match_threshold ? (parseFloat(cfg.ml_match_threshold) * (parseFloat(cfg.ml_match_threshold) <= 1 ? 100 : 1)).toFixed(0) + "%" : "80%";
      const llmGate = cfg.llm_match_threshold ? (parseFloat(cfg.llm_match_threshold) * (parseFloat(cfg.llm_match_threshold) <= 1 ? 100 : 1)).toFixed(0) + "%" : "70%";

      el.innerHTML = `
        <!-- Model Performance KPI Row -->
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:14px; margin-bottom:20px;">
          <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:14px 18px;">
            <div style="font-size:0.75rem; font-weight:700; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px;">Rule Matching Engine</div>
            <div style="font-family:var(--font-mono); font-size:1.4rem; font-weight:700; color:var(--color-success);">Deterministic</div>
            <div style="font-size:0.78rem; color:var(--text-secondary); margin-top:4px;">1:1 & Multi-source clustering</div>
          </div>
          <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:14px 18px;">
            <div style="font-size:0.75rem; font-weight:700; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px;">ML Match Confidence</div>
            <div style="font-family:var(--font-mono); font-size:1.4rem; font-weight:700; color:var(--accent-blue);">${mlGate}</div>
            <div style="font-size:0.78rem; color:var(--text-secondary); margin-top:4px;">Minimum match score threshold</div>
          </div>
          <div style="background:var(--bg-surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:14px 18px;">
            <div style="font-size:0.75rem; font-weight:700; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px;">LLM Reasoning Gate</div>
            <div style="font-family:var(--font-mono); font-size:1.4rem; font-weight:700; color:var(--accent-blue);">${llmGate}</div>
            <div style="font-size:0.78rem; color:var(--text-secondary); margin-top:4px;">Smart agent validation floor</div>
          </div>
        </div>

        <!-- Parameter Groups Grid -->
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;">${groups.map(g => `<div style="background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:18px;">
            <div style="font-size:var(--text-sm);font-weight:700;color:var(--text-primary);margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid var(--border);">${g.title}</div>
            ${g.keys.filter(k => cfg[k] !== undefined).map(k =>
        `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);">
                <span style="font-size:var(--text-sm);color:var(--text-secondary);">${fmtKey(k)}</span>
                <span style="font-family:var(--font-mono);font-size:var(--text-sm);color:var(--accent-blue);background:var(--accent-blue-subtle);padding:3px 10px;border-radius:var(--radius-sm);border:1px solid var(--accent-blue-border);">${fmtVal(k, cfg[k])}</span>
              </div>`
      ).join("")}
          </div>`).join("")
        }</div>`;
    }).catch(() => {
      el.innerHTML = '<div style="color:var(--color-danger);padding:20px;font-size:var(--text-sm);text-align:center;">Failed to load configuration parameters.</div>';
    });
  }

  function _loadOverviewPanel(force) {
    if (_panelLoaded.overview && !force) return;
    const wrap = document.getElementById("overviewPanelContent");
    if (!wrap) return;

    wrap.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;height:240px;color:var(--text-muted);gap:10px;font-size:var(--text-sm);">
        <svg class="spin-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
        Loading executive overview...
      </div>`;

    Promise.all([
      fetch("/api/reconciliation").then(r => r.ok ? r.json() : {}).catch(() => ({})),
      fetch("/api/statements").then(r => r.ok ? r.json() : {}).catch(() => ({}))
    ]).then(([reconRes, stmtRes]) => {
      _panelLoaded.overview = true;
      const run = reconRes.run || {};
      const s = run.summary || {};
      const total = s.total_transactions || 0;
      const autoMatched = s.auto_matched || 0;
      const manualMatched = s.manual_matched || 0;
      const totalMatched = autoMatched + manualMatched;
      const unmatched = s.unreconciled || 0;
      const pct = s.percent_reconciled !== undefined ? s.percent_reconciled.toFixed(1) : (total ? ((totalMatched / total) * 100).toFixed(1) : "0.0");
      const variance = s.variance !== undefined ? s.variance : 0;
      const deposits = s.deposits_total || 0;
      const payments = s.payments_total || 0;

      const statements = stmtRes.statements || [];

      wrap.innerHTML = `
        <div style="padding: 24px 28px; max-width: 1100px; margin: 0 auto;">
          <!-- Executive Header -->
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border);">
            <div>
              <div style="display: flex; align-items: center; gap: 10px;">
                <h2 style="font-size: 1.35rem; font-weight: 700; color: var(--text-primary); margin: 0;">Executive Overview</h2>
                <span style="font-size: 0.72rem; font-weight: 700; padding: 3px 10px; border-radius: 12px; background: ${total ? 'var(--accent-blue-subtle)' : 'var(--bg-elevated)'}; color: ${total ? 'var(--accent-blue)' : 'var(--text-muted)'}; border: 1px solid var(--border);">
                  ${total ? (run.closed ? 'FULLY CLOSED' : 'ACTIVE RUN') : 'AWAITING RUN'}
                </span>
              </div>
              <p style="font-size: 0.88rem; color: var(--text-muted); margin: 4px 0 0;">Real-time automated reconciliation status & financial balance integrity</p>
            </div>
            <div style="display: flex; gap: 10px;">
              <button type="button" onclick="activateSub('sub-reconcile')" style="display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; background: var(--accent-blue); color: #fff; border: none; border-radius: var(--radius-md); font-size: var(--text-sm); font-weight: 600; cursor: pointer;">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><polyline points="21 3 21 8 16 8"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><polyline points="3 21 3 16 8 16"/></svg>
                <span>Auto Match</span>
              </button>
            </div>
          </div>

          <!-- 4 Core Metric Cards Grid -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px;">
            <!-- Card 1: Total Transactions -->
            <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 18px 20px;">
              <div style="font-size: 0.75rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px;">Total Transactions</div>
              <div style="font-family: var(--font-mono); font-size: 1.8rem; font-weight: 700; color: var(--text-primary); margin-bottom: 6px;">${total.toLocaleString()}</div>
              <div style="font-size: 0.8rem; color: var(--text-secondary);">
                Payments: <span style="color: #ef4444; font-weight: 600;">-${formatMoney(Math.abs(payments), false)}</span> | Deposits: <span style="color: #10b981; font-weight: 600;">+${formatMoney(Math.abs(deposits), false)}</span>
              </div>
            </div>

            <!-- Card 2: Auto-Matched Rate -->
            <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 18px 20px;">
              <div style="font-size: 0.75rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px;">Matched Rate</div>
              <div style="font-family: var(--font-mono); font-size: 1.8rem; font-weight: 700; color: var(--color-success); margin-bottom: 6px;">${pct}%</div>
              <div style="font-size: 0.8rem; color: var(--text-secondary);">${totalMatched} of ${total} entries reconciled</div>
            </div>

            <!-- Card 3: Open Exception Items -->
            <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 18px 20px;">
              <div style="font-size: 0.75rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px;">Open Exceptions</div>
              <div style="font-family: var(--font-mono); font-size: 1.8rem; font-weight: 700; color: ${unmatched > 0 ? 'var(--color-warning)' : 'var(--text-primary)'}; margin-bottom: 6px;">${unmatched}</div>
              <div style="font-size: 0.8rem; color: var(--text-secondary);">${unmatched ? 'Requires manual audit review' : 'No open exceptions'}</div>
            </div>

            <!-- Card 4: Unreconciled Variance -->
            <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 18px 20px;">
              <div style="font-size: 0.75rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px;">Unreconciled Discrepancy</div>
              <div style="font-family: var(--font-mono); font-size: 1.6rem; font-weight: 700; color: ${variance > 0 ? 'var(--color-danger)' : 'var(--text-primary)'}; margin-bottom: 6px;">${formatMoney(variance, false)}</div>
              <div style="font-size: 0.8rem; color: var(--text-secondary);">Net variance balance</div>
            </div>
          </div>

          <!-- Reconciliation Match Progress Bar -->
          <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px 24px; margin-bottom: 24px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
              <div style="font-size: 0.85rem; font-weight: 700; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.04em;">Reconciliation Health & Match Progress</div>
              <div style="font-family: var(--font-mono); font-size: 0.9rem; font-weight: 700; color: var(--color-success);">${pct}% Matched</div>
            </div>
            <div style="height: 12px; background: var(--bg-elevated); border-radius: 999px; overflow: hidden; display: flex; border: 1px solid var(--border);">
              <div style="height: 100%; width: ${pct}%; background: var(--color-success); transition: width 0.6s ease;" title="Matched: ${pct}%"></div>
              <div style="height: 100%; width: ${total ? ((unmatched / total) * 100).toFixed(1) : 0}%; background: var(--color-warning); transition: width 0.6s ease;" title="Exceptions: ${unmatched}"></div>
            </div>
            <div style="display: flex; gap: 24px; margin-top: 12px; font-size: 0.82rem; color: var(--text-secondary);">
              <div style="display: flex; align-items: center; gap: 6px;">
                <span style="width: 8px; height: 8px; border-radius: 50%; background: var(--color-success);"></span>
                <span>Auto-Matched (${autoMatched})</span>
              </div>
              <div style="display: flex; align-items: center; gap: 6px;">
                <span style="width: 8px; height: 8px; border-radius: 50%; background: var(--color-warning);"></span>
                <span>Exceptions (${unmatched})</span>
              </div>
            </div>
          </div>

          <!-- PART 9 OVERVIEW CHARTS GRID (6 Charts) -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(440px, 1fr)); gap: 20px; margin-bottom: 24px;">
            
            <!-- Chart 1: Status Breakdown (Donut) -->
            <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px 24px; min-height: 320px; display: flex; flex-direction: column;">
              <div style="margin-bottom: 14px;">
                <div style="font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">Taxonomy Status Breakdown</div>
                <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 2px;">SETTLED vs MATCHED vs SIMILAR vs UNMATCHED distribution</div>
              </div>
              <div style="flex: 1; position: relative; width: 100%; min-height: 230px;">
                <canvas id="chartStatusBreakdown"></canvas>
              </div>
            </div>

            <!-- Chart 2: Reconciliation Funnel -->
            <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px 24px; min-height: 320px; display: flex; flex-direction: column;">
              <div style="margin-bottom: 14px;">
                <div style="font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">Reconciliation Pipeline Funnel</div>
                <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 2px;">Transaction volume flow across pipeline stages</div>
              </div>
              <div style="flex: 1; position: relative; width: 100%; min-height: 230px;">
                <canvas id="chartReconFunnel"></canvas>
              </div>
            </div>

            <!-- Chart 3: Source-wise Contribution (Stacked Bar) -->
            <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px 24px; min-height: 320px; display: flex; flex-direction: column;">
              <div style="margin-bottom: 14px;">
                <div style="font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">Source-Wise Contribution & Exceptions</div>
                <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 2px;">Taxonomy status breakdown per statement source</div>
              </div>
              <div style="flex: 1; position: relative; width: 100%; min-height: 230px;">
                <canvas id="chartSourceContribution"></canvas>
              </div>
            </div>

            <!-- Chart 4: Confidence Score Distribution Histogram -->
            <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px 24px; min-height: 320px; display: flex; flex-direction: column;">
              <div style="margin-bottom: 14px;">
                <div style="font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">Confidence Score Distribution</div>
                <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 2px;">Scoring engine calibration & match mass distribution</div>
              </div>
              <div style="flex: 1; position: relative; width: 100%; min-height: 230px;">
                <canvas id="chartConfidenceDist"></canvas>
              </div>
            </div>

            <!-- Chart 5: Exception Aging Chart -->
            <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px 24px; min-height: 320px; display: flex; flex-direction: column;">
              <div style="margin-bottom: 14px;">
                <div style="font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">Open Exception Aging</div>
                <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 2px;">Age buckets for SIMILAR / manual-review items</div>
              </div>
              <div style="flex: 1; position: relative; width: 100%; min-height: 230px;">
                <canvas id="chartExceptionAging"></canvas>
              </div>
            </div>

            <!-- Chart 6: Match Rate Trend Line -->
            <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px 24px; min-height: 320px; display: flex; flex-direction: column;">
              <div style="margin-bottom: 14px;">
                <div style="font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">Reconciliation Match Rate Trend</div>
                <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 2px;">Historical match percentage over pipeline import runs</div>
              </div>
              <div style="flex: 1; position: relative; width: 100%; min-height: 230px;">
                <canvas id="chartMatchTrend"></canvas>
              </div>
            </div>

          </div>

          <!-- Active Statement Sources -->
          <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px 24px; margin-bottom: 24px;">
            <div style="font-size: 0.85rem; font-weight: 700; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 16px;">
              Active Data Sources (${statements.length || 0})
            </div>
            ${statements.length === 0 ? `
              <div style="font-size: 0.88rem; color: var(--text-muted); text-align: center; padding: 24px 0;">
                No statement sources imported yet. Click "Import" in the sidebar to get started.
              </div>
            ` : `
              <div style="display: flex; flex-direction: column; gap: 10px;">
                ${statements.map(st => `
                  <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 8px;">
                    <div style="display: flex; align-items: center; gap: 12px;">
                      <span style="width: 10px; height: 10px; border-radius: 50%; background: ${st.color || 'var(--accent-blue)'};"></span>
                      <div>
                        <div style="font-size: 0.9rem; font-weight: 600; color: var(--text-primary);">${st.name || st.id}</div>
                        <div style="font-size: 0.78rem; color: var(--text-muted);">${(st.type || 'statement').toUpperCase()} · ${(st.row_count || st.rows || 0)} records</div>
                      </div>
                    </div>
                    <span style="font-size: 0.78rem; font-weight: 600; color: var(--color-success); background: rgba(50, 196, 141, 0.12); padding: 4px 10px; border-radius: 12px; border: 1px solid rgba(50, 196, 141, 0.3);">
                      Ingested
                    </span>
                  </div>
                `).join('')}
              </div>
            `}
          </div>

          <!-- Navigation Shortcuts -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px;">
            <div onclick="activateSub('sub-reconcile')" style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px; cursor: pointer; transition: border-color 0.2s ease;">
              <div style="font-size: 0.9rem; font-weight: 600; color: var(--text-primary); margin-bottom: 4px;">Explorer →</div>
              <div style="font-size: 0.8rem; color: var(--text-muted);">Inspect matched clusters and transaction details</div>
            </div>
            <div onclick="activateSub('sub-manual-review')" style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px; cursor: pointer; transition: border-color 0.2s ease;">
              <div style="font-size: 0.9rem; font-weight: 600; color: var(--text-primary); margin-bottom: 4px;">Exception Ledger →</div>
              <div style="font-size: 0.8rem; color: var(--text-muted);">Audit open exception items and manual overrides</div>
            </div>
            <div onclick="activateSub('sub-config')" style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px; cursor: pointer; transition: border-color 0.2s ease;">
              <div style="font-size: 0.9rem; font-weight: 600; color: var(--text-primary); margin-bottom: 4px;">Model Performance →</div>
              <div style="font-size: 0.8rem; color: var(--text-muted);">View matching engine rules and ML confidence gates</div>
            </div>
            <div onclick="activateSub('sub-reports')" style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px; cursor: pointer; transition: border-color 0.2s ease;">
              <div style="font-size: 0.9rem; font-weight: 600; color: var(--text-primary); margin-bottom: 4px;">Export Audit Run →</div>
              <div style="font-size: 0.8rem; color: var(--text-muted);">Download audit report and export run results</div>
            </div>
          </div>
        </div>`;

      setTimeout(() => _renderOverviewCharts(run.charts || {}, total), 60);
    }).catch(() => {
      if (wrap) wrap.innerHTML = '<div style="padding:40px;color:var(--text-muted);font-size:var(--text-sm);text-align:center;">Failed to load overview data. Please try again.</div>';
    });
  }

  let _overviewChartInstances = {};

  function _renderOverviewCharts(chartsData, total) {
    if (!chartsData) return;

    Object.keys(_overviewChartInstances).forEach(id => {
      if (_overviewChartInstances[id]) {
        try { _overviewChartInstances[id].destroy(); } catch (e) { }
      }
    });
    _overviewChartInstances = {};

    const hasData = total > 0;
    const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    const textColor = isDark ? '#94a3b8' : '#64748b';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.06)';

    if (!window.Chart) {
      console.warn("Chart.js library not loaded.");
      return;
    }

    // Chart 1: Status Breakdown Donut
    const canvas1 = document.getElementById("chartStatusBreakdown");
    if (canvas1) {
      if (!hasData) {
        _showChartEmptyPlaceholder(canvas1, "No transaction status breakdown available yet.");
      } else {
        const sb = chartsData.status_breakdown || {};
        _overviewChartInstances.statusBreakdown = new Chart(canvas1.getContext("2d"), {
          type: "doughnut",
          data: {
            labels: sb.labels || ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"],
            datasets: [{
              data: sb.counts || [0, 0, 0, 0],
              backgroundColor: ["#10b981", "#3b82f6", "#f59e0b", "#ef4444"],
              borderWidth: 2,
              borderColor: isDark ? "#0f172a" : "#ffffff",
              hoverOffset: 6
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { position: "bottom", labels: { color: textColor, font: { family: "Inter, sans-serif", size: 12 } } },
              tooltip: {
                callbacks: {
                  label: function (ctx) {
                    const cnt = ctx.raw || 0;
                    const pct = total ? ((cnt / total) * 100).toFixed(1) : 0;
                    return `${ctx.label}: ${cnt} (${pct}%)`;
                  }
                }
              }
            },
            cutout: "68%"
          }
        });
      }
    }

    // Chart 2: Reconciliation Funnel (Horizontal Bar)
    const canvas2 = document.getElementById("chartReconFunnel");
    if (canvas2) {
      if (!hasData) {
        _showChartEmptyPlaceholder(canvas2, "No pipeline volume flow available yet.");
      } else {
        const fn = chartsData.funnel_data || {};
        _overviewChartInstances.reconFunnel = new Chart(canvas2.getContext("2d"), {
          type: "bar",
          data: {
            labels: fn.stages || ["Total", "Auto", "Settled", "Similar", "Unmatched"],
            datasets: [{
              label: "Volume Flow",
              data: fn.counts || [0, 0, 0, 0, 0],
              backgroundColor: ["#6366f1", "#3b82f6", "#10b981", "#f59e0b", "#ef4444"],
              borderRadius: 6
            }]
          },
          options: {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { grid: { color: gridColor }, ticks: { color: textColor } },
              y: { grid: { display: false }, ticks: { color: textColor } }
            }
          }
        });
      }
    }

    // Chart 3: Source-wise Contribution (Stacked Bar)
    const canvas3 = document.getElementById("chartSourceContribution");
    if (canvas3) {
      if (!hasData) {
        _showChartEmptyPlaceholder(canvas3, "No statement contribution data available yet.");
      } else {
        const sc = chartsData.source_contribution || {};
        const ds = sc.datasets || {};
        _overviewChartInstances.sourceContribution = new Chart(canvas3.getContext("2d"), {
          type: "bar",
          data: {
            labels: sc.labels || ["No Sources"],
            datasets: [
              { label: "SETTLED", data: ds.SETTLED || [0], backgroundColor: "#10b981" },
              { label: "MATCHED", data: ds.MATCHED || [0], backgroundColor: "#3b82f6" },
              { label: "SIMILAR", data: ds.SIMILAR || [0], backgroundColor: "#f59e0b" },
              { label: "UNMATCHED", data: ds.UNMATCHED || [0], backgroundColor: "#ef4444" }
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: "bottom", labels: { color: textColor } } },
            scales: {
              x: { stacked: true, grid: { display: false }, ticks: { color: textColor } },
              y: { stacked: true, grid: { color: gridColor }, ticks: { color: textColor } }
            }
          }
        });
      }
    }

    // Chart 4: Confidence Score Distribution Histogram
    const canvas4 = document.getElementById("chartConfidenceDist");
    if (canvas4) {
      if (!hasData) {
        _showChartEmptyPlaceholder(canvas4, "No confidence scoring distribution data available yet.");
      } else {
        const cd = chartsData.confidence_distribution || {};
        _overviewChartInstances.confidenceDist = new Chart(canvas4.getContext("2d"), {
          type: "bar",
          data: {
            labels: cd.labels || ["0.0 - 0.5", "0.5 - 0.7", "0.7 - 0.8", "0.8 - 0.9", "0.9 - 1.0"],
            datasets: [{
              label: "Transaction Count",
              data: cd.counts || [0, 0, 0, 0, 0],
              backgroundColor: "#8b5cf6",
              borderRadius: 6
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { grid: { display: false }, ticks: { color: textColor } },
              y: { grid: { color: gridColor }, ticks: { color: textColor } }
            }
          }
        });
      }
    }

    // Chart 5: Exception Aging Chart
    const canvas5 = document.getElementById("chartExceptionAging");
    if (canvas5) {
      const ea = chartsData.exception_aging || {};
      const totalExceptions = (ea.counts || []).reduce((a, b) => a + b, 0);
      if (!hasData || totalExceptions === 0) {
        _showChartEmptyPlaceholder(canvas5, "No open exception items to age.");
      } else {
        _overviewChartInstances.exceptionAging = new Chart(canvas5.getContext("2d"), {
          type: "bar",
          data: {
            labels: ea.labels || ["0-1 day", "1-3 days", "3-7 days", "7+ days"],
            datasets: [{
              label: "Open Exception Items",
              data: ea.counts || [0, 0, 0, 0],
              backgroundColor: ["#3b82f6", "#f59e0b", "#f97316", "#ef4444"],
              borderRadius: 6
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { grid: { display: false }, ticks: { color: textColor } },
              y: { grid: { color: gridColor }, ticks: { color: textColor } }
            }
          }
        });
      }
    }

    // Chart 6: Trend Line
    const canvas6 = document.getElementById("chartMatchTrend");
    if (canvas6) {
      if (!hasData) {
        _showChartEmptyPlaceholder(canvas6, "No match-rate historical trend available yet.");
      } else {
        const tl = chartsData.trend_line || {};
        _overviewChartInstances.matchTrend = new Chart(canvas6.getContext("2d"), {
          type: "line",
          data: {
            labels: tl.labels || ["Current Run"],
            datasets: [{
              label: "Match Rate (%)",
              data: tl.match_rates || [0],
              borderColor: "#10b981",
              backgroundColor: "rgba(16, 185, 129, 0.12)",
              fill: true,
              tension: 0.35,
              pointRadius: 4,
              pointHoverRadius: 6
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { grid: { display: false }, ticks: { color: textColor } },
              y: { min: 0, max: 100, grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + "%" } }
            }
          }
        });
      }
    }
  }

  function _showChartEmptyPlaceholder(canvas, message) {
    const parent = canvas.parentElement;
    if (!parent) return;
    canvas.style.display = "none";
    let placeholder = parent.querySelector(".chart-empty-placeholder");
    if (!placeholder) {
      placeholder = document.createElement("div");
      placeholder.className = "chart-empty-placeholder";
      placeholder.style.cssText = "display:flex;align-items:center;justify-content:center;height:100%;min-height:180px;color:var(--text-muted);font-size:0.82rem;text-align:center;padding:20px;background:var(--bg-elevated);border-radius:8px;border:1px dashed var(--border);";
      parent.appendChild(placeholder);
    }
    placeholder.textContent = message;
  }


  function initSubTabs() {
    document.querySelectorAll(".sub-tab[data-sub]").forEach((el) => {
      el.addEventListener("click", () => activateSub(el.dataset.sub));
    });

    const goToReconcile = document.getElementById("goToReconcileBtn");
    if (goToReconcile) {
      goToReconcile.addEventListener("click", () => activateSub("sub-reconcile"));
    }

    const navCurrent = document.getElementById("navCurrentPeriod");
    if (navCurrent) navCurrent.addEventListener("click", () => activateSub("sub-upload-bank"));

    document.querySelectorAll("#btnNavImportStatement, #btnTopbarImportStatement, #btnTopbarImportFromSourcesMenu").forEach((btn) => {
      btn.addEventListener("click", () => activateSub("sub-upload-bank"));
    });

    const navReconciliation = document.getElementById("navReconciliation");
    if (navReconciliation) navReconciliation.addEventListener("click", () => activateSub("sub-reconcile"));

    const navManualReview = document.getElementById("navManualReview");
    if (navManualReview) navManualReview.addEventListener("click", () => activateSub("sub-manual-review"));

    // ── New SPA nav items ────────────────────────────────────────────────
    const navOverview = document.getElementById("navOverview");
    if (navOverview) navOverview.addEventListener("click", (e) => { e.preventDefault(); activateSub("sub-overview"); });

    const navTalkToLedger = document.getElementById("navTalkToLedger");
    if (navTalkToLedger) navTalkToLedger.addEventListener("click", (e) => { e.preventDefault(); activateSub("sub-talk-to-ledger"); });

    const navReports = document.getElementById("navReports");
    if (navReports) navReports.addEventListener("click", (e) => { e.preventDefault(); activateSub("sub-reports"); });

    const navConfig = document.getElementById("navConfig");
    if (navConfig) navConfig.addEventListener("click", (e) => { e.preventDefault(); activateSub("sub-config"); });

    // ── Group Accordion Toggles ──────────────────────────────────────────
    ["groupSources", "groupReconciliation", "groupExports"].forEach((groupId) => {
      const groupEl = document.getElementById(groupId);
      if (!groupEl) return;
      const headerEl = groupEl.querySelector(".sidebar-group-header");
      if (headerEl) {
        headerEl.addEventListener("click", (e) => {
          // Don't toggle if clicking (+) button inside header
          if (e.target.closest(".sidebar-add-btn")) return;
          groupEl.classList.toggle("open");
        });
      }
    });

    // Expose activateSub globally for inline onclick= attributes
    window.activateSub = activateSub;

    const btnNavRunAutoMatch = document.getElementById("btnNavRunAutoMatch");
    if (btnNavRunAutoMatch) {
      btnNavRunAutoMatch.addEventListener("click", () => {
        const mainRunBtn = document.getElementById("runReconcileBtn");
        if (mainRunBtn) mainRunBtn.click();
      });
    }

    const btnHdrRunAutoMatch = document.getElementById("btnHeaderRunAutoMatch");
    if (btnHdrRunAutoMatch) {
      btnHdrRunAutoMatch.addEventListener("click", () => {
        const mainRunBtn = document.getElementById("runReconcileBtn");
        if (mainRunBtn) mainRunBtn.click();
      });
    }

    const cpRunAutoMatchBtn = document.getElementById("cpRunAutoMatchBtn");
    if (cpRunAutoMatchBtn) {
      cpRunAutoMatchBtn.addEventListener("click", () => {
        const mainRunBtn = document.getElementById("runReconcileBtn");
        if (mainRunBtn) mainRunBtn.click();
      });
    }

    const cpClosePeriodBtn = document.getElementById("cpClosePeriodBtn");
    if (cpClosePeriodBtn) {
      cpClosePeriodBtn.addEventListener("click", () => {
        const closeBtn = document.getElementById("closePeriodBtn");
        if (closeBtn) closeBtn.click();
      });
    }

    const cpBtnViewUnmatched = document.getElementById("cpBtnViewUnmatched");
    if (cpBtnViewUnmatched) {
      cpBtnViewUnmatched.addEventListener("click", () => {
        activateSub("sub-reconcile");
        const filterEl = document.getElementById("txStatusFilter");
        if (filterEl) {
          filterEl.value = "unreconciled";
          filterEl.dispatchEvent(new Event("change"));
        }
      });
    }

    const cpBtnReviewAmbiguous = document.getElementById("cpBtnReviewAmbiguous");
    if (cpBtnReviewAmbiguous) {
      cpBtnReviewAmbiguous.addEventListener("click", () => activateSub("sub-manual-review"));
    }

    const cpBtnInvestigateDiscrepancy = document.getElementById("cpBtnInvestigateDiscrepancy");
    if (cpBtnInvestigateDiscrepancy) {
      cpBtnInvestigateDiscrepancy.addEventListener("click", () => activateSub("sub-reconcile"));
    }

    const navManual = document.getElementById("navManualReview");
    if (navManual) navManual.addEventListener("click", () => activateSub("sub-manual-review"));

    const btnHdrManual = document.getElementById("btnHeaderManualReview");
    if (btnHdrManual) btnHdrManual.addEventListener("click", () => activateSub("sub-manual-review"));

    const navClose = document.getElementById("navClosePeriod");
    if (navClose) navClose.addEventListener("click", () => activateSub("sub-close"));

    const addBtn = document.getElementById("addSourceBtn");
    if (addBtn) {
      addBtn.addEventListener("click", () => activateSub("sub-upload-bank"));
    }

    const closeStmtViewBtn = document.getElementById("closeStmtViewBtn");
    if (closeStmtViewBtn) {
      closeStmtViewBtn.addEventListener("click", () => activateSub("sub-upload-bank"));
    }

    document.querySelectorAll("#btnClearAllData, #btnClearAllDataSidebar, .btn-dustbin-expand").forEach((clearBtn) => {
      if (clearBtn.dataset.hasClearListener) return;
      clearBtn.dataset.hasClearListener = "true";

      clearBtn.addEventListener("click", async () => {
        const confirmed = confirm(
          "Are you sure you want to clear ALL imported statement data and reconciliation results?\n\nThis action cannot be undone."
        );
        if (!confirmed) return;

        clearBtn.disabled = true;
        const originalHtml = clearBtn.innerHTML;
        clearBtn.innerHTML = '<span class="spinner" style="width:13px;height:13px;border-width:2px;"></span> <span class="dustbin-text">Clearing...</span>';

        try {
          const res = await fetch("/api/clear_all_data", { method: "POST" });
          const data = await res.json();
          if (data.success || data.ok) {
            window.location.href = "/?tab=sub-upload-bank";
            window.location.reload();
          } else {
            alert(data.message || data.error || "Failed to clear data.");
          }
        } catch (err) {
          alert("Error clearing data: " + err.message);
        } finally {
          clearBtn.disabled = false;
          clearBtn.innerHTML = originalHtml;
        }
      });
    });
  }

  // ------------------------------------------------------------------
  // Resizable & Collapsible Sidebar
  // ------------------------------------------------------------------

  function initSidebarResizer() {
    const resizer = document.getElementById("sidebarResizer");
    const sidebar = document.getElementById("sidebar");
    const appBody = document.getElementById("appBody");
    if (!resizer || !sidebar || !appBody) return;

    let isResizing = false;

    // Restore saved width if available
    const savedWidth = localStorage.getItem("ledger_sidebar_width");
    if (savedWidth && !sidebar.classList.contains("collapsed")) {
      appBody.style.setProperty("--sidebar-width", `${savedWidth}px`);
    }

    resizer.addEventListener("mousedown", (e) => {
      e.preventDefault();
      if (sidebar.classList.contains("collapsed")) return;
      isResizing = true;
      resizer.classList.add("is-dragging");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    });

    document.addEventListener("mousemove", (e) => {
      if (!isResizing) return;
      const appBodyRect = appBody.getBoundingClientRect();
      let newWidth = e.clientX - appBodyRect.left;
      if (newWidth < 180) newWidth = 180;
      if (newWidth > 420) newWidth = 420;

      appBody.style.setProperty("--sidebar-width", `${newWidth}px`);
      localStorage.setItem("ledger_sidebar_width", newWidth);
    });

    document.addEventListener("mouseup", () => {
      if (isResizing) {
        isResizing = false;
        resizer.classList.remove("is-dragging");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    });
  }

  function initSidebarToggle() {
    const sidebar = document.getElementById("sidebar");
    const appBody = document.getElementById("appBody");
    const toggleBtn = document.getElementById("sidebarToggle");

    if (toggleBtn && sidebar && appBody) {
      toggleBtn.addEventListener("click", () => {
        const isCollapsed = sidebar.classList.toggle("collapsed");
        appBody.classList.toggle("sidebar-collapsed", isCollapsed);

        if (!isCollapsed) {
          const savedWidth = localStorage.getItem("ledger_sidebar_width") || 232;
          appBody.style.setProperty("--sidebar-width", `${savedWidth}px`);
        }
      });
    }
  }

  // ------------------------------------------------------------------
  // Statement Color Palette & Dot Utility (10-Color System)
  // ------------------------------------------------------------------
  const SOURCE_COLOR_PALETTE = [
    "#3b82f6", // Vibrant Blue
    "#10b981", // Emerald Green
    "#8b5cf6", // Purple Accent
    "#f59e0b", // Amber Gold
    "#ec4899", // Bright Pink
    "#06b6d4", // Cyan / Teal
    "#f97316", // Warm Orange
    "#6366f1", // Indigo
    "#14b8a6", // Mint / Jade
    "#e11d48"  // Rose Red
  ];

  function getStatementColor(stmt, idx) {
    if (stmt && stmt.color && !["#4C8DFF", "#6f89ff", "#3b82f6"].includes(stmt.color)) {
      return stmt.color;
    }
    const index = idx !== undefined ? idx : 0;
    return SOURCE_COLOR_PALETTE[index % SOURCE_COLOR_PALETTE.length];
  }

  // ------------------------------------------------------------------
  // Sidebar Sources List & 3-Dots Action Menu
  // ------------------------------------------------------------------

  function renderTopbarSources(statements) {
    const topbarSourcesEl = document.getElementById("topbarSourcesDynamic");
    if (!topbarSourcesEl) return;

    topbarSourcesEl.innerHTML = "";
    if (!statements || statements.length === 0) {
      topbarSourcesEl.innerHTML = '<span class="topbar-dropdown-empty">No statement sources loaded</span>';
      return;
    }

    statements.forEach((stmt, idx) => {
      const dotColor = getStatementColor(stmt, idx);
      const item = document.createElement("a");
      item.className = "topbar-dropdown-item";
      item.href = "javascript:void(0)";
      item.onclick = (e) => {
        e.preventDefault();
        if (typeof openStatementView === "function") openStatementView(stmt.id);
      };
      item.innerHTML = `
        <span class="source-dot" style="background-color: ${dotColor}; width:8px; height:8px; border-radius:50%; display:inline-block; flex-shrink:0;"></span>
        <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:500;">${escapeHtml(stmt.name)}</span>
        <span style="font-size:0.7rem; color:var(--text-muted); font-family:var(--font-mono);">${stmt.row_count || 0} rows</span>
      `;
      topbarSourcesEl.appendChild(item);
    });
  }

  async function loadSidebarSources() {
    const listEl = document.getElementById("sourceList");

    try {
      const res = await window.LedgerApi.getStatements();
      const statements = res.statements || [];

      if (listEl) {
        listEl.innerHTML = "";
        if (statements.length === 0) {
          listEl.appendChild(el('<li class="sidebar-empty">No statements imported yet</li>'));
        } else {
          statements.forEach((stmt, idx) => renderSourceListItem(stmt, listEl, idx));
        }
      }

      renderExecutiveSources(statements);
      renderTopbarSources(statements);
    } catch (_) {
      // Ignore error
    }
  }

  function renderExecutiveSources(statements) {
    const cpListEl = document.getElementById("cpSourcesList");
    const cpFooterEl = document.getElementById("cpSourcesFooter");
    if (!cpListEl) return;

    cpListEl.innerHTML = "";
    if (!statements || statements.length === 0) {
      cpListEl.innerHTML = `<div class="term-dim" style="font-size:0.88rem; padding:6px 0;">No statement sources imported yet.</div>`;
      if (cpFooterEl) cpFooterEl.textContent = "0 sources • 0 transactions";
      return;
    }

    let totalRows = 0;
    statements.forEach((stmt, idx) => {
      const dotColor = getStatementColor(stmt, idx);
      const rows = stmt.row_count || 0;
      totalRows += rows;
      const isPrimary = Boolean(stmt.is_primary);

      const item = el(`
        <div class="cp-source-item">
          <span class="cp-dot" style="background-color: ${dotColor};"></span>
          <span class="cp-source-name">${escapeHtml(stmt.name)} ${isPrimary ? '<span style="color:#eab308; font-size:0.75rem; border:1px solid #eab308; padding:1px 4px; border-radius:3px; margin-left:4px;">PRIMARY</span>' : ''}</span>
          <span class="font-mono" style="margin-left:auto; font-size:0.8rem; color:#94a3b8;">${rows} rows</span>
        </div>
      `);
      cpListEl.appendChild(item);
    });

    if (cpFooterEl) {
      cpFooterEl.textContent = `${statements.length} sources • ${totalRows.toLocaleString()} transactions`;
    }
  }

  async function loadRecentRuns() {
    const listEl = document.getElementById("cpRunsList");
    if (!listEl) return;
    try {
      const res = await window.LedgerApi.getReconciliationRuns();
      const runs = res.runs || [];
      listEl.innerHTML = "";
      if (runs.length === 0) {
        listEl.innerHTML = `<div class="term-dim" style="font-size:0.88rem; padding:8px 0;">No auto-match runs recorded yet.</div>`;
        return;
      }
      runs.forEach((r) => {
        const item = el(`
          <div class="cp-run-item">
            <span class="run-time font-mono">${r.timestamp || "Today"}</span>
            <span class="run-tx font-mono">${(r.total_transactions || 0).toLocaleString()} transactions</span>
            <span class="run-matched font-mono green">${(r.matched_count || 0).toLocaleString()} matched</span>
            <span class="run-status-badge badge-success">&check; ${r.status || "Complete"}</span>
          </div>
        `);
        listEl.appendChild(item);
      });
    } catch (_) { }
  }

  function formatSourceTitle(name) {
    if (!name) return "";
    if (name === name.toUpperCase()) {
      return name
        .toLowerCase()
        .split(" ")
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
    }
    return name;
  }

  function renderSourceListItem(stmt, listEl) {
    const dotColor = stmt.color || "#6f89ff";
    const displayName = formatSourceTitle(stmt.name);
    const isPrimary = Boolean(stmt.is_primary);

    const itemNode = el(`
      <li class="source-item ${stmt.id === activeStatementId ? "active" : ""}" data-id="${stmt.id}">
        <span class="source-dot" style="background-color: ${dotColor};"></span>
        <span class="label-text" title="${escapeHtml(stmt.name)}">${escapeHtml(displayName)} ${isPrimary ? '<span style="color:#eab308; font-size:0.7rem; font-weight:700; margin-left:4px;">PRIMARY</span>' : ''}</span>
        <div class="stmt-menu-wrapper">
          <button type="button" class="stmt-dots-btn" aria-label="Options" title="Options">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/><circle cx="5" cy="12" r="1.5"/></svg>
          </button>
          <div class="stmt-dropdown">
            <button type="button" class="dropdown-opt opt-set-primary">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
              ${isPrimary ? 'Primary Source' : 'Set as Primary'}
            </button>
            <button type="button" class="dropdown-opt opt-view">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
              View Entries
            </button>
            <button type="button" class="dropdown-opt opt-append">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6"/><path d="M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
              Update
            </button>
            <button type="button" class="dropdown-opt opt-rename">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              Rename
            </button>
            <button type="button" class="dropdown-opt opt-delete danger">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              Delete
            </button>
          </div>
        </div>
      </li>
    `);

    itemNode.addEventListener("click", (e) => {
      if (e.target.closest(".stmt-menu-wrapper")) return;
      openStatementView(stmt.id);
    });

    const dotsBtn = itemNode.querySelector(".stmt-dots-btn");
    const dropdown = itemNode.querySelector(".stmt-dropdown");

    dotsBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      document.querySelectorAll(".stmt-dropdown.show").forEach((d) => {
        if (d !== dropdown) d.classList.remove("show");
      });
      dropdown.classList.toggle("show");
    });

    itemNode.querySelector(".opt-set-primary")?.addEventListener("click", async (e) => {
      e.stopPropagation();
      dropdown.classList.remove("show");
      await handleSetPrimaryStatement(stmt.id);
    });

    itemNode.querySelector(".opt-view").addEventListener("click", (e) => {
      e.stopPropagation();
      dropdown.classList.remove("show");
      openStatementView(stmt.id);
    });

    itemNode.querySelector(".opt-append").addEventListener("click", (e) => {
      e.stopPropagation();
      dropdown.classList.remove("show");
      triggerAppendData(stmt.id);
    });

    itemNode.querySelector(".opt-rename").addEventListener("click", async (e) => {
      e.stopPropagation();
      dropdown.classList.remove("show");
      const newName = prompt("Enter new statement name:", stmt.name);
      if (newName && newName.trim()) {
        await window.LedgerApi.renameStatement(stmt.id, newName.trim());
        await loadSidebarSources();
        await loadStatementsTable();
        if (activeStatementId === stmt.id) {
          document.getElementById("stmtViewTitle").textContent = newName.trim();
        }
      }
    });

    itemNode.querySelector(".opt-delete").addEventListener("click", async (e) => {
      e.stopPropagation();
      dropdown.classList.remove("show");
      if (confirm(`Are you sure you want to delete "${stmt.name}"?`)) {
        await window.LedgerApi.deleteStatement(stmt.id);
        stateManager.invalidate();
        if (activeStatementId === stmt.id) {
          activateSub("sub-upload-bank");
          document.getElementById("subTabStatementView").style.display = "none";
          activeStatementId = null;
        }
        await stateManager.syncAll(true);
      }
    });

    listEl.appendChild(itemNode);
  }


  // Close dropdowns on document click
  document.addEventListener("click", () => {
    document.querySelectorAll(".stmt-dropdown.show").forEach((d) => d.classList.remove("show"));
  });

  // ------------------------------------------------------------------
  // Upload Dropzones with Statement Name Option
  // ------------------------------------------------------------------

  const TYPE_COLOR_MAP = {
    "bank": "#6f89ff",
    "order_book": "#e0b054",
    "orders": "#e0b054",
    "razorpay": "#f04f4f",
    "gateway": "#f04f4f",
    "upi": "#a855f7",
    "card": "#ec4899",
    "cash_book": "#6fe0a1",
    "cash": "#6fe0a1",
    "others": "#06b6d4",
  };

  function selectColorForType(typeVal) {
    const color = TYPE_COLOR_MAP[typeVal] || "#6f89ff";
    const row = document.getElementById("colorPickerRow");
    if (!row) return;

    let matchedSwatch = null;
    row.querySelectorAll(".color-swatch").forEach((swatch) => {
      if (swatch.dataset.color && swatch.dataset.color.toLowerCase() === color.toLowerCase()) {
        matchedSwatch = swatch;
      }
    });

    if (matchedSwatch) {
      row.querySelectorAll(".color-swatch").forEach((s) => s.classList.remove("active"));
      matchedSwatch.classList.add("active");
    }
  }

  function initTypeSelector() {
    const buttonsContainer = document.getElementById("typeSelectorButtons");
    const customWrapper = document.getElementById("customTypeWrapper");
    if (!buttonsContainer) return;

    buttonsContainer.querySelectorAll(".type-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        buttonsContainer.querySelectorAll(".type-chip").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");

        const typeVal = btn.dataset.type;
        if (typeVal === "others") {
          if (customWrapper) customWrapper.style.display = "block";
        } else {
          if (customWrapper) customWrapper.style.display = "none";
        }
        selectColorForType(typeVal);
      });
    });
  }

  function initColorPicker() {
    const row = document.getElementById("colorPickerRow");
    const customColorInput = document.getElementById("customColorInput");
    if (!row) return;

    row.querySelectorAll(".color-swatch").forEach((swatch) => {
      swatch.addEventListener("click", () => {
        row.querySelectorAll(".color-swatch").forEach((s) => s.classList.remove("active"));
        swatch.classList.add("active");
      });
    });

    if (customColorInput) {
      customColorInput.addEventListener("input", () => {
        row.querySelectorAll(".color-swatch").forEach((s) => s.classList.remove("active"));
      });
    }
  }


  function getSelectedTypeInfo() {
    const activeChip = document.querySelector("#typeSelectorButtons .type-chip.active");
    const chipType = activeChip ? activeChip.dataset.type : "bank";

    let label = "Bank";
    let sourceType = "bank";

    if (chipType === "bank") {
      sourceType = "bank";
      label = "Bank";
    } else if (chipType === "order_book" || chipType === "orders") {
      sourceType = "order_book";
      label = "Order Book";
    } else if (chipType === "razorpay" || chipType === "gateway") {
      sourceType = "razorpay";
      label = "Razorpay";
    } else if (chipType === "upi") {
      sourceType = "upi";
      label = "UPI";
    } else if (chipType === "card") {
      sourceType = "card";
      label = "Card";
    } else if (chipType === "cash_book" || chipType === "cash") {
      sourceType = "cash_book";
      label = "Cash Book";
    } else if (chipType === "others") {
      const customInput = document.getElementById("custom-type-input");
      const val = customInput ? customInput.value.trim() : "";
      label = val || "Others";
      sourceType = val ? val.toLowerCase().replace(/\s+/g, "_") : "subledger";
    }
    return { sourceType, label };
  }

  function getSelectedColor() {
    const activeSwatch = document.querySelector("#colorPickerRow .color-swatch.active");
    if (activeSwatch) {
      return activeSwatch.dataset.color;
    }
    const customInput = document.getElementById("customColorInput");
    if (customInput && customInput.value) {
      return customInput.value;
    }
    return "#6f89ff";
  }

  function setStatus(source, message, kind) {
    const el = document.querySelector(`[data-status="${source}"]`);
    if (!el) return;
    el.textContent = message;
    el.className = "upload-status show" + (kind ? ` status-${kind}` : "");
  }

  function renderImportResultsContainer(dropzoneEl, results) {
    let container = dropzoneEl.parentNode.querySelector(".import-results-list");
    if (!container) {
      container = document.createElement("div");
      container.className = "import-results-list";
      container.style.cssText = "margin-top: 15px; display: flex; flex-direction: column; gap: 8px;";
      dropzoneEl.parentNode.insertBefore(container, dropzoneEl.nextSibling);
    }
    container.innerHTML = "";

    results.forEach((res) => {
      const row = document.createElement("div");
      const isSuccess = res.status === "success";
      row.style.cssText = `display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-radius: 8px; font-size: 13px; background: ${isSuccess ? "rgba(34, 197, 94, 0.1)" : "rgba(239, 68, 68, 0.1)"}; border: 1px solid ${isSuccess ? "rgba(34, 197, 94, 0.3)" : "rgba(239, 68, 68, 0.3)"}; color: #e2e8f0;`;

      row.innerHTML = `
        <div style="display: flex; align-items: center; gap: 10px;">
          <span style="font-weight: 600; color: ${isSuccess ? "#4ade80" : "#f87171"};">${isSuccess ? "Success" : "Failed"}</span>
          <span style="font-family: monospace;">${escapeHtml(res.filename)}</span>
        </div>
        <div style="display: flex; align-items: center; gap: 12px;">
          ${isSuccess ? `<span style="opacity: 0.8;">${res.row_count} rows detected</span>` : `<span style="color: #f87171;">${escapeHtml(res.error_message || "Parse failed")}</span>`}
          ${isSuccess && res.statement_id ? `<button type="button" class="btn btn-sm btn-outline-secondary" onclick="openStatementView('${res.statement_id}')">View</button>` : ""}
        </div>
      `;
      container.appendChild(row);
    });
  }

  function initDropzone(dropzoneEl) {
    const source = dropzoneEl.dataset.source;
    const input = document.getElementById(dropzoneEl.dataset.input);
    const importBtn = document.querySelector(`[data-import="${source}"]`);
    const btnImportAI = document.getElementById("btnImportAI");
    const nameInput = document.getElementById(`name-${source}`);
    let pendingFiles = [];

    if (input) {
      input.setAttribute("multiple", "multiple");
    }

    const handleFiles = (files) => {
      const validFiles = Array.from(files || []).filter(f => f && f.name);
      if (validFiles.length === 0) return;

      pendingFiles = validFiles;
      if (importBtn) importBtn.disabled = false;
      if (btnImportAI) btnImportAI.disabled = false;

      if (nameInput && validFiles.length === 1 && !nameInput.value.trim()) {
        nameInput.value = validFiles[0].name.replace(/\.[^/.]+$/, "").replace(/_/g, " ").toUpperCase();
      }

      const namesStr = validFiles.map(f => f.name).join(", ");
      setStatus(source, `Ready to import ${validFiles.length} file(s): ${namesStr}`, null);
    };

    dropzoneEl.addEventListener("click", () => input.click());
    input.addEventListener("change", (e) => handleFiles(e.target.files));

    ["dragenter", "dragover"].forEach((evt) =>
      dropzoneEl.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzoneEl.classList.add("drag-over");
      })
    );
    ["dragleave", "drop"].forEach((evt) =>
      dropzoneEl.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzoneEl.classList.remove("drag-over");
      })
    );
    dropzoneEl.addEventListener("drop", (e) => {
      handleFiles(e.dataTransfer.files);
    });

    const runImport = async (forceLlm = false) => {
      if (pendingFiles.length === 0) return;

      const useLlm = Boolean(forceLlm);

      if (importBtn) importBtn.disabled = true;
      if (btnImportAI) btnImportAI.disabled = true;

      const statusMsg = useLlm
        ? `Importing & Auto-Organizing ${pendingFiles.length} file(s) with LLM Semantic Engine…`
        : `Importing ${pendingFiles.length} file(s) into database…`;

      setStatus(source, statusMsg, "loading");
      startPipelineMonitoring();

      const name = nameInput ? nameInput.value.trim() : "";
      const isPrimaryEl = document.getElementById("isPrimaryToggle");
      const isPrimary = isPrimaryEl ? isPrimaryEl.checked : false;
      const color = getSelectedColor();
      const rulesEl = document.getElementById("rules-input");
      const rules = rulesEl ? rulesEl.value.trim() : "";

      try {
        const result = await window.LedgerApi.importStatement(pendingFiles, name, isPrimary, color, rules, useLlm);
        const results = result.results || [];
        const successCount = results.filter(r => r.status === "success").length;
        const errCount = results.length - successCount;

        const summaryMsg = useLlm
          ? `AI Import Complete! Mapped ${successCount}/${results.length} file(s) using Groq.${errCount > 0 ? ` (${errCount} failed)` : ""}`
          : `Imported ${successCount}/${results.length} file(s) successfully.${errCount > 0 ? ` (${errCount} failed)` : ""}`;

        setStatus(source, summaryMsg, successCount > 0 ? "success" : "error");

        if (useLlm && successCount > 0) {
          showNotificationToast("Smart AI Import complete! Columns aligned & new aliases saved to registry.", "success");
        }

        renderImportResultsContainer(dropzoneEl, results);

        pendingFiles = [];
        input.value = "";
        if (nameInput) nameInput.value = "";
        if (rulesEl) rulesEl.value = "";

        await pollPipelineStatus();
        stopPipelineMonitoring();

        stateManager.invalidate();
        await loadSidebarSources();
        await loadStatementsTable();

      } catch (err) {
        stopPipelineMonitoring();
        const message = err instanceof window.ApiError ? err.message : "Upload failed. Please try again.";
        setStatus(source, message, "error");
        if (importBtn) importBtn.disabled = false;
        if (btnImportAI) btnImportAI.disabled = false;
      }
    };

    if (importBtn) {
      importBtn.addEventListener("click", () => runImport(false));
    }
    if (btnImportAI) {
      btnImportAI.addEventListener("click", () => runImport(true));
    }
  }


  // ------------------------------------------------------------------
  // Live Pipeline Progress Bar & Terminal Log Polling Engine
  // ------------------------------------------------------------------

  let pipelinePollInterval = null;
  let seenLogsCount = 0;

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  async function pollPipelineStatus() {
    const stageEl = document.getElementById("importStageText");
    const percentEl = document.getElementById("importProgressPercent");
    const fillEl = document.getElementById("importProgressFill");
    const terminalBody = document.getElementById("importTerminalBody");

    try {
      const res = await window.LedgerApi.getPipelineStatus();
      if (!res || !res.ok) return;

      if (stageEl && res.stage) {
        let displayStage = res.stage;
        if (displayStage && displayStage !== "Idle" && !displayStage.endsWith("...") && !displayStage.startsWith("Pipeline ")) {
          displayStage += "...";
        }
        stageEl.textContent = displayStage;
      }
      if (percentEl && res.progress !== undefined) percentEl.textContent = `${res.progress}%`;
      if (fillEl && res.progress !== undefined) fillEl.style.width = `${res.progress}%`;

      if (terminalBody && res.logs && res.logs.length > seenLogsCount) {
        const newLogs = res.logs.slice(seenLogsCount);
        seenLogsCount = res.logs.length;

        newLogs.forEach((log) => {
          const line = document.createElement("div");
          line.className = `term-line lvl-${log.level || "INFO"}`;
          line.innerHTML = `<span class="time">[${log.timestamp || ""}]</span> <span class="tag">[${log.level || "INFO"}]</span> ${escapeHtml(log.message || "")}`;
          terminalBody.appendChild(line);
        });
        terminalBody.scrollTop = terminalBody.scrollHeight;
      }

      if (!res.is_running && res.progress >= 100) {
        stopPipelineMonitoring();
      }
    } catch (err) {
      console.warn("Pipeline status poll warning:", err);
    }
  }

  function startPipelineMonitoring() {
    const container = document.getElementById("importProgressContainer");
    const stageEl = document.getElementById("importStageText");
    const percentEl = document.getElementById("importProgressPercent");
    const fillEl = document.getElementById("importProgressFill");
    const terminalBody = document.getElementById("importTerminalBody");

    if (container) container.style.display = "block";
    if (stageEl) stageEl.textContent = "Reading & Ingesting Uploaded File...";
    if (percentEl) percentEl.textContent = "5%";
    if (fillEl) fillEl.style.width = "5%";

    seenLogsCount = 0;
    if (terminalBody) {
      terminalBody.innerHTML = `<div class="term-line term-dim">[SYSTEM] Pipeline tracker activated. Starting live output...</div>`;
    }

    stopPipelineMonitoring();
    pollPipelineStatus();
    pipelinePollInterval = setInterval(pollPipelineStatus, 300);
  }

  function stopPipelineMonitoring() {
    if (pipelinePollInterval) {
      clearInterval(pipelinePollInterval);
      pipelinePollInterval = null;
    }
  }

  function initUploads() {
    initTypeSelector();
    initColorPicker();
    document.querySelectorAll(".dropzone").forEach(initDropzone);

    const btnClearTerm = document.getElementById("btnClearTerminal");
    if (btnClearTerm) {
      btnClearTerm.addEventListener("click", () => {
        const body = document.getElementById("importTerminalBody");
        if (body) body.innerHTML = `<div class="term-line term-dim">[SYSTEM] Console logs cleared.</div>`;
        seenLogsCount = 0;
      });
    }
  }

  // ------------------------------------------------------------------
  // Statement Detail Table View & Append Data
  // ------------------------------------------------------------------

  async function findAndOpenStatementForSource(sourceType, searchId, sourceName, statementId) {
    const modalBackdrop = document.getElementById("compareModalBackdrop");
    if (modalBackdrop) modalBackdrop.style.display = "none";

    try {
      const res = await window.LedgerApi.getStatements();
      const statements = res.statements || [];
      const cleanSearchId = searchId ? String(searchId).replace(/\.0$/, "").trim() : "";

      let targetStmt = null;

      // 1. Match by statementId
      if (statementId) {
        targetStmt = statements.find(s => String(s.id).trim() === String(statementId).trim());
      }

      // 2. Match by sourceName / statement name
      if (!targetStmt && sourceName) {
        const cleanName = String(sourceName).toLowerCase().trim();
        targetStmt = statements.find(s => {
          const sName = String(s.name || s.statement_type_label || "").toLowerCase().trim();
          return sName === cleanName || sName.includes(cleanName) || cleanName.includes(sName);
        });
      }

      // 3. Search DB for statement containing searchId in rows
      if (!targetStmt && cleanSearchId) {
        for (const s of statements) {
          const detail = await window.LedgerApi.getStatement(s.id);
          if (detail && detail.statement && detail.statement.rows) {
            const foundRow = detail.statement.rows.find(r => {
              return Object.values(r).some(v => v != null && String(v).replace(/\.0$/, "").trim() === cleanSearchId);
            });
            if (foundRow) {
              targetStmt = s;
              break;
            }
          }
        }
      }

      // 4. Fallback: Match by sourceType
      if (!targetStmt && sourceType) {
        const cleanStype = String(sourceType).toLowerCase().trim();
        targetStmt = statements.find(s => {
          const st = String(s.source_type || "").toLowerCase();
          return st === cleanStype || cleanStype.includes(st) || st.includes(cleanStype);
        });
      }

      if (!targetStmt && statements.length > 0) {
        targetStmt = statements[0];
      }

      if (targetStmt) {
        await openStatementView(targetStmt.id, cleanSearchId);
      } else {
        alert(`No statement source found matching "${cleanSearchId || sourceType || 'Record'}".`);
      }
    } catch (err) {
      console.error("Error opening statement source:", err);
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  async function loadStatementsTable() {
    const bodyEl = document.getElementById("statementsTableBody");
    const countEl = document.getElementById("statementsTableCount");
    if (!bodyEl) return;

    try {
      const res = await window.LedgerApi.getStatements();
      const statements = res.statements || [];
      window.statementColorMap = window.statementColorMap || {};
      statements.forEach(s => {
        if (s.name && s.color) window.statementColorMap[s.name] = s.color;
      });
      bodyEl.innerHTML = "";

      if (countEl) countEl.textContent = `${statements.length} statement${statements.length === 1 ? "" : "s"}`;

      if (statements.length === 0) {
        bodyEl.innerHTML = `<tr><td colspan="6" class="empty-state" style="text-align:center; padding:20px; color:var(--text-muted);">No statements imported yet</td></tr>`;
        return;
      }

      statements.forEach((stmt) => {
        const tr = document.createElement("tr");
        const color = stmt.color || "#6f89ff";
        const isPrimary = Boolean(stmt.is_primary);
        const rows = stmt.row_count || 0;
        const created = formatDateDDMMYYYY(stmt.created_at || "Today");

        const displayName = stmt.name || (stmt.filename ? stmt.filename.replace(/\.[^/.]+$/, "").replace(/_/g, " ").replace(/-/g, " ").toUpperCase() : "Statement");

        tr.innerHTML = `
          <td>
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="stmt-name-text" style="font-weight: 600; font-size: 0.88rem; color: var(--text-primary, #f8fafc); cursor: pointer;" title="Click to edit name">${escapeHtml(displayName)}</span>
              <input type="text" class="form-input stmt-name-input" value="${escapeHtml(displayName)}" style="display: none; background: var(--bg-surface, #12161f); border: 1px solid var(--border-color, #272f3e); color: var(--text-primary, #f8fafc); padding: 4px 8px; font-size: 0.85rem; font-weight: 600; border-radius: 6px; width: 100%; min-width: 140px;">
              ${isPrimary ? '<span style="color:#facc15; font-size:0.7rem; font-weight:700; border:1px solid #facc15; background:rgba(234,179,8,0.15); padding:2px 6px; border-radius:4px;" title="Primary Source">PRIMARY</span>' : ''}
            </div>
          </td>
          <td>
            <div style="display: inline-flex; align-items: center; gap: 8px;">
              <input type="color" class="stmt-color-picker" value="${color}" style="width: 28px; height: 28px; border: none; background: transparent; cursor: pointer; border-radius: 4px; padding: 0;">
              <span class="font-mono stmt-color-hex" style="font-size: 0.78rem; color: var(--text-muted, #94a3b8);">${color}</span>
            </div>
          </td>
          <td class="font-mono">${rows.toLocaleString()}</td>
          <td class="font-mono text-muted" style="font-size: 0.82rem;">${created}</td>
          <td>
            <button type="button" class="btn-primary-toggle ${isPrimary ? "is-primary" : ""}" data-id="${stmt.id}" style="display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: 8px; font-size: 0.8rem; font-weight: 700; background: ${isPrimary ? "rgba(234, 179, 8, 0.18)" : "rgba(255, 255, 255, 0.05)"}; color: ${isPrimary ? "#facc15" : "var(--text-secondary)"}; border: 1px solid ${isPrimary ? "rgba(234, 179, 8, 0.45)" : "rgba(255, 255, 255, 0.15)"}; cursor: pointer; transition: all 0.15s ease;">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="${isPrimary ? "#facc15" : "none"}" stroke="${isPrimary ? "#facc15" : "currentColor"}" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
              <span>${isPrimary ? "Primary Source" : "Set as Primary"}</span>
            </button>
          </td>
          <td class="text-right">
            <div style="display: flex; align-items: center; justify-content: flex-end; gap: 8px;">
              <button type="button" class="btn btn-sm btn-table-view" data-id="${stmt.id}" style="padding: 4px 12px; font-size: 0.78rem; font-weight: 600; color: #60a5fa; background: rgba(96, 165, 250, 0.12); border: 1px solid rgba(96, 165, 250, 0.35); border-radius: 6px; cursor: pointer;" title="View Entries">View</button>
              <button type="button" class="btn btn-sm btn-table-delete" data-id="${stmt.id}" data-name="${escapeHtml(displayName)}" style="padding: 4px 12px; font-size: 0.78rem; font-weight: 600; color: #f87171; background: rgba(248, 113, 113, 0.12); border: 1px solid rgba(248, 113, 113, 0.35); border-radius: 6px; cursor: pointer;" title="Delete">Delete</button>
            </div>
          </td>
        `;

        const nameText = tr.querySelector(".stmt-name-text");
        const nameInput = tr.querySelector(".stmt-name-input");

        if (nameText && nameInput) {
          nameText.addEventListener("click", () => {
            nameText.style.display = "none";
            nameInput.style.display = "inline-block";
            nameInput.focus();
            nameInput.select();
          });

          const saveName = async () => {
            const newName = nameInput.value.trim();
            nameInput.style.display = "none";
            nameText.style.display = "inline-block";
            if (newName && newName !== displayName) {
              nameText.textContent = newName;
              await window.LedgerApi.renameStatement(stmt.id, newName);
              await loadSidebarSources();
              if (activeStatementId === stmt.id) {
                const titleEl = document.getElementById("stmtViewTitle");
                if (titleEl) titleEl.textContent = newName;
              }
            } else {
              nameInput.value = displayName;
            }
          };

          nameInput.addEventListener("blur", saveName);
          nameInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              nameInput.blur();
            } else if (e.key === "Escape") {
              nameInput.value = displayName;
              nameInput.style.display = "none";
              nameText.style.display = "inline-block";
            }
          });
        }

        const colorPicker = tr.querySelector(".stmt-color-picker");
        const colorHex = tr.querySelector(".stmt-color-hex");
        if (colorPicker) {
          colorPicker.addEventListener("input", (e) => {
            if (colorHex) colorHex.textContent = e.target.value;
          });
          colorPicker.addEventListener("change", async (e) => {
            const newColor = e.target.value;
            await window.LedgerApi.updateStatementColor(stmt.id, newColor);
            await loadSidebarSources();
          });
        }

        const primaryBtn = tr.querySelector(".btn-primary-toggle");
        if (primaryBtn) {
          primaryBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            await handleSetPrimaryStatement(stmt.id, primaryBtn);
          });
        }

        tr.querySelector(".btn-table-view")?.addEventListener("click", () => openStatementView(stmt.id));

        tr.querySelector(".btn-table-delete")?.addEventListener("click", async () => {
          if (confirm(`Are you sure you want to delete "${stmt.name}"?`)) {
            await window.LedgerApi.deleteStatement(stmt.id);
            stateManager.invalidate();
            if (activeStatementId === stmt.id) {
              activateSub("sub-upload-bank");
              document.getElementById("subTabStatementView").style.display = "none";
              activeStatementId = null;
            }
            await stateManager.syncAll(true);
          }
        });

        bodyEl.appendChild(tr);
      });

    } catch (err) {
      console.warn("Error loading statements table:", err);
    }
  }

  let activeStatementLoadedRows = [];
  let isEditingStatementRows = false;

  async function openStatementView(statementId, searchQuery = "") {
    if (!statementId) return;
    activeStatementId = statementId;
    isEditingStatementRows = false;
    resetEditStatementButtonState();

    const subTabStatementView = document.getElementById("subTabStatementView");
    if (subTabStatementView) subTabStatementView.style.display = "inline-flex";

    activateSub("sub-statement-view");
    await loadSidebarSources();

    let attempts = 0;
    while (attempts < 3) {
      try {
        const res = await window.LedgerApi.getStatementDetail(statementId);
        if (res && res.statement) {
          const stmt = res.statement;
          activeStatementLoadedRows = stmt.rows || [];

          document.getElementById("stmtViewTitle").textContent = stmt.name;
          const typeBadge = document.getElementById("stmtViewTypeBadge");
          if (typeBadge) {
            const badgeLabel = getSourceTypeBadgeLabel(stmt);
            typeBadge.textContent = badgeLabel;
            if (badgeLabel.includes("RAZORPAY")) {
              typeBadge.style.background = "rgba(168, 85, 247, 0.18)";
              typeBadge.style.color = "#c084fc";
              typeBadge.style.border = "1px solid rgba(168, 85, 247, 0.4)";
            } else if (badgeLabel.includes("INTERNAL")) {
              typeBadge.style.background = "rgba(16, 185, 129, 0.18)";
              typeBadge.style.color = "#34d399";
              typeBadge.style.border = "1px solid rgba(16, 185, 129, 0.4)";
            } else if (badgeLabel.includes("CASH")) {
              typeBadge.style.background = "rgba(245, 158, 11, 0.18)";
              typeBadge.style.color = "#fbbf24";
              typeBadge.style.border = "1px solid rgba(245, 158, 11, 0.4)";
            } else {
              typeBadge.style.background = "rgba(59, 130, 246, 0.18)";
              typeBadge.style.color = "#60a5fa";
              typeBadge.style.border = "1px solid rgba(59, 130, 246, 0.4)";
            }
          }

          document.getElementById("stmtViewCountBadge").textContent = `${stmt.row_count} rows`;

          const btnSetPrimary = document.getElementById("btnStmtHeaderSetPrimary");
          const btnSetPrimaryText = document.getElementById("btnStmtHeaderSetPrimaryText");
          if (btnSetPrimary && btnSetPrimaryText) {
            const isPrimary = Boolean(stmt.is_primary);
            btnSetPrimaryText.textContent = isPrimary ? "Primary Source" : "Set as Primary";
            if (isPrimary) {
              btnSetPrimary.classList.add("is-primary");
            } else {
              btnSetPrimary.classList.remove("is-primary");
            }
            btnSetPrimary.onclick = async (e) => {
              e.stopPropagation();
              await handleSetPrimaryStatement(statementId, btnSetPrimary);
            };
          }

          const settledBadge = document.getElementById("stmtViewSettledBadge");
          if (settledBadge) {
            settledBadge.style.display = stmt.period_settled ? "inline-block" : "none";
          }

          renderStatementRows(activeStatementLoadedRows);

          if (searchQuery) {
            const searchInput = document.getElementById("stmtSearchInput");
            if (searchInput) {
              searchInput.value = searchQuery;
              searchInput.dispatchEvent(new Event("input"));
            }
          }
          return;
        }
      } catch (err) {
        console.warn(`Attempt ${attempts + 1} loading statement details failed:`, err);
      }
      attempts++;
      await new Promise(r => setTimeout(r, 200));
    }
  }


  function resetEditStatementButtonState() {
    const editBtn = document.getElementById("btnEditStmtEntries");
    const editBtnText = document.getElementById("btnEditStmtEntriesText");
    if (editBtn && editBtnText) {
      editBtnText.textContent = "Edit Entries";
      editBtn.classList.remove("is-editing");
      editBtn.removeAttribute("style");
    }
  }

  const IGNORED_SYSTEM_KEYS = new Set([
    "source_name", "source_row_number", "source_sheet", "is_primary",
    "serial_code", "serial_no", "source_color", "statement_id",
    "dropped_columns", "explanations", "source_file", "source_page",
    "content_hash"
  ]);

  function renderStatementRows(rows, editable = false) {
    const headEl = document.getElementById("stmtTableHead");
    const bodyEl = document.getElementById("stmtTableBody");
    headEl.innerHTML = "";
    bodyEl.innerHTML = "";

    if (!rows || rows.length === 0) {
      bodyEl.innerHTML = '<tr><td colspan="6" class="empty-state">No rows found in this statement</td></tr>';
      return;
    }

    const rawKeys = Object.keys(rows[0]);
    const lowerKeys = new Set(rawKeys.map(k => k.toLowerCase()));

    // Filter out system metadata keys, duplicate legacy aliases, and columns with 100% empty values
    const seenColNames = new Set();
    const columns = rawKeys.filter((col) => {
      const colLower = col.toLowerCase();
      if (IGNORED_SYSTEM_KEYS.has(colLower)) return false;

      // Deduplicate redundant legacy duplicate keys if canonical counterpart is present
      if (colLower === "bank_transaction_id" && lowerKeys.has("transaction_id")) return false;
      if (colLower === "date" && lowerKeys.has("transaction_date")) return false;
      if (colLower === "amount" && (lowerKeys.has("net_amount") || lowerKeys.has("gross_amount"))) return false;

      if (seenColNames.has(colLower)) return false;

      const hasVal = rows.some((r) => {
        const v = r[col];
        if (v === null || v === undefined) return false;
        const s = String(v).trim().toLowerCase();
        return s !== "" && s !== "nan" && s !== "none" && s !== "null" && s !== "undefined";
      });

      if (hasVal) {
        seenColNames.add(colLower);
        return true;
      }
      return false;
    });

    const displayCols = columns.length > 0 ? columns : rawKeys.filter(c => !IGNORED_SYSTEM_KEYS.has(c.toLowerCase()));

    // Render Header
    const headRow = document.createElement("tr");
    displayCols.forEach((col) => {
      const th = document.createElement("th");
      th.textContent = col.replace(/_/g, " ").toUpperCase();
      headRow.appendChild(th);
    });
    headEl.appendChild(headRow);

    // Render Rows
    rows.forEach((row, rIdx) => {
      const tr = document.createElement("tr");
      tr.dataset.rowIndex = rIdx;
      displayCols.forEach((col) => {
        const td = document.createElement("td");
        td.dataset.colKey = col;
        const val = row[col];

        if (editable) {
          const inp = document.createElement("input");
          inp.type = "text";
          inp.className = "form-input cell-edit-input";
          inp.value = val != null ? String(val) : "";
          inp.style.width = "100%";
          inp.style.minWidth = "80px";
          inp.style.padding = "4px 8px";
          inp.style.fontSize = "13px";
          inp.style.background = "var(--bg-card, #ffffff)";
          inp.style.border = "1px solid var(--border-color, #cbd5e1)";
          inp.style.borderRadius = "4px";
          inp.style.color = "var(--text-primary, #0f172a)";
          td.appendChild(inp);
        } else {
          td.textContent = val != null ? String(val) : "";
          const colLower = col.toLowerCase();
          if (colLower.includes("amount") || colLower.includes("debit") || colLower.includes("credit") || colLower.includes("dr")) {
            const num = Number(val);
            if (!isNaN(num) && val !== "" && val !== null) {
              const isDebitCol = colLower.includes("debit") || colLower.includes("dr") || colLower.includes("withdrawal") || colLower.includes("refund") || colLower.includes("fee");
              const isCreditCol = colLower.includes("credit") || colLower.includes("cr") || colLower.includes("deposit");

              if (isDebitCol) {
                td.classList.add("amount-negative");
                td.textContent = formatMoney(-Math.abs(num), true);
              } else if (isCreditCol) {
                td.classList.add("amount-positive");
                td.textContent = formatMoney(Math.abs(num), true);
              } else if (num < 0) {
                td.classList.add("amount-negative");
                td.textContent = formatMoney(num, true);
              } else if (num > 0) {
                td.classList.add("amount-positive");
                td.textContent = formatMoney(num, true);
              }
            }
          }
        }
        tr.appendChild(td);
      });
      bodyEl.appendChild(tr);
    });

    // Setup filter
    const searchInput = document.getElementById("stmtSearchInput");
    if (searchInput) {
      searchInput.oninput = () => {
        const query = searchInput.value.toLowerCase().trim();
        const trs = bodyEl.querySelectorAll("tr");
        trs.forEach((tr) => {
          const text = tr.textContent.toLowerCase();
          tr.style.display = text.includes(query) ? "" : "none";
        });
      };
    }
  }

  function triggerAppendData(statementId) {
    activeStatementId = statementId;
    const fileInput = document.getElementById("appendFileInput");
    fileInput.onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      try {
        const res = await window.LedgerApi.appendStatementData(statementId, file);
        const r = res.result || {};
        alert(r.message || `Appended ${r.appended_count || 0} new records.`);
        await loadSidebarSources();
        if (activeStatementId === statementId) {
          openStatementView(statementId);
        }
      } catch (err) {
        alert("Failed to append new statement data.");
      }
    };
    fileInput.click();
  }

  function initAppendButton() {
    const btn = document.getElementById("btnAppendData");
    if (btn) {
      btn.addEventListener("click", () => {
        if (activeStatementId) {
          triggerAppendData(activeStatementId);
        }
      });
    }
  }

  function showNotificationToast(msg, type = "success") {
    let toast = document.getElementById("ledgerGlobalToast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "ledgerGlobalToast";
      toast.style.position = "fixed";
      toast.style.bottom = "24px";
      toast.style.right = "24px";
      toast.style.padding = "12px 20px";
      toast.style.borderRadius = "8px";
      toast.style.fontWeight = "600";
      toast.style.fontSize = "14px";
      toast.style.zIndex = "99999";
      toast.style.boxShadow = "0 10px 25px rgba(0,0,0,0.15)";
      toast.style.transition = "all 0.3s cubic-bezier(0.16, 1, 0.3, 1)";
      toast.style.display = "flex";
      toast.style.alignItems = "center";
      toast.style.gap = "8px";
      document.body.appendChild(toast);
    }

    let iconSvg = "";

    if (type === "success") {
      toast.style.background = "#15803d";
      toast.style.color = "#ffffff";
      toast.style.border = "1px solid #22c55e";
      iconSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>';
    } else if (type === "info" || type === "loading") {
      toast.style.background = "#1e3a8a";
      toast.style.color = "#ffffff";
      toast.style.border = "1px solid #3b82f6";
      iconSvg = '<span class="spinner" style="width:16px; height:16px; border-width:2px; border-color:#ffffff #ffffff transparent transparent; margin-right:4px;"></span>';
    } else {
      toast.style.background = "#dc2626";
      toast.style.color = "#ffffff";
      toast.style.border = "1px solid #ef4444";
      iconSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
    }

    toast.innerHTML = `${iconSvg} <span>${msg}</span>`;
    toast.style.opacity = "1";
    toast.style.transform = "translateY(0)";

    if (type !== "loading") {
      setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(10px)";
      }, 3500);
    }
  }

  function initStatementToolbarButtons() {
    const editBtn = document.getElementById("btnEditStmtEntries");
    const editBtnText = document.getElementById("btnEditStmtEntriesText");
    const deleteColBtn = document.getElementById("btnDeleteStmtColumns");
    const realignLlmBtn = document.getElementById("btnRealignColumnsLLM");
    const realignLlmText = document.getElementById("btnRealignColumnsLLMText");

    if (realignLlmBtn) {
      realignLlmBtn.addEventListener("click", async () => {
        if (!activeStatementId) return;

        realignLlmBtn.disabled = true;
        if (realignLlmText) realignLlmText.textContent = "AI Organizing…";
        const svgIcon = realignLlmBtn.querySelector(".realign-icon");
        if (svgIcon) svgIcon.classList.add("spin-icon");

        try {
          const res = await window.LedgerApi.realignStatementColumnsLLM(activeStatementId);
          showNotificationToast("AI successfully organized table columns and learned new column rules!", "success");
          await openStatementView(activeStatementId);
        } catch (err) {
          alert(err.message || "Failed to organize table columns with AI.");
        } finally {
          realignLlmBtn.disabled = false;
          if (realignLlmText) realignLlmText.textContent = "Organize Table by AI";
          if (svgIcon) svgIcon.classList.remove("spin-icon");
        }
      });
    }

    if (editBtn) {
      editBtn.addEventListener("click", async () => {
        if (!activeStatementId) return;

        if (!isEditingStatementRows) {
          // Toggle to Edit Mode
          isEditingStatementRows = true;
          if (editBtnText) editBtnText.textContent = "Save Changes";
          editBtn.classList.add("is-editing");
          renderStatementRows(activeStatementLoadedRows, true);
        } else {
          // Collect updated values from table inputs
          const bodyEl = document.getElementById("stmtTableBody");
          const trs = bodyEl.querySelectorAll("tr");
          const updatedRows = [];

          trs.forEach((tr, rIdx) => {
            const rowObj = { ...(activeStatementLoadedRows[rIdx] || {}) };
            const tds = tr.querySelectorAll("td");
            tds.forEach((td) => {
              const colKey = td.dataset.colKey;
              if (colKey) {
                const inp = td.querySelector("input");
                rowObj[colKey] = inp ? inp.value.trim() : td.textContent.trim();
              }
            });
            if (Object.keys(rowObj).length > 0) {
              updatedRows.push(rowObj);
            }
          });

          editBtn.disabled = true;
          if (editBtnText) editBtnText.textContent = "Saving…";

          try {
            await window.LedgerApi.updateStatementRows(activeStatementId, updatedRows);
            isEditingStatementRows = false;
            resetEditStatementButtonState();
            await openStatementView(activeStatementId);
            showNotificationToast("Saved! Reconciliation pipeline is syncing in the background.", "success");
          } catch (err) {
            alert(err.message || "Failed to save statement edits.");
            resetEditStatementButtonState();
            isEditingStatementRows = false;
          } finally {
            editBtn.disabled = false;
          }
        }
      });
    }

    if (deleteColBtn) {
      deleteColBtn.addEventListener("click", () => {
        if (!activeStatementId || !activeStatementLoadedRows || activeStatementLoadedRows.length === 0) {
          alert("No columns available to delete.");
          return;
        }

        const cols = Object.keys(activeStatementLoadedRows[0]).filter(c => !IGNORED_SYSTEM_KEYS.has(c.toLowerCase()));
        const selectList = document.getElementById("deleteColumnSelectList");
        if (selectList) {
          selectList.innerHTML = "";
          cols.forEach((col) => {
            const label = document.createElement("label");
            label.style.display = "flex";
            label.style.alignItems = "center";
            label.style.gap = "10px";
            label.style.padding = "8px 12px";
            label.style.background = "var(--bg-card-subtle, #f8fafc)";
            label.style.border = "1px solid var(--border-color, #e2e8f0)";
            label.style.borderRadius = "6px";
            label.style.cursor = "pointer";
            label.style.fontWeight = "500";
            label.style.fontSize = "14px";
            label.style.color = "var(--text-primary, #0f172a)";

            label.innerHTML = `
              <input type="checkbox" value="${col}" class="delete-col-cb" style="width:16px; height:16px; accent-color:#dc2626;">
              <span>${col.replace(/_/g, " ").toUpperCase()} <span style="color:#94a3b8; font-size:12px;">(${col})</span></span>
            `;
            selectList.appendChild(label);
          });
        }

        const modalBackdrop = document.getElementById("deleteColumnModalBackdrop");
        if (modalBackdrop) modalBackdrop.style.display = "flex";
      });
    }

    const closeDeleteModal = () => {
      const modalBackdrop = document.getElementById("deleteColumnModalBackdrop");
      if (modalBackdrop) modalBackdrop.style.display = "none";
    };

    const closeBtn = document.getElementById("closeDeleteColumnModalBtn");
    const cancelBtn = document.getElementById("cancelDeleteColumnBtn");
    if (closeBtn) closeBtn.addEventListener("click", closeDeleteModal);
    if (cancelBtn) cancelBtn.addEventListener("click", closeDeleteModal);

    const confirmDeleteBtn = document.getElementById("confirmDeleteColumnBtn");
    if (confirmDeleteBtn) {
      confirmDeleteBtn.addEventListener("click", async () => {
        const cbs = document.querySelectorAll(".delete-col-cb:checked");
        const selectedCols = Array.from(cbs).map((cb) => cb.value);

        if (selectedCols.length === 0) {
          alert("Please select at least one column to delete.");
          return;
        }

        confirmDeleteBtn.disabled = true;
        confirmDeleteBtn.textContent = "Deleting…";

        try {
          await window.LedgerApi.deleteStatementColumns(activeStatementId, selectedCols);
          closeDeleteModal();
          await openStatementView(activeStatementId);
          showNotificationToast(`Deleted columns: ${selectedCols.join(", ")}. Syncing background pipeline...`, "success");
        } catch (err) {
          alert(err.message || "Failed to delete columns.");
        } finally {
          confirmDeleteBtn.disabled = false;
          confirmDeleteBtn.textContent = "Delete Selected Columns";
        }
      });
    }
  }

  // ------------------------------------------------------------------
  // Interactive Filters, Sorting & Collapsible Section Logic
  // ------------------------------------------------------------------

  let currentTransactions = [];
  let currentExceptions = [];
  let txSortKey = "date";
  let txSortAsc = false;
  let excSortKey = "date";
  let excSortAsc = false;
  let activeAmountTypeFilter = "all"; // "all" | "payments" | "deposits"

  window.filterByAmountType = function (type) {
    if (activeAmountTypeFilter === type) {
      activeAmountTypeFilter = "all";
    } else {
      activeAmountTypeFilter = type;
    }
    updateAmountFilterPills();
    updateTagFilterBar();
    applyTransactionFiltersAndRender();

    const el = document.getElementById("cardTxTable") || document.getElementById("txTable");
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  window.filterByStatusTag = function (tagId) {
    if (activeTagFilter === tagId) {
      activeTagFilter = "all";
    } else {
      activeTagFilter = tagId;
    }
    updateCountCardActiveState();
    updateTagFilterBar();
    applyTransactionFiltersAndRender();

    const el = document.getElementById("cardTxTable") || document.getElementById("txTable");
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  function updateCountCardActiveState() {
    const cardMap = {
      settled: document.getElementById("cardCountSettled"),
      auto: document.getElementById("cardCountAuto"),
      similar: document.getElementById("cardCountSimilar"),
      exception: document.getElementById("cardCountManual"),
      unreconciled: document.getElementById("cardCountUnreconciled")
    };

    Object.keys(cardMap).forEach((tag) => {
      const card = cardMap[tag];
      if (!card) return;
      if (activeTagFilter === tag) {
        card.style.border = "1px solid var(--accent-blue, #3b82f6)";
        card.style.boxShadow = "0 0 12px rgba(59, 130, 246, 0.45)";
        card.style.background = "rgba(59, 130, 246, 0.14)";
      } else {
        card.style.border = "";
        card.style.boxShadow = "";
        card.style.background = "";
      }
    });
  }

  function updateAmountFilterPills() {
    const payEl = document.getElementById("btnStatPayments");
    const depEl = document.getElementById("btnStatDeposits");
    const badgeEl = document.getElementById("txAmountFilterBadge");

    if (payEl) {
      if (activeAmountTypeFilter === "payments") {
        payEl.style.background = "rgba(239, 68, 68, 0.22)";
        payEl.style.border = "1px solid #ef4444";
        payEl.style.boxShadow = "0 0 10px rgba(239, 68, 68, 0.4)";
      } else {
        payEl.style.background = "transparent";
        payEl.style.border = "1px solid transparent";
        payEl.style.boxShadow = "none";
      }
    }

    if (depEl) {
      if (activeAmountTypeFilter === "deposits") {
        depEl.style.background = "rgba(16, 185, 129, 0.22)";
        depEl.style.border = "1px solid #10b981";
        depEl.style.boxShadow = "0 0 10px rgba(16, 185, 129, 0.4)";
      } else {
        depEl.style.background = "transparent";
        depEl.style.border = "1px solid transparent";
        depEl.style.boxShadow = "none";
      }
    }

    if (badgeEl) {
      if (activeAmountTypeFilter === "payments") {
        badgeEl.style.display = "inline-flex";
        badgeEl.style.background = "rgba(239, 68, 68, 0.15)";
        badgeEl.style.color = "#ef4444";
        badgeEl.style.border = "1px solid #ef4444";
        badgeEl.innerHTML = "Filtered: Payments (- Outflows) &times;";
      } else if (activeAmountTypeFilter === "deposits") {
        badgeEl.style.display = "inline-flex";
        badgeEl.style.background = "rgba(16, 185, 129, 0.15)";
        badgeEl.style.color = "#10b981";
        badgeEl.style.border = "1px solid #10b981";
        badgeEl.innerHTML = "Filtered: Deposits (+ Inflows) &times;";
      } else {
        badgeEl.style.display = "none";
      }
    }
  }

  function initCollapsibleSections() {
    document.querySelectorAll(".card-header-toggle").forEach((header) => {
      header.addEventListener("click", () => {
        const targetId = header.dataset.collapse;
        const target = document.getElementById(targetId);
        if (target) {
          header.classList.toggle("collapsed");
          target.classList.toggle("collapsed-content");
        }
      });
    });
  }

  function initTableSorting() {
    // Matched Transactions Headers
    document.querySelectorAll("#txTable .sort-header").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sortKey;
        if (txSortKey === key) {
          txSortAsc = !txSortAsc;
        } else {
          txSortKey = key;
          txSortAsc = true;
        }
        updateSortHeaders("#txTable", txSortKey, txSortAsc);
        applyTransactionFiltersAndRender();
      });
    });

    // Exceptions Headers
    document.querySelectorAll("#excTable .sort-header").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sortKey;
        if (excSortKey === key) {
          excSortAsc = !excSortAsc;
        } else {
          excSortKey = key;
          excSortAsc = true;
        }
        updateSortHeaders("#excTable", excSortKey, excSortAsc);
        applyExceptionFiltersAndRender();
      });
    });
  }

  function updateSortHeaders(tableSelector, activeKey, isAsc) {
    document.querySelectorAll(`${tableSelector} .sort-header`).forEach((th) => {
      const isCurrent = th.dataset.sortKey === activeKey;
      th.classList.toggle("active-sort", isCurrent);
      const arrow = th.querySelector(".sort-arrow");
      if (arrow) {
        arrow.textContent = isCurrent ? (isAsc ? "↑" : "↓") : "↕";
      }
    });
  }

  let activeTagFilter = "all";
  let isTagFilterExpanded = false;

  function getTxTags(tx) {
    const tags = ["all"];
    const st = (tx.status || "").toLowerCase().trim();

    if (st === "settled") {
      tags.push("settled");
    } else if (st === "auto" || st === "matched" || st === "exact" || st === "tolerance") {
      tags.push("auto");
    } else if (st === "similar" || st === "proposed") {
      tags.push("similar");
    } else if (st === "unreconciled" || st === "unmatched" || st === "rejected") {
      tags.push("unreconciled");
    } else if (st === "exception" || st === "manual" || st === "review") {
      tags.push("exception");
    } else if (st === "llm") {
      tags.push("llm");
    } else if (st === "ml") {
      tags.push("ml");
    }

    const ev = tx.evidence || {};
    if (ev.identifier_matched) {
      tags.push("utr_match");
    } else if (st === "llm" || st === "ml" || st === "manual" || st === "unmatched" || st === "exception" || st === "unreconciled") {
      tags.push("utr_mismatch");
    }

    const dateDiff = ev.date_difference_days || 0;
    if (dateDiff > 0) {
      tags.push("date_gap");
    }

    const amtDiff = Math.abs(ev.amount_difference !== undefined ? ev.amount_difference : 0);
    if (amtDiff > 0.01) {
      tags.push("amt_diff");
    }

    if (tx.is_split || ev.is_split || (tx.stage && tx.stage.includes("split")) || (ev.candidate_count && ev.candidate_count > 1 && !ev.identifier_matched)) {
      tags.push("split_txn");
    }

    if (tx.fee_aware || (tx.reason && tx.reason.toLowerCase().includes("fee"))) {
      tags.push("fee_aware");
    }

    return tags;
  }

  const TAG_METADATA = {
    all: { label: "All", priority: 1 },
    settled: { label: "Settled", priority: 2 },
    auto: { label: "Matched", priority: 3 },
    similar: { label: "Similar", priority: 4 },
    exception: { label: "Exception", priority: 5 },
    unreconciled: { label: "Unreconciled", priority: 6 },
    llm: { label: "LLM", priority: 7 },
    ml: { label: "ML", priority: 8 },
    utr_mismatch: { label: "UTR Mismatch", priority: 9 },
    utr_match: { label: "UTR Match", priority: 10 },
    date_gap: { label: "Date Gap", priority: 11 },
    amt_diff: { label: "Amt Diff", priority: 12 },
    split_txn: { label: "Split Txn", priority: 13 },
    fee_aware: { label: "Fee Aware", priority: 14 },
  };

  function updateTagFilterBar() {
    const container = document.getElementById("txTagFilterBar");
    if (!container) return;

    const tagCounts = {};
    Object.keys(TAG_METADATA).forEach((id) => (tagCounts[id] = 0));

    let txPool = currentTransactions;
    if (activeAmountTypeFilter === "payments") {
      txPool = currentTransactions.filter((tx) => (Number(tx.amount) || 0) < 0);
    } else if (activeAmountTypeFilter === "deposits") {
      txPool = currentTransactions.filter((tx) => (Number(tx.amount) || 0) > 0);
    }

    txPool.forEach((tx) => {
      const tags = getTxTags(tx);
      tags.forEach((t) => {
        if (tagCounts[t] !== undefined) {
          tagCounts[t]++;
        } else {
          tagCounts[t] = (tagCounts[t] || 0) + 1;
        }
      });
    });

    let availableTags = Object.keys(TAG_METADATA)
      .map((id) => ({
        id,
        label: TAG_METADATA[id].label,
        priority: TAG_METADATA[id].priority,
        count: tagCounts[id] || 0,
      }))
      .filter((t) => t.id === "all" || t.count > 0);

    availableTags.sort((a, b) => {
      if (a.id === "all") return -1;
      if (b.id === "all") return 1;
      return a.priority - b.priority;
    });

    const TOP_TAG_COUNT = 4;
    const hasMore = availableTags.length > TOP_TAG_COUNT;
    const visibleTags = isTagFilterExpanded ? availableTags : availableTags.slice(0, TOP_TAG_COUNT);

    let html = "";
    visibleTags.forEach((tag) => {
      const isActive = activeTagFilter === tag.id;
      html += `
        <button type="button" class="tag-pill-btn ${isActive ? "active" : ""}" data-tag="${tag.id}">
          <span>${tag.label}</span>
          <span class="tag-count">${tag.count}</span>
        </button>
      `;
    });

    if (hasMore) {
      if (!isTagFilterExpanded) {
        const extraCount = availableTags.length - TOP_TAG_COUNT;
        html += `
          <button type="button" class="tag-pill-btn tag-btn-toggle" id="btnToggleMoreTags">
            <span>+ ${extraCount} More</span>
          </button>
        `;
      } else {
        html += `
          <button type="button" class="tag-pill-btn tag-btn-toggle" id="btnToggleMoreTags">
            <span>- Less</span>
          </button>
        `;
      }
    }

    container.innerHTML = html;

    container.querySelectorAll(".tag-pill-btn[data-tag]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeTagFilter = btn.getAttribute("data-tag");
        updateCountCardActiveState();
        updateTagFilterBar();
        applyTransactionFiltersAndRender();
      });
    });

    const toggleBtn = container.querySelector("#btnToggleMoreTags");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", () => {
        isTagFilterExpanded = !isTagFilterExpanded;
        updateTagFilterBar();
      });
    }
  }

  function initFilterInputs() {
    const txSearch = document.getElementById("txSearchInput");
    if (txSearch) txSearch.addEventListener("input", applyTransactionFiltersAndRender);

    const excSearch = document.getElementById("excSearchInput");
    if (excSearch) excSearch.addEventListener("input", applyExceptionFiltersAndRender);
  }

  function applyTransactionFiltersAndRender() {
    let list = [...currentTransactions];
    const q = (document.getElementById("txSearchInput")?.value || "").toLowerCase().trim();

    if (activeAmountTypeFilter === "payments") {
      list = list.filter((tx) => (Number(tx.amount) || 0) < 0);
    } else if (activeAmountTypeFilter === "deposits") {
      list = list.filter((tx) => (Number(tx.amount) || 0) > 0);
    }

    if (activeTagFilter !== "all") {
      list = list.filter((tx) => {
        const tags = getTxTags(tx);
        return tags.includes(activeTagFilter);
      });
    }

    if (q) {
      list = list.filter((tx) => {
        const d = (tx.date || "").toLowerCase();
        const b = (tx.bank_description || tx.description || "").toLowerCase();
        const g = (tx.gl_description || "").toLowerCase();
        const a = String(tx.amount || "");
        const st = (tx.status || "").toLowerCase();
        return d.includes(q) || b.includes(q) || g.includes(q) || a.includes(q) || st.includes(q);
      });
    }

    // Sort list
    list.sort((a, b) => {
      let valA = a[txSortKey];
      let valB = b[txSortKey];
      if (txSortKey === "primary_id") {
        valA = a.primary_id || a.settlement_id || a.bank_transaction_id || "";
        valB = b.primary_id || b.settlement_id || b.bank_transaction_id || "";
      } else if (txSortKey === "source_type_label") {
        valA = a.source_type_label || a.source_type || a.source || "";
        valB = b.source_type_label || b.source_type || b.source || "";
      } else if (txSortKey === "matched_source_type_label") {
        valA = a.matched_source_type_label || a.matched_source_type || "";
        valB = b.matched_source_type_label || b.matched_source_type || "";
      }

      valA = valA ?? "";
      valB = valB ?? "";

      if (txSortKey === "amount") {
        valA = Number(valA) || 0;
        valB = Number(valB) || 0;
      } else {
        valA = String(valA).toLowerCase();
        valB = String(valB).toLowerCase();
      }
      if (valA < valB) return txSortAsc ? -1 : 1;
      if (valA > valB) return txSortAsc ? 1 : -1;
      return 0;
    });

    renderTransactionsTable(list);
  }

  let activeExcTagFilter = "all";
  let isExcTagFilterExpanded = false;

  function getUnmatchedTransactions() {
    return (currentTransactions || []).filter((tx) => {
      const st = (tx.status || "").toLowerCase().trim();
      const ds = (tx.dashboard_status || "").toLowerCase().trim();
      return (
        st === "unmatched" ||
        st === "unreconciled" ||
        st === "exception" ||
        ds === "unreconciled" ||
        ds === "unmatched"
      );
    });
  }

  function updateExcTagFilterBar() {
    const container = document.getElementById("excTagFilterBar");
    if (!container) return;

    const unmatchedList = getUnmatchedTransactions();
    const tagCounts = {};
    Object.keys(TAG_METADATA).forEach((id) => (tagCounts[id] = 0));

    unmatchedList.forEach((tx) => {
      const tags = getTxTags(tx);
      tags.forEach((t) => {
        if (tagCounts[t] !== undefined) {
          tagCounts[t]++;
        } else {
          tagCounts[t] = (tagCounts[t] || 0) + 1;
        }
      });
    });

    let availableTags = Object.keys(TAG_METADATA)
      .map((id) => ({
        id,
        label: TAG_METADATA[id].label,
        priority: TAG_METADATA[id].priority,
        count: tagCounts[id] || 0,
      }))
      .filter((t) => t.id === "all" || t.count > 0);

    availableTags.sort((a, b) => {
      if (a.id === "all") return -1;
      if (b.id === "all") return 1;
      return a.priority - b.priority;
    });

    const TOP_TAG_COUNT = 4;
    const hasMore = availableTags.length > TOP_TAG_COUNT;
    const visibleTags = isExcTagFilterExpanded ? availableTags : availableTags.slice(0, TOP_TAG_COUNT);

    let html = "";
    visibleTags.forEach((tag) => {
      const isActive = activeExcTagFilter === tag.id;
      html += `
        <button type="button" class="tag-pill-btn ${isActive ? "active" : ""}" data-tag="${tag.id}">
          <span>${tag.label}</span>
          <span class="tag-count">${tag.count}</span>
        </button>
      `;
    });

    if (hasMore) {
      if (!isExcTagFilterExpanded) {
        const extraCount = availableTags.length - TOP_TAG_COUNT;
        html += `
          <button type="button" class="tag-pill-btn tag-btn-toggle" id="btnToggleMoreExcTags">
            <span>+ ${extraCount} More</span>
          </button>
        `;
      } else {
        html += `
          <button type="button" class="tag-pill-btn tag-btn-toggle" id="btnToggleMoreExcTags">
            <span>- Less</span>
          </button>
        `;
      }
    }

    container.innerHTML = html;

    container.querySelectorAll(".tag-pill-btn[data-tag]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeExcTagFilter = btn.getAttribute("data-tag");
        updateExcTagFilterBar();
        applyExceptionFiltersAndRender();
      });
    });

    const toggleBtn = container.querySelector("#btnToggleMoreExcTags");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", () => {
        isExcTagFilterExpanded = !isExcTagFilterExpanded;
        updateExcTagFilterBar();
      });
    }
  }

  function applyExceptionFiltersAndRender() {
    updateExcTagFilterBar();

    let list = getUnmatchedTransactions();
    const q = (document.getElementById("excSearchInput")?.value || "").toLowerCase().trim();

    if (activeExcTagFilter !== "all") {
      list = list.filter((tx) => {
        const tags = getTxTags(tx);
        return tags.includes(activeExcTagFilter);
      });
    }

    if (q) {
      list = list.filter((tx) => {
        const d = (tx.date || "").toLowerCase();
        const b = (tx.bank_description || tx.description || "").toLowerCase();
        const g = (tx.gl_description || "").toLowerCase();
        const a = String(tx.amount || "");
        const st = (tx.status || "").toLowerCase();
        const pid = (tx.primary_id || tx.settlement_id || tx.bank_transaction_id || "").toLowerCase();
        return d.includes(q) || b.includes(q) || g.includes(q) || a.includes(q) || st.includes(q) || pid.includes(q);
      });
    }

    // Sort list
    list.sort((a, b) => {
      let valA = a[excSortKey];
      let valB = b[excSortKey];
      if (excSortKey === "primary_id") {
        valA = a.primary_id || a.settlement_id || a.bank_transaction_id || "";
        valB = b.primary_id || b.settlement_id || b.bank_transaction_id || "";
      } else if (excSortKey === "source_type_label") {
        valA = a.source_type_label || a.source_type || a.source || "";
        valB = b.source_type_label || b.source_type || b.source || "";
      } else if (excSortKey === "matched_source_type_label") {
        valA = a.matched_source_type_label || a.matched_source_type || "";
        valB = b.matched_source_type_label || b.matched_source_type || "";
      }

      valA = valA ?? "";
      valB = valB ?? "";

      if (excSortKey === "amount") {
        valA = Number(valA) || 0;
        valB = Number(valB) || 0;
      } else {
        valA = String(valA).toLowerCase();
        valB = String(valB).toLowerCase();
      }
      if (valA < valB) return excSortAsc ? -1 : 1;
      if (valA > valB) return excSortAsc ? 1 : -1;
      return 0;
    });

    renderTransactionsTable(list, "exceptionsBody", "exceptionsEmpty", "excBadgeCount");
  }

  function renderSummary(run) {
    const s = run.summary || {};
    const total = s.total_transactions || 0;
    const settled = s.settled_count || 0;
    const auto = s.auto_matched || 0;
    const llmCount = s.llm_matched || 0;
    const exceptionsCount = s.exceptions_count || (run.exceptions ? run.exceptions.length : 0);
    const manual = s.manual_matched || 0;
    const unreconciled = s.unreconciled || 0;
    const percent = s.percent_reconciled != null ? s.percent_reconciled : 0;
    const formattedPeriod = formatPeriodLabel(run.period_label);

    document.getElementById("periodBadge").textContent = formattedPeriod || "No Data";
    document.getElementById("periodBadge").classList.toggle("badge-closed", !!run.closed);
    document.getElementById("closePeriodBtn").textContent = run.closed ? "Period Closed ✓" : "Close Period";
    document.getElementById("closePeriodBtn").disabled = !!run.closed;

    const hdrBadge = document.getElementById("hdrManualBadge");
    if (hdrBadge) {
      hdrBadge.textContent = exceptionsCount;
      hdrBadge.style.display = "inline-flex";
    }

    const cpCloseBtn = document.getElementById("cpClosePeriodBtn");
    if (cpCloseBtn) {
      cpCloseBtn.textContent = run.closed ? "Period Closed ✓" : "Close Period";
      cpCloseBtn.disabled = !!run.closed;
    }

    const reconciledCount = settled + auto + llmCount;
    const calculatedPercent = total > 0 ? ((reconciledCount / total) * 100).toFixed(1) : "0.0";

    const labelEl = document.getElementById("progressLabel");
    if (labelEl) labelEl.textContent = `${calculatedPercent}% Reconciled`;

    const fracEl = document.getElementById("progressFraction");
    if (fracEl) fracEl.textContent = `${reconciledCount}/${total}`;

    const pct = (n) => (total > 0 ? (n / total) * 100 : 0);
    const segAutoEl = document.getElementById("segAuto");
    if (segAutoEl) {
      segAutoEl.style.width = `${pct(reconciledCount)}%`;
      segAutoEl.style.display = "block";
      segAutoEl.title = `Reconciled: ${reconciledCount} / ${total} (${calculatedPercent}%)`;
    }

    const segManualEl = document.getElementById("segManual");
    if (segManualEl) {
      segManualEl.style.width = "0%";
      segManualEl.style.display = "none";
    }

    const segUnreconciledEl = document.getElementById("segUnreconciled");
    if (segUnreconciledEl) {
      segUnreconciledEl.style.width = "0%";
      segUnreconciledEl.style.display = "none";
    }

    document.getElementById("statBeginning").textContent = formatMoney(s.beginning_balance, false);

    const payEl = document.getElementById("statPayments");
    if (payEl) {
      payEl.textContent = `-₹${Math.abs(s.payments_total || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      payEl.style.color = "#ef4444";
      payEl.style.fontWeight = "600";
    }

    const depEl = document.getElementById("statDeposits");
    if (depEl) {
      depEl.textContent = `+₹${Math.abs(s.deposits_total || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      depEl.style.color = "#10b981";
      depEl.style.fontWeight = "600";
    }

    const varianceEl = document.getElementById("statVariance");
    const varVal = s.variance || 0;
    varianceEl.textContent = `${varVal >= 0 ? "+" : "-"}₹${Math.abs(varVal).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    varianceEl.style.color = varVal < 0 ? "#ef4444" : "#10b981";
    varianceEl.style.fontWeight = "600";

    const settledEl = document.getElementById("countSettled");
    if (settledEl) settledEl.textContent = settled;

    document.getElementById("countAuto").textContent = auto;

    // Calculate Similar count from current transactions list
    const txList = currentTransactions || [];
    const similarCount = txList.filter(t => (t.status || "").toLowerCase() === "similar").length;
    const countSimilarEl = document.getElementById("countSimilar");
    if (countSimilarEl) countSimilarEl.textContent = similarCount;

    const llmEl = document.getElementById("countLlm");
    if (llmEl) llmEl.textContent = llmCount;

    document.getElementById("countManual").textContent = exceptionsCount;
    document.getElementById("countUnreconciled").textContent = unreconciled;

    // Executive Overview (Current Period) Updates
    const cpSubtitle = document.getElementById("cpSubtitle");
    if (cpSubtitle) cpSubtitle.textContent = `Bank reconciliation for ${formattedPeriod}`;
    const cpPeriodBadge = document.getElementById("cpPeriodBadge");
    if (cpPeriodBadge) cpPeriodBadge.textContent = formattedPeriod;

    const cpStatTotal = document.getElementById("cpStatTotal");
    if (cpStatTotal) cpStatTotal.textContent = total.toLocaleString();

    const matchedCount = auto + llmCount;
    const cpStatMatched = document.getElementById("cpStatMatched");
    if (cpStatMatched) cpStatMatched.textContent = matchedCount.toLocaleString();

    const cpStatMatchedPct = document.getElementById("cpStatMatchedPct");
    if (cpStatMatchedPct) cpStatMatchedPct.textContent = `${percent.toFixed ? percent.toFixed(1) : percent}%`;

    const cpStatUnmatched = document.getElementById("cpStatUnmatched");
    if (cpStatUnmatched) cpStatUnmatched.textContent = unreconciled.toLocaleString();

    const cpStatUnmatchedPct = document.getElementById("cpStatUnmatchedPct");
    const unPcnt = total > 0 ? (unreconciled / total * 100).toFixed(1) : "0.0";
    if (cpStatUnmatchedPct) cpStatUnmatchedPct.textContent = `${unPcnt}%`;

    const cpStatExceptions = document.getElementById("cpStatExceptions");
    if (cpStatExceptions) cpStatExceptions.textContent = manual.toLocaleString();

    const cpProgressFill = document.getElementById("cpProgressFill");
    if (cpProgressFill) cpProgressFill.style.width = `${percent.toFixed ? percent.toFixed(1) : percent}%`;

    const cpProgressPct = document.getElementById("cpProgressPct");
    if (cpProgressPct) cpProgressPct.textContent = `${percent.toFixed ? percent.toFixed(1) : percent}%`;

    const cpProgressCaption = document.getElementById("cpProgressCaption");
    if (cpProgressCaption) {
      cpProgressCaption.innerHTML = `${matchedCount.toLocaleString()} matched &bull; ${unreconciled.toLocaleString()} unmatched &bull; ${manual.toLocaleString()} need review`;
    }

    const cpAttUnmatched = document.getElementById("cpAttUnmatched");
    if (cpAttUnmatched) cpAttUnmatched.textContent = `${unreconciled} unmatched transactions`;

    const cpAttAmbiguous = document.getElementById("cpAttAmbiguous");
    if (cpAttAmbiguous) cpAttAmbiguous.textContent = `${manual} ambiguous matches`;

    const cpAttDiscrepancy = document.getElementById("cpAttDiscrepancy");
    if (cpAttDiscrepancy) cpAttDiscrepancy.textContent = `${formatMoney(s.variance)} discrepancy`;

    const heroSettledBadge = document.getElementById("periodSettledHeroBadge");
    if (heroSettledBadge) {
      const isSettled = Boolean(run.period_settled || (unreconciled === 0 && manual === 0 && total > 0));
      heroSettledBadge.style.display = isSettled ? "inline-block" : "none";
    }

    loadRecentRuns();
  }

  function getTaxonomyInfo(tx) {
    const statusStr = (typeof tx === "string" ? tx : (tx && tx.status) || "").toLowerCase().trim();
    const confRaw = typeof tx === "object" ? (tx.confidence ?? tx.confidence_score ?? tx.score ?? tx.ml_confidence ?? 1.0) : 1.0;
    const confPct = Math.round(Number(confRaw) * 100);

    if (statusStr === "settled") {
      return { taxonomy: "SETTLED", pillClass: "status-settled", label: "SETTLED" };
    }
    if (statusStr === "auto" || statusStr === "matched" || statusStr === "exact" || statusStr === "tolerance" || statusStr === "llm" || statusStr === "confirmed_match") {
      return { taxonomy: "MATCHED", pillClass: "status-auto", label: `MATCHED (${confPct}%)` };
    }
    if (statusStr === "similar" || statusStr === "proposed" || statusStr === "ml") {
      return { taxonomy: "SIMILAR", pillClass: "status-manual", label: `SIMILAR (${confPct}%)` };
    }
    if (statusStr === "unreconciled" || statusStr === "unmatched" || statusStr === "rejected") {
      return { taxonomy: "UNRECONCILED", pillClass: "status-unmatched", label: "UNRECONCILED" };
    }
    return { taxonomy: "EXCEPTION", pillClass: "status-manual", label: "EXCEPTION" };
  }

  function statusPillClass(tx) {
    return getTaxonomyInfo(tx).pillClass;
  }

  function getStatusLabel(tx) {
    return getTaxonomyInfo(tx).label;
  }


  function getFeatureFlagsHTML(tx) {
    const flags = [];
    const ev = tx.evidence || {};
    const st = (tx.status || "").toLowerCase().trim();

    // 1. UTR Match vs UTR Mismatch
    if (ev.identifier_matched) {
      flags.push({ label: "UTR Match", type: "success" });
    } else if (st === "llm" || st === "ml" || st === "manual" || st === "unmatched" || st === "exception") {
      flags.push({ label: "UTR Mismatch", type: "warning" });
    }

    // 2. Date Gap Tolerance
    const dateDiff = ev.date_difference_days || 0;
    if (dateDiff > 0) {
      flags.push({ label: `Date Gap (+${dateDiff}d)`, type: "info" });
    }

    // 3. Amount Difference
    const amtDiff = Math.abs(ev.amount_difference !== undefined ? ev.amount_difference : 0);
    if (amtDiff > 0.01) {
      flags.push({ label: `Amt Diff (${formatMoney(amtDiff)})`, type: "amber" });
    }

    // 4. Split Transactions
    if (tx.is_split || ev.is_split || (tx.stage && tx.stage.includes("split")) || (ev.candidate_count && ev.candidate_count > 1 && !ev.identifier_matched)) {
      flags.push({ label: "Split Txn", type: "purple" });
    }

    // 5. Fee Aware
    if (tx.fee_aware || (tx.reason && tx.reason.toLowerCase().includes("fee"))) {
      flags.push({ label: "Fee Aware", type: "cyan" });
    }

    if (flags.length === 0) {
      flags.push({ label: "Exact Match", type: "success" });
    }

    return `<div class="flags-cell">${flags.map(f => `<span class="flag-chip flag-${f.type}">${f.label}</span>`).join("")}</div>`;
  }

  function openRecordComparisonModal(tx) {
    const modalBackdrop = document.getElementById("compareModalBackdrop");
    if (!modalBackdrop) return;

    // Display modal container
    modalBackdrop.style.display = "flex";

    // Reset similar payments panel
    const similarPanel = document.getElementById("cmpSimilarPaymentsPanel");
    if (similarPanel) similarPanel.style.display = "none";

    const isReconciled = tx.status === "settled" || tx.status === "matched" || tx.status === "auto" || tx.status === "tolerance" || tx.status === "similar" || tx.status === "llm" || tx.status === "manual";

    let counterpart = tx.counterpart;
    if (!counterpart && tx.matched_sources && tx.matched_sources.length > 0) {
      const ms = tx.matched_sources[0];
      counterpart = {
        id: ms.id || tx.bank_transaction_id || tx.utr || "—",
        source_name: ms.name || ms.type || "Matched Source",
        source_type: ms.type || "counterpart",
        source_color: ms.color || "#10b981"
      };
    } else if (!counterpart && isReconciled) {
      counterpart = {
        id: tx.bank_transaction_id || tx.utr || tx.settlement_id || tx.primary_id || "—",
        source_name: tx.matched_source_name || "Counterpart Statement",
        source_type: tx.matched_source_type || "counterpart",
        source_color: "#10b981"
      };
    }

    const hasCounterpart = Boolean((tx.has_counterpart && tx.counterpart) || counterpart || (tx.matched_sources && tx.matched_sources.length > 0) || isReconciled);
    const confPct = Math.round((tx.confidence || 0.95) * 100);

    // 1. Score Badge & Title Contradiction Fix
    const scoreBadge = document.getElementById("compareMatchScoreBadge");
    if (scoreBadge) {
      if (tx.status === "unmatched" || tx.status === "unreconciled" || !hasCounterpart) {
        scoreBadge.textContent = "No Match Reconciled";
        scoreBadge.className = "compare-match-score score-unmatched";
      } else if (tx.status === "settled") {
        scoreBadge.textContent = "Settled (100% Match)";
        scoreBadge.className = "compare-match-score score-matched";
      } else if (tx.status === "similar" || tx.status === "manual" || confPct < 90) {
        scoreBadge.textContent = `Potential Match / Similarity (${confPct}%)`;
        scoreBadge.className = "compare-match-score score-potential";
      } else {
        scoreBadge.textContent = `${confPct}% Match Confidence`;
        scoreBadge.className = "compare-match-score score-matched";
      }
    }

    function getReadableSourceLabel(type, fallback, txObj) {
      if (txObj && txObj.source_name) return txObj.source_name;
      if (txObj && txObj.source_type_label && !txObj.source_type_label.toLowerCase().includes("statement record")) return txObj.source_type_label;
      if (txObj && txObj.source_label && !txObj.source_label.toLowerCase().includes("statement record")) return txObj.source_label;
      if (fallback && fallback !== "primary" && fallback !== "none" && !fallback.includes("Gateway") && fallback !== "Statement Record" && fallback !== "Statement") return fallback;
      const st = String(type || "").toLowerCase().replace(/\s+/g, "_");
      return st ? st.replace(/_/g, " ").toUpperCase() : "STATEMENT";
    }

    // 2. Primary Source Record Card (Derived from real transaction metadata)
    const primarySrcType = tx.source_type || "bank";
    const primarySrcName = tx.source_name || tx.source_type_label || getReadableSourceLabel(tx.source_type, tx.source, tx);
    const primaryIdVal = tx.primary_id || tx.settlement_id || tx.utr || tx.id || "—";

    const primaryTag = document.getElementById("cmpPrimaryTag");
    if (primaryTag) primaryTag.textContent = primarySrcName.toUpperCase();
    document.getElementById("cmpSettlementId").textContent = primaryIdVal;
    document.getElementById("cmpSettlementSource").textContent = primarySrcName;
    document.getElementById("cmpSettlementUtr").textContent = tx.utr || tx.settlement_id || "—";
    document.getElementById("cmpSettlementPaymentId").textContent = tx.order_id || tx.payment_id || tx.settlement_id || "—";
    document.getElementById("cmpSettlementDate").textContent = formatDateDDMMYYYY(tx.date);
    document.getElementById("cmpSettlementAmount").textContent = formatMoney(tx.amount);
    document.getElementById("cmpSettlementStatus").textContent = (tx.status || "unmatched").toUpperCase();

    const leftViewBtn = document.getElementById("cmpLeftViewSourceBtn");
    if (leftViewBtn) {
      leftViewBtn.onclick = (e) => {
        e.stopPropagation();
        findAndOpenStatementForSource(primarySrcType, primaryIdVal, tx.source_name || primarySrcName, tx.statement_id);
      };
    }

    // 3. Counterpart Record Card or Empty State
    const secondaryHeader = document.getElementById("cmpSecondaryHeader");
    const secondaryParamList = document.getElementById("cmpSecondaryParamList");
    const secondaryEmptyState = document.getElementById("cmpSecondaryEmptyState");
    const matrixWrap = document.getElementById("cmpMatrixWrap");
    const tbody = document.getElementById("compareTableBody");

    if (hasCounterpart && counterpart) {
      if (secondaryHeader) secondaryHeader.style.display = "flex";
      if (secondaryParamList) secondaryParamList.style.display = "flex";
      if (secondaryEmptyState) secondaryEmptyState.style.display = "none";
      if (matrixWrap) matrixWrap.style.display = "block";

      const counterSrcLabel = counterpart.source_name || counterpart.source_label || (counterpart.source_type ? counterpart.source_type.replace("_", " ").toUpperCase() : "COUNTERPART");
      const secondaryTag = document.getElementById("cmpSecondaryTag");
      if (secondaryTag) secondaryTag.textContent = counterSrcLabel.toUpperCase();

      document.getElementById("cmpBankId").textContent = counterpart.id || "—";
      document.getElementById("cmpBankSource").textContent = counterSrcLabel;
      document.getElementById("cmpBankUtr").textContent = counterpart.id || "—";
      document.getElementById("cmpBankTxId").textContent = counterpart.id || "—";
      document.getElementById("cmpBankDate").textContent = formatDateDDMMYYYY(counterpart.date || tx.date);
      document.getElementById("cmpBankAmount").textContent = formatMoney(tx.amount);
      document.getElementById("cmpBankDesc").textContent = tx.bank_description || tx.reason || "Matched Record";

      const rightViewBtn = document.getElementById("cmpRightViewSourceBtn");
      if (rightViewBtn) {
        rightViewBtn.onclick = (e) => {
          e.stopPropagation();
          findAndOpenStatementForSource(counterpart.source_type, counterpart.id, counterpart.source_name || counterpart.source_label, counterpart.statement_id);
        };
      }

      function extractSharedKeywords(str1, str2) {
        if (!str1 || !str2) return [];
        const STOP_WORDS = new Set(["the", "and", "for", "with", "ref", "txn", "card", "setl", "upi", "bank", "settlement", "payment", "inc", "ltd", "pvt", "corp", "org", "transfer", "neft", "rtgs", "imps", "from", "to", "via", "val", "date"]);
        const cleanTokens = (s) => String(s).toLowerCase().replace(/[^a-z0-9\s]/g, " ").split(/\s+/).filter(w => w.length >= 2 && !STOP_WORDS.has(w));

        const set1 = new Set(cleanTokens(str1));
        const set2 = cleanTokens(str2);
        const shared = new Set();
        set2.forEach(w => {
          if (set1.has(w)) shared.add(w.toUpperCase());
        });
        return Array.from(shared);
      }

      // Populate Parameter Match Matrix Table Body
      const ev = tx.evidence || {};
      const amtDiff = ev.amount_difference !== undefined ? Math.abs(ev.amount_difference) : 0;
      const amtStatus = amtDiff === 0 ? '<span class="status-pill status-exact">Exact Match</span>' : `<span class="status-pill status-tolerance">Variance: ₹${amtDiff.toFixed(2)}</span>`;
      const dateGap = ev.date_difference_days !== undefined ? ev.date_difference_days : 0;
      const dateStatus = dateGap === 0 ? '<span class="status-pill status-exact">Same Date</span>' : `<span class="status-pill status-tolerance">${dateGap} day gap</span>`;

      // Extract Description & Similar Keywords
      const pDesc = tx.bank_description || tx.description || tx.primary_id || "";
      const cDesc = counterpart.description || counterpart.bank_description || counterpart.id || "";
      const sharedKws = extractSharedKeywords(pDesc, cDesc);

      const sharedKwBadge = sharedKws.length > 0
        ? `<span class="status-pill status-exact" style="background: rgba(52, 211, 153, 0.2); color: #34d399; font-weight:600;">Shared Keywords: ${sharedKws.map(escapeHtml).join(", ")}</span>`
        : `<span class="status-pill" style="opacity: 0.75; font-size:0.78rem;">Fuzzy / Field Linked Match</span>`;

      // Multi-Source Cluster Summary Row if present
      let multiSourceRowHTML = "";
      if (tx.matched_sources && tx.matched_sources.length > 1) {
        const msChips = tx.matched_sources.map(ms => {
          const msName = ms.name || ms.type;
          const msColor = ms.color || (window.statementColorMap && window.statementColorMap[msName]) || '#3b82f6';
          return createSourceBadgeHTML(msName, msColor, ms.type);
        }).join("");
        multiSourceRowHTML = `
          <tr>
            <td><strong>Linked Sources</strong></td>
            <td colspan="2">${msChips}</td>
            <td><span class="status-pill status-exact">${tx.matched_sources.length} Sources Unified</span></td>
          </tr>
        `;
      }

      tbody.innerHTML = `
        ${multiSourceRowHTML}
        <tr>
          <td><strong>Source Type</strong></td>
          <td><span class="flag-chip flag-primary">${primarySrcName}</span></td>
          <td><span class="flag-chip flag-secondary">${counterSrcLabel}</span></td>
          <td><span class="status-pill status-exact">Different Sources (Passed)</span></td>
        </tr>
        <tr>
          <td><strong>UTR / Reference ID</strong></td>
          <td class="font-mono">${primaryIdVal}</td>
          <td class="font-mono">${counterpart.id || "—"}</td>
          <td><span class="status-pill status-exact">${primaryIdVal === counterpart.id ? "Exact Reference Match" : "Reference Linked"}</span></td>
        </tr>
        <tr>
          <td><strong>Reconciled Amount</strong></td>
          <td class="font-mono">${formatMoney(tx.amount)}</td>
          <td class="font-mono">${formatMoney(tx.amount)}</td>
          <td>${amtStatus}</td>
        </tr>
        <tr>
          <td><strong>Transaction Date</strong></td>
          <td>${tx.date || "—"}</td>
          <td>${tx.date || "—"}</td>
          <td>${dateStatus}</td>
        </tr>
        <tr>
          <td><strong>Description &amp; Keywords</strong></td>
          <td style="font-size:0.82rem; color:var(--text-secondary, #94a3b8);">${escapeHtml(pDesc || "—")}</td>
          <td style="font-size:0.82rem; color:var(--text-secondary, #94a3b8);">${escapeHtml(cDesc || "—")}</td>
          <td>${sharedKwBadge}</td>
        </tr>
        <tr>
          <td><strong>Rule Engine Result</strong></td>
          <td>${tx.stage ? tx.stage.toUpperCase() : "EXACT"} MATCH</td>
          <td>RECONCILED COUNTERPART</td>
          <td><span class="status-pill ${statusPillClass(tx.status)}">${getStatusLabel(tx.status)}</span></td>
        </tr>
      `;
    } else {
      // Unmatched state: Empty counterpart card & no fake data
      if (secondaryHeader) secondaryHeader.style.display = "none";
      if (secondaryParamList) secondaryParamList.style.display = "none";
      if (secondaryEmptyState) secondaryEmptyState.style.display = "flex";
      if (matrixWrap) matrixWrap.style.display = "none";
      tbody.innerHTML = "";
    }

    // 4. Find Similar Payments Button
    const btnFindSimilar = document.getElementById("btnFindSimilarPayments");
    if (btnFindSimilar) {
      btnFindSimilar.onclick = (e) => {
        e.stopPropagation();
        triggerFindSimilarPayments(tx);
      };
    }

    const btnLlmFooter = document.getElementById("btnModalLlmSmartMatch");
    if (btnLlmFooter) {
      btnLlmFooter.onclick = (e) => {
        e.stopPropagation();
        triggerModalLlmSmartMatch(tx, btnLlmFooter);
      };
    }

    // 5. Close Similar Panel Button
    const btnCloseSimilar = document.getElementById("btnCloseSimilarPanel");
    if (btnCloseSimilar) {
      btnCloseSimilar.onclick = () => {
        if (similarPanel) similarPanel.style.display = "none";
      };
    }

    // Footer status pill & action buttons
    const currentPill = document.getElementById("compareCurrentStatusPill");
    if (currentPill) {
      currentPill.textContent = `Current Status: ${getStatusLabel(tx.status).toUpperCase()}`;
    }

    const statusSelect = document.getElementById("cmpChangeStatusSelect");
    if (statusSelect) {
      statusSelect.dataset.settlementId = primaryIdVal;
      statusSelect.dataset.bankTxId = (tx.counterpart && tx.counterpart.id) || "";
      statusSelect.value = "";
    }

    modalBackdrop.style.display = "flex";
  }

  async function triggerModalLlmSmartMatch(tx, triggerBtn) {
    if (!tx) return;
    const origHtml = triggerBtn ? triggerBtn.innerHTML : "";
    if (triggerBtn) {
      triggerBtn.disabled = true;
      triggerBtn.innerHTML = '<span class="spinner"></span> Running Groq LLM...';
    }

    try {
      const primaryIdVal = tx.primary_id || tx.settlement_id || tx.utr || "";
      const desc = tx.bank_description || tx.description || tx.reason || "";
      const srcLabel = tx.source_name || tx.source_type_label || tx.source_label || "Statement Record";

      const res = await window.LedgerApi.llmSmartMatch(
        primaryIdVal,
        primaryIdVal,
        tx.amount,
        tx.date,
        desc,
        tx.source_type || "settlement",
        tx.source_name || srcLabel,
        tx.statement_id || ""
      );

      if (res && res.ok && res.found_candidate && res.best_candidate) {
        const cand = res.best_candidate;
        tx.status = "llm";
        tx.stage = "llm";
        tx.counterpart = {
          id: cand.bank_transaction_id || cand.utr || cand.id,
          source_type: cand.source_type || "bank",
          source_label: cand.statement_name || cand.source_label || "Candidate Source"
        };
        tx.evidence = {
          amount_difference: 0,
          date_difference_days: 0,
          identifier_matched: true,
          candidate_count: 1
        };
        openRecordComparisonModal(tx);
        alert(`LLM Match Confirmed! Matched with ${tx.counterpart.id} (${Math.round((res.confidence || 0.9) * 100)}% Confidence)`);
      } else {
        const reason = res && res.llm_reasoning ? res.llm_reasoning : "No high-confidence candidate found across imported sources.";
        alert(`LLM Evaluation: ${reason}`);
      }
    } catch (err) {
      alert(`LLM Smart Match error: ${err.message || err}`);
    } finally {
      if (triggerBtn) {
        triggerBtn.disabled = false;
        triggerBtn.innerHTML = origHtml;
      }
    }
  }

  async function triggerFindSimilarPayments(tx) {
    const panel = document.getElementById("cmpSimilarPaymentsPanel");
    const list = document.getElementById("cmpSimilarCandidatesList");
    if (!panel || !list) return;

    panel.style.display = "block";
    list.innerHTML = '<div style="padding: 16px; text-align: center; color: #94a3b8;"><span class="spinner"></span> Searching real transaction records across different sources...</div>';

    try {
      const res = await window.LedgerApi.getSimilarPayments(
        tx.primary_id || tx.settlement_id || tx.utr,
        tx.source_type || "bank",
        tx.amount,
        tx.date,
        tx.utr,
        tx.bank_description || tx.description || tx.reason || "",
        tx.source_name || tx.source_type_label || "",
        tx.statement_id || ""
      );

      if (!res || !res.ok || !res.candidates || res.candidates.length === 0) {
        list.innerHTML = `
          <div style="padding: 16px; text-align: center; color: #94a3b8;">
            No similar payments found in other imported sources.
            <div style="font-size:0.76rem; color:#64748b; margin-top:4px;">Rule Enforced: Only transactions from DIFFERENT sources can be compared.</div>
          </div>
        `;
        return;
      }

      list.innerHTML = res.candidates.map((cand, idx) => {
        const kwBadges = cand.matched_keywords && cand.matched_keywords.length > 0
          ? `<div style="margin-top: 4px; display: flex; align-items: center; gap: 4px; flex-wrap: wrap;">
              <span style="font-size: 0.7rem; color: #34d399; font-weight: 600;">Matched Keywords:</span>
              ${cand.matched_keywords.map(k => `<span class="flag-chip flag-success" style="background: rgba(52, 211, 153, 0.18); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.3); padding: 1px 6px; font-size: 0.68rem;">"${k}"</span>`).join("")}
            </div>`
          : "";

        return `
          <div class="similar-candidate-card">
            <div class="candidate-left-info">
              <div class="candidate-source-line">
                <span class="candidate-source-tag" style="background: ${cand.source_color || '#3b82f6'}22; color: ${cand.source_color || '#60a5fa'}; border: 1px solid ${cand.source_color || '#3b82f6'}44;">${cand.statement_name || cand.source_label}</span>
                <span class="candidate-id">${cand.id || cand.candidate_id || '—'}</span>
              </div>
              <div class="candidate-sub-line">
                Date: ${cand.date} &bull; Amount: <strong style="color:${cand.amount < 0 ? '#f87171' : '#4ade80'}">${formatMoney(cand.amount)}</strong> &bull; ${cand.description}
              </div>
              ${kwBadges}
              <div class="candidate-sub-line" style="color:#60a5fa; font-size:0.72rem; margin-top:3px;">
                ${cand.feature_diffs ? cand.feature_diffs.join(" &bull; ") : ""}
              </div>
            </div>
            <div class="candidate-right-action">
              <span class="candidate-similarity-badge">${cand.similarity_pct}% Similarity</span>
              <button type="button" class="btn-select-candidate" data-cand-index="${idx}">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>
                Compare
              </button>
            </div>
          </div>
        `;
      }).join("");

      // Bind candidate select buttons
      list.querySelectorAll(".btn-select-candidate").forEach((btn) => {
        btn.onclick = () => {
          const idx = parseInt(btn.dataset.candIndex, 10);
          const cand = res.candidates[idx];
          if (cand) {
            renderSelectedCandidateComparison(tx, cand);
            panel.style.display = "none";
          }
        };
      });
    } catch (err) {
      list.innerHTML = `<div style="padding: 16px; text-align: center; color: #f87171;">Failed to search similar payments: ${err.message || err}</div>`;
    }
  }

  function renderSelectedCandidateComparison(primaryTx, cand) {
    const secondaryHeader = document.getElementById("cmpSecondaryHeader");
    const secondaryParamList = document.getElementById("cmpSecondaryParamList");
    const secondaryEmptyState = document.getElementById("cmpSecondaryEmptyState");
    const matrixWrap = document.getElementById("cmpMatrixWrap");
    const scoreBadge = document.getElementById("compareMatchScoreBadge");
    const tbody = document.getElementById("compareTableBody");

    if (scoreBadge) {
      scoreBadge.textContent = `Potential Match / Similarity (${cand.similarity_pct}%)`;
      scoreBadge.className = "compare-match-score score-potential";
    }

    if (secondaryHeader) secondaryHeader.style.display = "flex";
    if (secondaryParamList) secondaryParamList.style.display = "flex";
    if (secondaryEmptyState) secondaryEmptyState.style.display = "none";
    if (matrixWrap) matrixWrap.style.display = "block";

    const secondaryTag = document.getElementById("cmpSecondaryTag");
    if (secondaryTag) secondaryTag.textContent = cand.source_label.toUpperCase();

    document.getElementById("cmpBankId").textContent = cand.id;
    document.getElementById("cmpBankSource").textContent = cand.source_label;
    document.getElementById("cmpBankUtr").textContent = cand.utr || cand.id;
    document.getElementById("cmpBankTxId").textContent = cand.id;
    document.getElementById("cmpBankDate").textContent = cand.date;
    document.getElementById("cmpBankAmount").textContent = formatMoney(cand.amount);
    document.getElementById("cmpBankDesc").textContent = cand.description;

    const rightViewBtn = document.getElementById("cmpRightViewSourceBtn");
    if (rightViewBtn) {
      rightViewBtn.onclick = (e) => {
        e.stopPropagation();
        findAndOpenStatementForSource(cand.source_type, cand.id);
      };
    }

    const primaryIdVal = primaryTx.primary_id || primaryTx.settlement_id || primaryTx.utr || "—";
    const primarySrcLabel = primaryTx.source_name || primaryTx.source_type_label || (primaryTx.source && primaryTx.source !== "primary" ? primaryTx.source : "Gateway Settlement");
    const candSrcLabel = cand.statement_name || cand.source_label || "Candidate Source";

    const amtDiff = Math.abs(Math.abs(primaryTx.amount || 0) - Math.abs(cand.amount || 0));
    const amtStatus = amtDiff < 0.01 ? '<span class="status-pill status-exact">Exact Amount Match</span>' : `<span class="status-pill status-tolerance">Variance: ₹${amtDiff.toFixed(2)}</span>`;

    const pDescCand = primaryTx.bank_description || primaryTx.description || primaryTx.primary_id || "";
    const cDescCand = cand.description || cand.bank_description || cand.id || "";
    const sharedKwsCand = cand.matched_keywords && cand.matched_keywords.length > 0 ? cand.matched_keywords : extractSharedKeywords(pDescCand, cDescCand);

    const sharedKwBadgeCand = sharedKwsCand.length > 0
      ? `<span class="status-pill status-exact" style="background: rgba(52, 211, 153, 0.2); color: #34d399; font-weight:600;">Shared Keywords: ${sharedKwsCand.map(escapeHtml).join(", ")}</span>`
      : `<span class="status-pill" style="opacity: 0.75; font-size:0.78rem;">Candidate Overlap (${cand.similarity_pct}%)</span>`;

    const kwRow = `
      <tr>
        <td><strong>Description &amp; Keywords</strong></td>
        <td style="font-size:0.82rem; color:var(--text-secondary, #cbd5e1);">${escapeHtml(pDescCand || "—")}</td>
        <td style="font-size:0.82rem; color:var(--text-secondary, #cbd5e1);">${escapeHtml(cDescCand || "—")}</td>
        <td>${sharedKwBadgeCand}</td>
      </tr>
    `;

    tbody.innerHTML = `
      <tr>
        <td><strong>Source Type</strong></td>
        <td><span class="flag-chip flag-primary">${primarySrcLabel}</span></td>
        <td><span class="flag-chip flag-secondary">${candSrcLabel}</span></td>
        <td><span class="status-pill status-exact">Different Sources (Passed)</span></td>
      </tr>
      <tr>
        <td><strong>UTR / Reference ID</strong></td>
        <td class="font-mono">${primaryIdVal}</td>
        <td class="font-mono">${cand.utr || cand.id}</td>
        <td><span class="status-pill status-exact">${primaryIdVal === (cand.utr || cand.id) ? "Exact Reference Match" : "Similarity Match"}</span></td>
      </tr>
      <tr>
        <td><strong>Reconciled Amount</strong></td>
        <td class="font-mono">${formatMoney(primaryTx.amount)}</td>
        <td class="font-mono">${formatMoney(cand.amount)}</td>
        <td>${amtStatus}</td>
      </tr>
      <tr>
        <td><strong>Transaction Date</strong></td>
        <td>${primaryTx.date || "—"}</td>
        <td>${cand.date}</td>
        <td><span class="status-pill status-exact">${primaryTx.date === cand.date ? "Same Date" : "Date Proximity"}</span></td>
      </tr>
      ${kwRow}
      <tr>
        <td><strong>Rule Engine Result</strong></td>
        <td>${primarySrcLabel.toUpperCase()}</td>
        <td>${candSrcLabel.toUpperCase()}</td>
        <td><span class="status-pill status-manual">Potential Candidate</span></td>
      </tr>
    `;

    const btnMatch = document.getElementById("btnMarkAsMatched");
    if (btnMatch) {
      btnMatch.dataset.settlementId = primaryIdVal;
      btnMatch.dataset.bankTxId = cand.id;
    }
  }

  function createSourceBadgeHTML(name, color, fallbackType = "bank") {
    const label = name || (fallbackType || "bank").replace(/_/g, " ").toUpperCase();
    const hex = color || (window.statementColorMap && window.statementColorMap[name]) || "#3b82f6";
    return `<span class="source-chip" style="background: ${hex}22; color: ${hex}; border: 1px solid ${hex}60; font-weight: 600; padding: 4px 10px; border-radius: 6px; display: inline-flex; align-items: center; font-size: 0.8rem;">${escapeHtml(label)}</span>`;
  }

  function renderTransactionsTable(transactions, targetBodyId = "transactionsBody", targetEmptyId = "transactionsEmpty", targetBadgeId = "txBadgeCount") {
    const body = document.getElementById(targetBodyId);
    const empty = document.getElementById(targetEmptyId);
    const badge = document.getElementById(targetBadgeId);
    if (!body) return;
    body.innerHTML = "";

    if (badge) badge.textContent = `${transactions.length} items`;

    if (!transactions || transactions.length === 0) {
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";

    transactions.forEach((tx) => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.title = "Click to view side-by-side comparison & record details";
      const amountClass = (tx.amount || 0) < 0 ? "amount-negative" : "amount-positive";
      const pillLabel = getStatusLabel(tx);
      const flagsHTML = getFeatureFlagsHTML(tx);
      const titleReason = tx.reason ? `title="${tx.reason}"` : "";

      // 1. Transaction ID of first source
      const primaryTxId = tx.id || tx.primary_id || tx.settlement_id || tx.bank_transaction_id || tx.utr || "—";

      // 2. Source Badge Chip
      const srcName = tx.source_name || tx.source_label || tx.source_type_label;
      const srcColor = tx.source_color || (window.statementColorMap && window.statementColorMap[srcName]);
      const srcPill = createSourceBadgeHTML(srcName, srcColor, tx.source_type);

      // 3. Matched With Badge
      let matchedPill = `<span class="flag-chip flag-secondary" style="opacity: 0.7;">Unmatched</span>`;
      const isReconciled = tx.status !== "unreconciled" && tx.status !== "unmatched" && tx.status !== "exception";
      if (isReconciled) {
        if (tx.matched_sources && tx.matched_sources.length > 0) {
          const chipItems = tx.matched_sources.map(s => {
            const sName = s.name || s.source_name || s.source_label;
            const sColor = s.color || s.source_color || (window.statementColorMap && window.statementColorMap[sName]);
            return createSourceBadgeHTML(sName, sColor, s.type || s.source_type);
          }).join(" ");
          matchedPill = `<div class="matched-with-wrapper" style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">${chipItems}</div>`;
        } else if (tx.counterpart && (tx.counterpart.source_name || tx.counterpart.source_label)) {
          const mName = tx.counterpart.source_name || tx.counterpart.source_label;
          const mColor = tx.counterpart.source_color || (window.statementColorMap && window.statementColorMap[mName]);
          matchedPill = `<div class="matched-with-wrapper">${createSourceBadgeHTML(mName, mColor, tx.counterpart.source_type)}</div>`;
        } else if (tx.matched_source_name) {
          const mName = tx.matched_source_name;
          const mColor = tx.matched_source_color || (window.statementColorMap && window.statementColorMap[mName]);
          matchedPill = `<div class="matched-with-wrapper">${createSourceBadgeHTML(mName, mColor, tx.matched_source_type)}</div>`;
        }
      }

      tr.innerHTML = `
        <td><code class="font-mono text-sm" style="color:var(--accent-blue, #60a5fa); font-weight:600;">${escapeHtml(primaryTxId)}</code></td>
        <td>${formatDateDDMMYYYY(tx.date)}</td>
        <td>${srcPill}</td>
        <td>${matchedPill}</td>
        <td class="${amountClass}">${formatMoney(tx.amount)}</td>
        <td>${flagsHTML}</td>
        <td><span class="status-pill ${statusPillClass(tx)}" ${titleReason}>${pillLabel}</span></td>
        <td>
          <button type="button" class="btn-ask-ai-row" title="Ask Ledger AI Agent about this transaction">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
            <span>Ask AI</span>
          </button>
        </td>
      `;

      const askBtn = tr.querySelector(".btn-ask-ai-row");
      if (askBtn) {
        askBtn.addEventListener("mousedown", (e) => e.stopPropagation());
        askBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          e.preventDefault();
          if (window.askLedgerAiAboutTx) window.askLedgerAiAboutTx(primaryTxId);
        });
      }

      tr.addEventListener("click", (e) => {
        if (e.target.closest(".btn-ask-ai-row")) return;
        openRecordComparisonModal(tx);
      });

      body.appendChild(tr);
    });
  }

  function renderExceptionsTable(exceptions) {
    const body = document.getElementById("exceptionsBody");
    const empty = document.getElementById("exceptionsEmpty");
    const badge = document.getElementById("excBadgeCount");
    if (!body) return;
    body.innerHTML = "";

    if (badge) {
      const cnt = (exceptions || []).length;
      badge.innerHTML = `<strong>${cnt}</strong> Exception${cnt === 1 ? "" : "s"} Pending`;
    }

    if (!exceptions || exceptions.length === 0) {
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";

    exceptions.forEach((ex) => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.title = "Click to view side-by-side comparison & record details";
      const amountClass = (ex.amount || 0) < 0 ? "amount-negative" : "amount-positive";
      const pillLabel = getStatusLabel(ex);
      const flagsHTML = getFeatureFlagsHTML(ex);
      const primaryTxId = ex.id || ex.primary_id || ex.settlement_id || ex.bank_transaction_id || ex.utr || "—";

      const srcName = ex.source_name || ex.source_label || ex.source_type_label;
      const srcColor = ex.source_color || (window.statementColorMap && window.statementColorMap[srcName]);
      const srcPill = createSourceBadgeHTML(srcName, srcColor, ex.source_type);

      let matchedPill = `<span class="flag-chip flag-secondary" style="opacity: 0.7;">Unmatched</span>`;

      tr.innerHTML = `
        <td><code class="font-mono text-sm" style="color:var(--accent-blue, #60a5fa); font-weight:600;">${escapeHtml(primaryTxId)}</code></td>
        <td>${formatDateDDMMYYYY(ex.date)}</td>
        <td>${srcPill}</td>
        <td>${matchedPill}</td>
        <td class="${amountClass}">${formatMoney(ex.amount)}</td>
        <td>${flagsHTML}</td>
        <td><span class="status-pill status-unmatched">UNMATCHED</span></td>
        <td>
          <button type="button" class="btn-ask-ai-row" title="Ask Ledger AI Agent about this transaction">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
            <span>Ask AI</span>
          </button>
        </td>
      `;

      const excAskBtn = tr.querySelector(".btn-ask-ai-row");
      if (excAskBtn) {
        excAskBtn.addEventListener("mousedown", (e) => e.stopPropagation());
        excAskBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          e.preventDefault();
          if (window.askLedgerAiAboutTx) window.askLedgerAiAboutTx(primaryTxId);
        });
      }

      tr.addEventListener("click", (e) => {
        if (e.target.closest(".btn-ask-ai-row")) return;
        openRecordComparisonModal(ex);
      });

      body.appendChild(tr);
    });
  }

  function renderManualReviewQueue(exceptions) {
    const container = document.getElementById("manualReviewGrid");
    const emptyEl = document.getElementById("manualReviewEmpty");
    const badgeEl = document.getElementById("manualReviewBadgeCount");
    const navBadgeEl = document.getElementById("navManualBadge");
    const hdrBadgeEl = document.getElementById("hdrManualBadge");
    const topbarBadgeEl = document.getElementById("topbarExceptionBadge");

    const items = exceptions || [];
    const pendingCount = items.length;

    if (badgeEl) badgeEl.textContent = `${pendingCount} item${pendingCount === 1 ? "" : "s"} pending`;
    if (navBadgeEl) {
      navBadgeEl.textContent = pendingCount;
      navBadgeEl.style.display = pendingCount > 0 ? "inline-block" : "none";
    }
    if (topbarBadgeEl) {
      topbarBadgeEl.textContent = pendingCount;
      topbarBadgeEl.style.display = pendingCount > 0 ? "inline-block" : "none";
    }
    if (hdrBadgeEl) {
      hdrBadgeEl.textContent = pendingCount;
      hdrBadgeEl.style.display = pendingCount > 0 ? "inline-block" : "none";
    }

    if (container) {
      container.innerHTML = "";
      container.style.display = "none";
    }
    if (emptyEl) {
      emptyEl.style.display = "none";
    }
  }

  async function handleExceptionResolution(excId, outcome, cardElement) {
    try {
      const footer = cardElement.querySelector(".review-card-footer");
      if (footer) {
        footer.innerHTML = '<span class="spinner"></span> Updating Exception Ledger & ML Feedback Loop...';
      }

      const res = await window.LedgerApi.resolveException(excId, outcome);

      if (res && res.ok) {
        stateManager.invalidate();
        const nextRunId = res.run_id;
        if (nextRunId) {
          await loadRun(nextRunId);
        } else {
          const runRes = await window.LedgerApi.getLatestReconciliation();
          if (runRes && runRes.run) {
            await loadRun(runRes.run.run_id);
          }
        }
      }
    } catch (err) {
      alert(`Resolution failed: ${err.message || err}`);
    }
  }

  async function loadRun(runId) {
    currentRunId = runId;
    const [reconRes, exceptionsRes] = await Promise.all([
      window.LedgerApi.getReconciliation(runId),
      window.LedgerApi.getExceptions(runId),
    ]);

    document.getElementById("reconcileEmptyState").style.display = "none";
    document.getElementById("reconcileResults").style.display = "flex";

    currentTransactions = reconRes.run.transactions || [];
    currentExceptions = exceptionsRes.exceptions || [];

    renderSummary(reconRes.run);
    updateTagFilterBar();
    applyTransactionFiltersAndRender();
    applyExceptionFiltersAndRender();
    renderManualReviewQueue(currentExceptions);
  }

  async function triggerAutoMatch() {
    const runBtn = document.getElementById("runReconcileBtn");
    const navBtn = document.getElementById("btnNavRunAutoMatch");
    const cyclicSvg18 = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><polyline points="21 3 21 8 16 8"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><polyline points="3 21 3 16 8 16"/></svg>';
    const cyclicSvg14 = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><polyline points="21 3 21 8 16 8"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><polyline points="3 21 3 16 8 16"/></svg>';

    if (runBtn) runBtn.disabled = true;
    if (navBtn) navBtn.disabled = true;

    if (runBtn) runBtn.innerHTML = '<span class="spinner" style="width:15px; height:15px; border-width:2px; margin-right:6px;"></span> <span>Processing Pipeline...</span>';
    if (navBtn) navBtn.innerHTML = '<span class="spinner" style="width:13px; height:13px; border-width:2px; margin-right:4px;"></span> <span>Processing...</span>';

    try {
      const result = await window.LedgerApi.runReconciliation();
      currentRunId = result.run_id;
      stateManager.invalidate();
      await loadRun(currentRunId);
    } catch (err) {
      console.warn("Auto match failed:", err);
    } finally {
      if (runBtn) {
        runBtn.disabled = false;
        runBtn.innerHTML = `${cyclicSvg18} <span>Auto Match</span>`;
      }
      if (navBtn) {
        navBtn.disabled = false;
        navBtn.innerHTML = `${cyclicSvg14} <span>Auto Match</span>`;
      }
    }
  }

  async function handleSetPrimaryStatement(statementId, triggeringEl = null) {
    if (!statementId) return;

    showNotificationToast("Setting primary statement & re-syncing pipeline...", "loading");

    const btnSetPrimary = document.getElementById("btnStmtHeaderSetPrimary");
    const btnSetPrimaryText = document.getElementById("btnStmtHeaderSetPrimaryText");
    let origText = "";
    if (btnSetPrimaryText) {
      origText = btnSetPrimaryText.textContent;
      btnSetPrimaryText.textContent = "Setting Primary...";
      btnSetPrimary?.classList.add("btn-primary-loading");
    }

    if (triggeringEl) {
      triggeringEl.classList.add("btn-primary-loading");
      if (triggeringEl.tagName === "BUTTON") triggeringEl.disabled = true;
    }

    try {
      await window.LedgerApi.setPrimaryStatement(statementId);
      await loadSidebarSources();
      await loadStatementsTable();
      if (activeStatementId) await openStatementView(activeStatementId);
      await triggerAutoMatch();
      showNotificationToast("Primary statement set & reconciliation updated!", "success");
    } catch (err) {
      console.error("Error setting primary statement:", err);
      showNotificationToast("Failed to update primary statement. Please try again.", "error");
    } finally {
      if (btnSetPrimaryText) {
        btnSetPrimaryText.textContent = origText || "Primary Source";
        btnSetPrimary?.classList.remove("btn-primary-loading");
      }
      if (triggeringEl) {
        triggeringEl.classList.remove("btn-primary-loading");
        if (triggeringEl.tagName === "BUTTON") triggeringEl.disabled = false;
      }
    }
  }

  function initReconcile() {
    const runBtn = document.getElementById("runReconcileBtn");
    const navBtn = document.getElementById("btnNavRunAutoMatch");
    const closeBtn = document.getElementById("closePeriodBtn");

    const cyclicSvg18 = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><polyline points="21 3 21 8 16 8"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><polyline points="3 21 3 16 8 16"/></svg>';
    const cyclicSvg14 = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><polyline points="21 3 21 8 16 8"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><polyline points="3 21 3 16 8 16"/></svg>';

    if (runBtn) {
      runBtn.addEventListener("click", async () => {
        runBtn.disabled = true;
        if (navBtn) navBtn.disabled = true;

        runBtn.innerHTML = '<span class="spinner" style="width:15px; height:15px; border-width:2px; margin-right:6px;"></span> <span>Processing Pipeline...</span>';
        if (navBtn) navBtn.innerHTML = '<span class="spinner" style="width:13px; height:13px; border-width:2px; margin-right:4px;"></span> <span>Processing...</span>';

        try {
          const result = await window.LedgerApi.runReconciliation();
          currentRunId = result.run_id;
          stateManager.invalidate();
          await loadRun(currentRunId);
        } catch (err) {
          const detail = (err && err.message) ? err.message : String(err || "Reconciliation run failed.");
          alert(`Reconciliation Error:\n\n${detail}`);
        } finally {
          runBtn.disabled = false;
          if (navBtn) navBtn.disabled = false;
          runBtn.innerHTML = `${cyclicSvg18} <span>Auto Match</span>`;
          if (navBtn) navBtn.innerHTML = `${cyclicSvg14} <span>Auto Match</span>`;
        }
      });
    }

    closeBtn.addEventListener("click", async () => {
      if (!currentRunId) return;
      closeBtn.disabled = true;
      try {
        const result = await window.LedgerApi.closePeriod(currentRunId);
        stateManager.invalidate();
        renderSummary(result.run);
      } catch (err) {
        const detail = (err && err.message) ? err.message : String(err || "Could not close period.");
        alert(`Close Period Error:\n\n${detail}`);
        closeBtn.disabled = false;
      }
    });
  }

  async function hydrateExistingRun() {
    try {
      const latest = await window.LedgerApi.getLatestReconciliation();
      if (latest && latest.run) {
        currentRunId = latest.run.run_id;
        await loadRun(currentRunId);
      }
    } catch (_) {
      // Leave empty state showing
    }
  }

  function initCompareModal() {
    const backdrop = document.getElementById("compareModalBackdrop");
    const closeBtn = document.getElementById("closeCompareModalBtn");
    const statusSelect = document.getElementById("cmpChangeStatusSelect");

    if (closeBtn && backdrop) {
      closeBtn.addEventListener("click", () => {
        backdrop.style.display = "none";
      });
      backdrop.addEventListener("click", (e) => {
        if (e.target === backdrop) backdrop.style.display = "none";
      });
    }

    if (statusSelect) {
      statusSelect.addEventListener("change", async (e) => {
        const targetStatus = e.target.value;
        const sId = statusSelect.dataset.settlementId;
        const bId = statusSelect.dataset.bankTxId;
        if (!sId || !targetStatus) return;

        statusSelect.disabled = true;
        try {
          const res = await window.LedgerApi.overrideStatus(sId, bId, targetStatus);
          if (res && res.ok && res.run_id) {
            if (backdrop) backdrop.style.display = "none";
            stateManager.invalidate();
            await loadRun(res.run_id);
          }
        } catch (err) {
          alert(`Failed to update status to ${targetStatus.toUpperCase()}: ${err.message || err}`);
        } finally {
          statusSelect.disabled = false;
          statusSelect.value = "";
        }
      });
    }

    document.addEventListener("click", (e) => {
      const viewBtn = e.target.closest(".btn-inline-view-source");
      if (viewBtn) {
        e.stopPropagation();
        const stype = viewBtn.dataset.source;
        const searchId = viewBtn.dataset.id;
        findAndOpenStatementForSource(stype, searchId);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    initSubTabs();
    initSidebarToggle();
    initSidebarResizer();
    initUploads();
    initAppendButton();
    initStatementToolbarButtons();
    initCollapsibleSections();
    initTableSorting();
    initFilterInputs();
    initReconcile();
    initCompareModal();

    let hasData = false;
    try {
      const res = await window.LedgerApi.getStatements();
      const stmts = res.statements || [];
      if (stmts.length > 0) {
        hasData = true;
      }
    } catch (_) { }

    loadSidebarSources();
    loadStatementsTable();
    hydrateExistingRun();

    if (hasData) {
      activateSub("sub-overview");
    } else {
      activateSub("sub-upload-bank");
    }

    if (window.location.search) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  });
})();
