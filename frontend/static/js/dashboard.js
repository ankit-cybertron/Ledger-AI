/**
 * dashboard.js
 *
 * Restored original clean dashboard interaction flow while integrating backend
 * statement store, 3-dot menus, incremental updates, and dynamic data tables.
 */

(function () {
  "use strict";

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

  function getDotClass(sourceType) {
    if (sourceType === "razorpay") return "dot-red";
    if (sourceType === "orders") return "dot-amber";
    return "dot-blue";
  }

  // ------------------------------------------------------------------
  // Sub-tabs: Import Bank / Razorpay / Orders / Auto-Match / Close / Stmt View
  // ------------------------------------------------------------------

  function activateSub(subId) {
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === subId));
    document.querySelectorAll(".sub-tab").forEach((t) => t.classList.toggle("active", t.dataset.sub === subId));
    document.querySelectorAll(".source-item").forEach((s) => s.classList.toggle("active", s.dataset.sub === subId));

    const navCurrent = document.getElementById("navCurrentPeriod");
    if (navCurrent) navCurrent.classList.toggle("active", subId === "sub-current-period");

    const navRecon = document.getElementById("navReconciliation");
    if (navRecon) navRecon.classList.toggle("active", subId === "sub-reconcile");

    const navManual = document.getElementById("navManualReview");
    if (navManual) navManual.classList.toggle("active", subId === "sub-manual-review");

    const navClose = document.getElementById("navClosePeriod");
    if (navClose) navClose.classList.toggle("active", subId === "sub-close");
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
    if (navCurrent) navCurrent.addEventListener("click", () => activateSub("sub-current-period"));

    const navReconciliation = document.getElementById("navReconciliation");
    if (navReconciliation) navReconciliation.addEventListener("click", () => activateSub("sub-reconcile"));

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

    const cardCountManual = document.querySelector(".count-card.manual");
    if (cardCountManual) {
      cardCountManual.style.cursor = "pointer";
      cardCountManual.addEventListener("click", () => activateSub("sub-manual-review"));
    }

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

    const clearBtn = document.getElementById("btnClearAllData");
    if (clearBtn) {
      clearBtn.addEventListener("click", async () => {
        const confirmed = confirm(
          "⚠️ Are you sure you want to clear ALL imported statement data and reconciliation results?\n\nThis action cannot be undone."
        );
        if (!confirmed) return;

        clearBtn.disabled = true;
        clearBtn.innerHTML = '<span class="spinner"></span> Clearing...';

        try {
          const res = await fetch("/api/data/clear", { method: "POST" });
          const data = await res.json();
          if (data.ok) {
            alert("All data cleared successfully.");
            window.location.reload();
          } else {
            alert(data.error || "Failed to clear data.");
          }
        } catch (err) {
          alert("Error clearing data: " + err.message);
        } finally {
          clearBtn.disabled = false;
          clearBtn.innerHTML = `
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="subnav-icon"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
            <span class="label-text">Clear All Data</span>
          `;
        }
      });
    }
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
  // Sidebar Sources List & 3-Dots Action Menu
  // ------------------------------------------------------------------

  async function loadSidebarSources() {
    const listEl = document.getElementById("sourceList");
    if (!listEl) return;

    try {
      const res = await window.LedgerApi.getStatements();
      const statements = res.statements || [];

      listEl.innerHTML = "";

      if (statements.length === 0) {
        listEl.appendChild(el('<li class="sidebar-empty">No statements imported yet</li>'));
        renderExecutiveSources([]);
        return;
      }

      statements.forEach((stmt) => renderSourceListItem(stmt, listEl));
      renderExecutiveSources(statements);
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
    statements.forEach((stmt) => {
      const dotColor = stmt.color || (stmt.source_type === "razorpay" ? "#f04f4f" : (stmt.source_type === "orders" ? "#e0b054" : "#6f89ff"));
      const rows = stmt.row_count || 0;
      totalRows += rows;

      const item = el(`
        <div class="cp-source-item">
          <span class="cp-dot" style="background-color: ${dotColor}; box-shadow: 0 0 6px ${dotColor}80;"></span>
          <span class="cp-source-name">${stmt.name}</span>
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
    } catch (_) {}
  }

  function renderSourceListItem(stmt, listEl) {
    const dotColor = stmt.color || (stmt.source_type === "razorpay" ? "#f04f4f" : (stmt.source_type === "orders" ? "#e0b054" : "#6f89ff"));
    const itemNode = el(`
      <li class="source-item ${stmt.id === activeStatementId ? "active" : ""}" data-id="${stmt.id}">
        <span class="source-dot" style="background-color: ${dotColor}; box-shadow: 0 0 6px ${dotColor}80;"></span>
        <span class="label-text" title="${stmt.name}">${stmt.name}</span>
        <div class="stmt-menu-wrapper">
          <button type="button" class="stmt-dots-btn" aria-label="Options" title="Options">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/><circle cx="5" cy="12" r="1.5"/></svg>
          </button>
          <div class="stmt-dropdown">
            <button type="button" class="dropdown-opt opt-view">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
              View Entries
            </button>
            <button type="button" class="dropdown-opt opt-append">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6"/><path d="M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
              Update
            </button>
            <button type="button" class="dropdown-opt opt-rename">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              Rename
            </button>
            <button type="button" class="dropdown-opt opt-delete danger">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              Delete
            </button>
          </div>
        </div>
      </li>
    `);

    // Click source item -> view statement details table
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

    // Dropdown actions
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
        if (activeStatementId === stmt.id) {
          activateSub("sub-upload-bank");
          document.getElementById("subTabStatementView").style.display = "none";
          activeStatementId = null;
        }
        await loadSidebarSources();
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
    } else if (chipType === "card") {
      sourceType = "bank";
      label = "Card";
    } else if (chipType === "upi") {
      sourceType = "bank";
      label = "UPI";
    } else if (chipType === "others") {
      const customInput = document.getElementById("custom-type-input");
      const val = customInput ? customInput.value.trim() : "";
      label = val || "Others";
      sourceType = "bank";
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

  function initDropzone(dropzoneEl) {
    const source = dropzoneEl.dataset.source;
    const input = document.getElementById(dropzoneEl.dataset.input);
    const importBtn = document.querySelector(`[data-import="${source}"]`);
    const nameInput = document.getElementById(`name-${source}`);
    let pendingFile = null;

    const handleFile = (file) => {
      if (!file) return;
      const ext = file.name.split(".").pop().toLowerCase();
      if (!["csv", "xlsx", "pdf"].includes(ext)) {
        setStatus(source, "Unsupported file type — please use .csv, .xlsx, or .pdf.", "error");
        return;
      }
      pendingFile = file;
      importBtn.disabled = false;
      if (nameInput && !nameInput.value.trim()) {
        nameInput.value = file.name.replace(/\.[^/.]+$/, "").replace(/_/g, " ").toUpperCase();
      }
      setStatus(source, `Ready to import: ${file.name}`, null);
    };

    dropzoneEl.addEventListener("click", () => input.click());
    input.addEventListener("change", (e) => handleFile(e.target.files[0]));

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
      const file = e.dataTransfer.files[0];
      handleFile(file);
    });

    importBtn.addEventListener("click", async () => {
      if (!pendingFile) return;
      importBtn.disabled = true;
      setStatus(source, "Importing statement into database…", "loading");
      startPipelineMonitoring();

      const name = nameInput ? nameInput.value.trim() : "";
      const { sourceType, label } = getSelectedTypeInfo();
      const color = getSelectedColor();
      const rulesEl = document.getElementById("rules-input");
      const rules = rulesEl ? rulesEl.value.trim() : "";

      try {
        const result = await window.LedgerApi.importStatement(pendingFile, name, sourceType, color, label, rules);
        const stmt = result.statement || {};
        setStatus(source, `Successfully imported "${stmt.name || result.filename}" (${stmt.row_count || 0} rows).`, "success");
        
        pendingFile = null;
        input.value = "";
        if (nameInput) nameInput.value = "";
        if (rulesEl) rulesEl.value = "";

        // Final status pull to ensure 100% progress and terminal log completion
        await pollPipelineStatus();
        stopPipelineMonitoring();

        await loadSidebarSources();
        if (stmt.id) {
          openStatementView(stmt.id);
        }
      } catch (err) {
        stopPipelineMonitoring();
        const message = err instanceof window.ApiError ? err.message : "Upload failed. Please try again.";
        setStatus(source, message, "error");
        importBtn.disabled = false;
      }
    });
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

      if (stageEl && res.stage) stageEl.textContent = res.stage;
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
    if (stageEl) stageEl.textContent = "Initializing Pipeline Engine...";
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

  async function openStatementView(statementId) {
    activeStatementId = statementId;
    const subTabStatementView = document.getElementById("subTabStatementView");
    if (subTabStatementView) subTabStatementView.style.display = "inline-flex";

    activateSub("sub-statement-view");
    await loadSidebarSources();

    try {
      const res = await window.LedgerApi.getStatementDetail(statementId);
      const stmt = res.statement;

      document.getElementById("stmtViewTitle").textContent = stmt.name;
      document.getElementById("stmtViewTypeBadge").textContent = stmt.source_type.toUpperCase();
      document.getElementById("stmtViewCountBadge").textContent = `${stmt.row_count} rows`;

      renderStatementRows(stmt.rows || []);
    } catch (err) {
      alert("Could not load statement details.");
    }
  }

  function renderStatementRows(rows) {
    const headEl = document.getElementById("stmtTableHead");
    const bodyEl = document.getElementById("stmtTableBody");
    headEl.innerHTML = "";
    bodyEl.innerHTML = "";

    if (!rows || rows.length === 0) {
      bodyEl.innerHTML = '<tr><td colspan="6" class="empty-state">No rows found in this statement</td></tr>';
      return;
    }

    const columns = Object.keys(rows[0]);
    
    // Render Header
    const headRow = document.createElement("tr");
    columns.forEach((col) => {
      const th = document.createElement("th");
      th.textContent = col.replace(/_/g, " ").toUpperCase();
      headRow.appendChild(th);
    });
    headEl.appendChild(headRow);

    // Render Rows
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      columns.forEach((col) => {
        const td = document.createElement("td");
        const val = row[col];
        td.textContent = val != null ? String(val) : "";
        if (col.toLowerCase().includes("amount") || col.toLowerCase().includes("debit") || col.toLowerCase().includes("credit")) {
          const num = Number(val);
          if (!isNaN(num) && val !== "" && val !== null) {
            if (num < 0) {
              td.classList.add("amount-negative");
              td.textContent = formatMoney(num, true);
            } else if (num > 0) {
              td.classList.add("amount-positive");
              td.textContent = formatMoney(num, true);
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

  // ------------------------------------------------------------------
  // Interactive Filters, Sorting & Collapsible Section Logic
  // ------------------------------------------------------------------

  let currentTransactions = [];
  let currentExceptions = [];
  let txSortKey = "date";
  let txSortAsc = false;
  let excSortKey = "date";
  let excSortAsc = false;

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

    if (st === "auto" || st === "matched" || st === "exact" || st === "tolerance") {
      tags.push("auto");
    } else if (st === "manual") {
      tags.push("manual");
    } else if (st === "llm") {
      tags.push("llm");
    } else if (st === "ml" || st === "review") {
      tags.push("ml");
    } else if (st === "unmatched" || st === "unreconciled" || st === "exception") {
      tags.push("unmatched");
    }

    const ev = tx.evidence || {};
    if (ev.identifier_matched) {
      tags.push("utr_match");
    } else if (st === "llm" || st === "ml" || st === "manual" || st === "unmatched" || st === "exception") {
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
    auto: { label: "Auto", priority: 2 },
    unmatched: { label: "Unmatched", priority: 3 },
    manual: { label: "Manual", priority: 4 },
    llm: { label: "LLM", priority: 5 },
    ml: { label: "ML", priority: 6 },
    utr_mismatch: { label: "⚠️ UTR Mismatch", priority: 7 },
    utr_match: { label: "✓ UTR Match", priority: 8 },
    date_gap: { label: "📅 Date Gap", priority: 9 },
    amt_diff: { label: "💰 Amt Diff", priority: 10 },
    split_txn: { label: "🔀 Split Txn", priority: 11 },
    fee_aware: { label: "🏷️ Fee Aware", priority: 12 },
  };

  function updateTagFilterBar() {
    const container = document.getElementById("txTagFilterBar");
    if (!container) return;

    const tagCounts = {};
    Object.keys(TAG_METADATA).forEach((id) => (tagCounts[id] = 0));

    currentTransactions.forEach((tx) => {
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
      let valA = a[txSortKey] ?? "";
      let valB = b[txSortKey] ?? "";
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

  function applyExceptionFiltersAndRender() {
    let list = [...currentExceptions];
    const q = (document.getElementById("excSearchInput")?.value || "").toLowerCase().trim();

    if (q) {
      list = list.filter((ex) => {
        const d = (ex.date || "").toLowerCase();
        const desc = (ex.description || "").toLowerCase();
        const s = (ex.source || "").toLowerCase();
        const r = (ex.reason || "").toLowerCase();
        const a = String(ex.amount || "");
        return d.includes(q) || desc.includes(q) || s.includes(q) || r.includes(q) || a.includes(q);
      });
    }

    // Sort list
    list.sort((a, b) => {
      let valA = a[excSortKey] ?? "";
      let valB = b[excSortKey] ?? "";
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

    renderExceptionsTable(list);
  }

  function renderSummary(run) {
    const s = run.summary || {};
    const total = s.total_transactions || 0;
    const auto = s.auto_matched || 0;
    const llmCount = s.llm_matched || 0;
    const manual = s.manual_matched || 0;
    const unreconciled = s.unreconciled || 0;
    const percent = s.percent_reconciled != null ? s.percent_reconciled : (s.reconciled_percent != null ? s.reconciled_percent : 0);

    document.getElementById("periodBadge").textContent = run.period_label || "—";
    document.getElementById("periodBadge").classList.toggle("badge-closed", !!run.closed);
    document.getElementById("closePeriodBtn").textContent = run.closed ? "Period Closed ✓" : "Close Period";
    document.getElementById("closePeriodBtn").disabled = !!run.closed;

    const cpCloseBtn = document.getElementById("cpClosePeriodBtn");
    if (cpCloseBtn) {
      cpCloseBtn.textContent = run.closed ? "Period Closed ✓" : "Close Period";
      cpCloseBtn.disabled = !!run.closed;
    }

    document.getElementById("progressLabel").textContent = `${percent.toFixed ? percent.toFixed(1) : percent}% Reconciled`;
    document.getElementById("progressFraction").textContent = `${auto + llmCount + manual}/${total}`;

    const pct = (n) => (total > 0 ? (n / total) * 100 : 0);
    document.getElementById("segAuto").style.width = `${pct(auto)}%`;
    document.getElementById("segManual").style.width = `${pct(manual + llmCount)}%`;
    document.getElementById("segUnreconciled").style.width = `${pct(unreconciled)}%`;

    document.getElementById("statBeginning").textContent = formatMoney(s.beginning_balance);
    document.getElementById("statPayments").textContent = formatMoney(s.payments_total);
    document.getElementById("statDeposits").textContent = formatMoney(s.deposits_total);

    const varianceEl = document.getElementById("statVariance");
    varianceEl.textContent = formatMoney(s.variance);
    varianceEl.className = (s.variance || 0) === 0 ? "variance-zero" : "variance-negative";

    document.getElementById("countAuto").textContent = auto;
    const llmEl = document.getElementById("countLlm");
    if (llmEl) llmEl.textContent = llmCount;

    document.getElementById("countManual").textContent = manual;
    document.getElementById("countUnreconciled").textContent = unreconciled;

    // Executive Overview (Current Period) Updates
    const cpSubtitle = document.getElementById("cpSubtitle");
    if (cpSubtitle) cpSubtitle.textContent = `Bank reconciliation for ${run.period_label || "July 2026"}`;
    const cpPeriodBadge = document.getElementById("cpPeriodBadge");
    if (cpPeriodBadge) cpPeriodBadge.textContent = run.period_label || "Jul 2026";

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

    loadRecentRuns();
  }

  function statusPillClass(status) {
    const s = (status || "").toLowerCase().trim();
    if (s === "auto" || s === "matched" || s === "exact" || s === "tolerance") return "status-auto";
    if (s === "manual") return "status-manual";
    if (s === "llm") return "status-llm";
    if (s === "ml" || s === "review") return "status-ml";
    if (s === "unmatched" || s === "unreconciled" || s === "exception") return "status-unmatched";
    return "status-auto";
  }

  function getStatusLabel(status) {
    const s = (status || "").toLowerCase().trim();
    if (s === "auto" || s === "matched" || s === "exact" || s === "tolerance") return "Auto";
    if (s === "manual") return "Manual";
    if (s === "llm") return "LLM";
    if (s === "ml" || s === "review") return "ML";
    if (s === "unmatched" || s === "unreconciled" || s === "exception") return "Unmatched";
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function getFeatureFlagsHTML(tx) {
    const flags = [];
    const ev = tx.evidence || {};
    const st = (tx.status || "").toLowerCase().trim();

    // 1. UTR Match vs UTR Mismatch
    if (ev.identifier_matched) {
      flags.push({ label: "✓ UTR Match", type: "success" });
    } else if (st === "llm" || st === "ml" || st === "manual" || st === "unmatched" || st === "exception") {
      flags.push({ label: "⚠️ UTR Mismatch", type: "warning" });
    }

    // 2. Date Gap Tolerance
    const dateDiff = ev.date_difference_days || 0;
    if (dateDiff > 0) {
      flags.push({ label: `📅 Date Gap (+${dateDiff}d)`, type: "info" });
    }

    // 3. Amount Difference
    const amtDiff = Math.abs(ev.amount_difference !== undefined ? ev.amount_difference : 0);
    if (amtDiff > 0.01) {
      flags.push({ label: `💰 Amt Diff (${formatMoney(amtDiff)})`, type: "amber" });
    }

    // 4. Split Transactions
    if (tx.is_split || ev.is_split || (tx.stage && tx.stage.includes("split")) || (ev.candidate_count && ev.candidate_count > 1 && !ev.identifier_matched)) {
      flags.push({ label: "🔀 Split Txn", type: "purple" });
    }

    // 5. Fee Aware
    if (tx.fee_aware || (tx.reason && tx.reason.toLowerCase().includes("fee"))) {
      flags.push({ label: "🏷️ Fee Aware", type: "cyan" });
    }

    if (flags.length === 0) {
      flags.push({ label: "Exact Match", type: "success" });
    }

    return `<div class="flags-cell">${flags.map(f => `<span class="flag-chip flag-${f.type}">${f.label}</span>`).join("")}</div>`;
  }

  function renderTransactionsTable(transactions) {
    const body = document.getElementById("transactionsBody");
    const empty = document.getElementById("transactionsEmpty");
    const badge = document.getElementById("txBadgeCount");
    body.innerHTML = "";

    if (badge) badge.textContent = `${transactions.length} items`;

    if (!transactions || transactions.length === 0) {
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";

    transactions.forEach((tx) => {
      const tr = document.createElement("tr");
      tr.className = "expandable-row";
      const amountClass = (tx.amount || 0) < 0 ? "amount-negative" : "amount-positive";
      const pillLabel = getStatusLabel(tx.status);
      const flagsHTML = getFeatureFlagsHTML(tx);
      const titleReason = tx.reason ? `title="${tx.reason}"` : "";
      const descText = tx.bank_description || tx.description || "Transaction Record";

      tr.innerHTML = `
        <td><span class="row-expand-icon">▸</span> ${tx.date ?? "—"}</td>
        <td class="desc">${descText}</td>
        <td><code class="gl-code">${tx.gl_description ?? tx.stage ?? "—"}</code></td>
        <td class="${amountClass}">${formatMoney(tx.amount)}</td>
        <td>${flagsHTML}</td>
        <td><span class="status-pill ${statusPillClass(tx.status)}" ${titleReason}>${pillLabel}</span></td>
      `;

      const detailTr = document.createElement("tr");
      detailTr.className = "detail-row";
      detailTr.style.display = "none";
      const confPct = Math.round((tx.confidence || 1.0) * 100);

      const ev = tx.evidence || {};
      const amtDiffVal = ev.amount_difference !== undefined ? ev.amount_difference : 0;
      const amtDiffText = formatMoney(amtDiffVal);
      const dateDiffText = ev.date_difference_days !== undefined ? `${ev.date_difference_days} day(s)` : "0 days";
      const idMatchText = ev.identifier_matched ? "✓ UTR / Order ID Matched" : "Fuzzy / Similarity Match";

      const settlementIdText = tx.settlement_id || tx.gl_description || "—";
      const bankRefText = tx.bank_transaction_id || tx.bank_description || "—";
      const stageName = (tx.stage || "exact").toUpperCase();
      const resolvedByAgent = (tx.resolved_by || `${stageName.toLowerCase()}_matcher`).replace(/_/g, " ");

      detailTr.innerHTML = `
        <td colspan="6">
          <div class="row-expansion-card">
            <div class="expansion-header">
              <div class="expansion-title-group">
                <span class="expansion-stage-badge">${stageName} STAGE</span>
                <h4 class="expansion-title">${descText}</h4>
              </div>
              <div class="expansion-conf-badge">
                <span class="conf-dot"></span> ${confPct}% Confidence Match
              </div>
            </div>

            <div class="matched-sources-bar">
              <div class="source-match-pill">
                <span class="source-lbl">SETTLEMENT RECORD</span>
                <span class="source-val font-mono">${settlementIdText}</span>
              </div>
              <div class="source-match-arrow">➔</div>
              <div class="source-match-pill">
                <span class="source-lbl">BANK TRANSACTION / UTR</span>
                <span class="source-val font-mono">${bankRefText}</span>
              </div>
              <div class="source-match-arrow">➔</div>
              <div class="source-match-pill">
                <span class="source-lbl">MATCHED ENGINE</span>
                <span class="source-val font-mono">${resolvedByAgent}</span>
              </div>
            </div>

            <div class="expansion-grid">
              <div class="expansion-item">
                <span class="lbl">Reference / Settlement ID</span>
                <span class="val font-mono">${settlementIdText}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Bank UTR / Ref ID</span>
                <span class="val font-mono">${tx.bank_transaction_id || "—"}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Transaction Date</span>
                <span class="val">${tx.date || "—"}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Reconciled Amount</span>
                <span class="val font-mono ${amountClass}">${formatMoney(tx.amount)}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Amount Difference</span>
                <span class="val font-mono">${amtDiffText}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Date Gap Tolerance</span>
                <span class="val">${dateDiffText}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Identifier Status</span>
                <span class="val" style="color:#6fe0a1; font-weight:600;">${idMatchText}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Match Category</span>
                <span class="val val-match-category" style="color:var(--accent-2); font-weight:600;">${(tx.status || "auto").toUpperCase()}</span>
              </div>
              <div class="expansion-item full-width">
                <span class="lbl">Matching Reason & Audit Trail</span>
                <div class="reason-callout val-reason-callout">${tx.reason || "Matched deterministically by rule engine."}</div>
              </div>
            </div>

            <div class="expansion-action-toolbar">
              <button type="button" class="btn-expansion-action btn-rematch-llm">
                <svg class="btn-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.912 5.813a2 2 0 001.275 1.275L21 12l-5.813 1.912a2 2 0 00-1.275 1.275L12 21l-1.912-5.813a2 2 0 00-1.275-1.275L3 12l5.813-1.912a2 2 0 001.275-1.275L12 3z"/></svg>
                <span>Trigger LLM Match</span>
              </button>
              <button type="button" class="btn-expansion-action btn-add-manual">
                <svg class="btn-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22v-7"/></svg>
                <span>Add to Manual Review</span>
              </button>
            </div>
          </div>
        </td>
      `;

      const llmBtn = detailTr.querySelector(".btn-rematch-llm");
      const manualBtn = detailTr.querySelector(".btn-add-manual");

      if (llmBtn) {
        llmBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          llmBtn.disabled = true;
          const origHtml = llmBtn.innerHTML;
          llmBtn.innerHTML = '<span class="spinner"></span> Running Groq LLM...';
          try {
            const res = await window.LedgerApi.rematchLlm(settlementIdText, tx.bank_transaction_id, tx.amount);
            if (res && res.ok) {
              // Update elements in-place without closing the dropdown!
              const stageBadge = detailTr.querySelector(".expansion-stage-badge");
              if (stageBadge) stageBadge.textContent = "LLM STAGE";

              const confBadge = detailTr.querySelector(".expansion-conf-badge");
              if (confBadge) {
                const confPctNew = Math.round((res.confidence || 0.92) * 100);
                confBadge.innerHTML = `<span class="conf-dot"></span> ${confPctNew}% Confidence Match`;
              }

              const engineVal = detailTr.querySelectorAll(".source-match-pill .source-val");
              if (engineVal && engineVal.length >= 3) {
                engineVal[2].textContent = res.resolved_by || "llm reviewer";
              }

              const categoryVal = detailTr.querySelector(".val-match-category");
              if (categoryVal) categoryVal.textContent = "LLM";

              const reasonBox = detailTr.querySelector(".val-reason-callout");
              if (reasonBox) {
                reasonBox.textContent = res.reason || "LLM evaluated candidate match with high confidence.";
                reasonBox.classList.add("updated-glow");
                setTimeout(() => reasonBox.classList.remove("updated-glow"), 2500);
              }

              // Update main row status pill
              const pill = tr.querySelector(".status-pill");
              if (pill) {
                pill.textContent = "✨ LLM";
                pill.className = "status-pill status-llm";
              }

              tx.status = "llm";
              tx.stage = "llm";
              tx.confidence = res.confidence;
              tx.reason = res.reason;
            }
          } catch (err) {
            alert(`LLM Rematch failed: ${err.message || err}`);
          } finally {
            llmBtn.disabled = false;
            llmBtn.innerHTML = origHtml;
          }
        });
      }

      if (manualBtn) {
        manualBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          manualBtn.disabled = true;
          const origHtml = manualBtn.innerHTML;
          manualBtn.innerHTML = '<span class="spinner"></span> Moving to Manual Review...';
          try {
            const res = await window.LedgerApi.flagManual(settlementIdText, "Flagged by reviewer from transaction dropdown.", tx.bank_transaction_id, tx.amount);
            if (res && res.ok && res.run_id) {
              await loadRun(res.run_id);
            }
          } catch (err) {
            alert(`Failed to add to Manual Review: ${err.message || err}`);
          } finally {
            manualBtn.disabled = false;
            manualBtn.innerHTML = origHtml;
          }
        });
      }

      tr.addEventListener("click", () => {
        const isExpanded = detailTr.style.display !== "none";
        const icon = tr.querySelector(".row-expand-icon");
        if (isExpanded) {
          detailTr.style.display = "none";
          tr.classList.remove("row-expanded");
          if (icon) icon.textContent = "▸";
        } else {
          detailTr.style.display = "table-row";
          tr.classList.add("row-expanded");
          if (icon) icon.textContent = "▾";
        }
      });

      body.appendChild(tr);
      body.appendChild(detailTr);
    });
  }

  function renderExceptionsTable(exceptions) {
    const body = document.getElementById("exceptionsBody");
    const empty = document.getElementById("exceptionsEmpty");
    const badge = document.getElementById("excBadgeCount");
    body.innerHTML = "";

    if (badge) badge.textContent = `${exceptions.length} items`;

    if (!exceptions || exceptions.length === 0) {
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";

    exceptions.forEach((ex) => {
      const tr = document.createElement("tr");
      tr.className = "expandable-row";
      const amountClass = (ex.amount || 0) < 0 ? "amount-negative" : "amount-positive";
      const descText = ex.description || ex.settlement_id || "Unresolved Transaction Exception";

      tr.innerHTML = `
        <td><span class="row-expand-icon">▸</span> ${ex.date ?? "—"}</td>
        <td class="desc">${descText}</td>
        <td><code class="gl-code">${ex.source ?? "Reconciler"}</code></td>
        <td class="${amountClass}">${formatMoney(ex.amount)}</td>
        <td>${ex.reason ?? "Manual review required"}</td>
      `;

      const detailTr = document.createElement("tr");
      detailTr.className = "detail-row";
      detailTr.style.display = "none";

      detailTr.innerHTML = `
        <td colspan="5">
          <div class="row-expansion-card exception-expansion">
            <div class="expansion-header">
              <div class="expansion-title-group">
                <span class="expansion-stage-badge status-exception-badge">EXCEPTION FLAG</span>
                <h4 class="expansion-title">${descText}</h4>
              </div>
              <div class="expansion-conf-badge exc-badge">
                Priority: ${ex.priority || "High"}
              </div>
            </div>
            <div class="expansion-grid">
              <div class="expansion-item">
                <span class="lbl">Source Ledger</span>
                <span class="val font-mono">${ex.source || "Settlement"}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Exception Date</span>
                <span class="val">${ex.date || "—"}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Amount</span>
                <span class="val font-mono ${amountClass}">${formatMoney(ex.amount)}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Exception ID / Reference</span>
                <span class="val font-mono">${ex.exception_id || ex.settlement_id || "—"}</span>
              </div>
              <div class="expansion-item full-width">
                <span class="lbl">Audit Exception Detail</span>
                <div class="reason-callout exception-callout">${ex.reason || "No deterministic or ML candidate resolved this settlement."}</div>
              </div>
            </div>
          </div>
        </td>
      `;

      tr.addEventListener("click", () => {
        const isExpanded = detailTr.style.display !== "none";
        const icon = tr.querySelector(".row-expand-icon");
        if (isExpanded) {
          detailTr.style.display = "none";
          tr.classList.remove("row-expanded");
          if (icon) icon.textContent = "▸";
        } else {
          detailTr.style.display = "table-row";
          tr.classList.add("row-expanded");
          if (icon) icon.textContent = "▾";
        }
      });

      body.appendChild(tr);
      body.appendChild(detailTr);
    });
  }

  function renderManualReviewQueue(exceptions) {
    const container = document.getElementById("manualReviewGrid");
    const emptyEl = document.getElementById("manualReviewEmpty");
    const badgeEl = document.getElementById("manualReviewBadgeCount");
    const navBadgeEl = document.getElementById("navManualBadge");
    const hdrBadgeEl = document.getElementById("hdrManualBadge");

    if (!container) return;
    container.innerHTML = "";

    const openItems = (exceptions || []).filter(
      (ex) => (ex.resolution_status || "open").toLowerCase() === "open"
    );

    const pendingCount = openItems.length;
    if (badgeEl) badgeEl.textContent = `${pendingCount} item${pendingCount === 1 ? "" : "s"} pending`;
    if (navBadgeEl) {
      navBadgeEl.textContent = pendingCount;
      navBadgeEl.style.display = pendingCount > 0 ? "inline-block" : "none";
    }
    if (hdrBadgeEl) {
      hdrBadgeEl.textContent = pendingCount;
      hdrBadgeEl.style.display = pendingCount > 0 ? "inline-block" : "none";
    }

    if (!openItems || openItems.length === 0) {
      if (emptyEl) emptyEl.style.display = "block";
      return;
    }

    if (emptyEl) emptyEl.style.display = "none";

    openItems.forEach((ex) => {
      const card = document.createElement("div");
      card.className = "manual-review-card collapsed";
      const isResolved = (ex.resolution_status || "").toLowerCase() !== "open";
      const outcome = (ex.resolved_outcome || "").toLowerCase();

      const excId = ex.exception_id || ex.settlement_id || "EXC-100";
      const descText = ex.description || ex.settlement_id || "Unresolved Transaction";
      const amtText = formatMoney(ex.amount);
      const bankUtr = ex.bank_transaction_id || "Unlinked / Candidate";

      let actionHtml = "";
      if (isResolved) {
        const isMatch = outcome === "confirmed_match" || outcome === "match";
        const badgeClass = isMatch ? "badge-resolved-match" : "badge-resolved-non-match";
        const label = isMatch ? "Resolved: Confirmed Match ✓" : "Resolved: Confirmed Non-Match ✕";
        actionHtml = `<span class="resolved-status-badge ${badgeClass}">${label}</span>`;
      } else {
        actionHtml = `
          <div class="review-action-row">
            <button type="button" class="btn-confirm-non-match" data-exc-id="${excId}">
              ✕ Confirm Non-Match
            </button>
            <button type="button" class="btn-confirm-match" data-exc-id="${excId}">
              ✓ Confirm Match
            </button>
          </div>
        `;
      }

      card.innerHTML = `
        <div class="review-card-header">
          <div class="review-card-header-left">
            <span class="review-expand-chevron">▸</span>
            <div class="review-status-tag">
              <span class="pulse-dot"></span>
              <span>AMBIGUOUS</span>
            </div>
            <div class="review-exc-id font-mono">ID: ${excId}</div>
            <div class="review-card-title">${descText}</div>
          </div>
          <div class="review-card-header-right">
            <span class="review-target-utr font-mono">Target: ${bankUtr}</span>
            <span class="review-card-amt font-mono">${amtText}</span>
          </div>
        </div>

        <div class="review-card-body" style="display: none;">
          <div class="review-comparison-grid">
            <div class="comparison-side flagged-side">
              <div class="side-label">FLAGGED TRANSACTION</div>
              <div class="primary-text">${descText}</div>
              <div class="secondary-info">Date: ${ex.date || "—"} &bull; Source: ${ex.source || "Settlement"}</div>
              <div class="amount-tag font-mono">${amtText}</div>
            </div>

            <div class="comparison-divider">
              <div class="divider-icon" title="Candidate Comparison">↔</div>
            </div>

            <div class="comparison-side target-side">
              <div class="side-label">CANDIDATE BANK TARGET</div>
              <div class="primary-text font-mono">${bankUtr}</div>
              <div class="secondary-info">Status: Requires Resolution</div>
              <div class="confidence-tag font-mono">ML Confidence: Ambiguous</div>
            </div>
          </div>

          <div class="review-ai-box">
            <div class="ai-box-header">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
              <span>LLM AUDIT TRAIL & REASONING</span>
            </div>
            <div class="ai-box-content">${ex.reason || "Ambiguous candidate requiring human decision."}</div>
          </div>

          <div class="review-card-footer" id="action-container-${excId}">
            ${actionHtml}
          </div>
        </div>
      `;

      // Expand / Collapse toggle on header click!
      const headerEl = card.querySelector(".review-card-header");
      const bodyEl = card.querySelector(".review-card-body");
      const chevronEl = card.querySelector(".review-expand-chevron");

      headerEl.addEventListener("click", () => {
        const isCollapsed = bodyEl.style.display === "none";
        if (isCollapsed) {
          bodyEl.style.display = "block";
          card.classList.remove("collapsed");
          card.classList.add("expanded");
          chevronEl.textContent = "▾";
        } else {
          bodyEl.style.display = "none";
          card.classList.remove("expanded");
          card.classList.add("collapsed");
          chevronEl.textContent = "▸";
        }
      });

      const matchBtn = card.querySelector(".btn-confirm-match");
      const nonMatchBtn = card.querySelector(".btn-confirm-non-match");

      if (matchBtn) {
        matchBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          await handleExceptionResolution(excId, "confirmed_match", card);
        });
      }

      if (nonMatchBtn) {
        nonMatchBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          await handleExceptionResolution(excId, "confirmed_non_match", card);
        });
      }

      container.appendChild(card);
    });
  }

  async function handleExceptionResolution(excId, outcome, cardElement) {
    try {
      const footer = cardElement.querySelector(".review-card-footer");
      if (footer) {
        footer.innerHTML = '<span class="spinner"></span> Updating Exception Ledger & ML Feedback Loop...';
      }

      const res = await window.LedgerApi.resolveException(excId, outcome);

      if (res && res.ok) {
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
    document.getElementById("reconcileResults").style.display = "block";

    currentTransactions = reconRes.run.transactions || [];
    currentExceptions = exceptionsRes.exceptions || [];

    renderSummary(reconRes.run);
    updateTagFilterBar();
    applyTransactionFiltersAndRender();
    renderManualReviewQueue(currentExceptions);
  }

  function initReconcile() {
    const runBtn = document.getElementById("runReconcileBtn");
    const closeBtn = document.getElementById("closePeriodBtn");

    runBtn.addEventListener("click", async () => {
      runBtn.disabled = true;
      runBtn.innerHTML = '<span class="spinner"></span> Processing All Statements…';

      try {
        const result = await window.LedgerApi.runReconciliation();
        currentRunId = result.run_id;
        await loadRun(currentRunId);
      } catch (err) {
        const message = err instanceof window.ApiError ? err.message : "Reconciliation run failed.";
        alert(message);
      } finally {
        runBtn.disabled = false;
        runBtn.innerHTML = 'Run Auto-Match <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M5 12H19M19 12L13 6M19 12L13 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      }
    });

    closeBtn.addEventListener("click", async () => {
      if (!currentRunId) return;
      closeBtn.disabled = true;
      try {
        const result = await window.LedgerApi.closePeriod(currentRunId);
        renderSummary(result.run);
      } catch (err) {
        const message = err instanceof window.ApiError ? err.message : "Could not close period.";
        alert(message);
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

  document.addEventListener("DOMContentLoaded", () => {
    initSubTabs();
    initSidebarToggle();
    initSidebarResizer();
    initUploads();
    initAppendButton();
    initCollapsibleSections();
    initTableSorting();
    initFilterInputs();
    initReconcile();
    loadSidebarSources();
    hydrateExistingRun();
    activateSub("sub-current-period");
  });
})();
