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

  function formatMoney(value) {
    const n = Number(value) || 0;
    const sign = n < 0 ? "-" : "";
    return `${sign}₹${Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
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
    if (navCurrent) navCurrent.addEventListener("click", () => activateSub("sub-reconcile"));

    const navAuto = document.getElementById("navAutoMatchRun");
    if (navAuto) navAuto.addEventListener("click", () => activateSub("sub-reconcile"));

    const navClose = document.getElementById("navClosePeriod");
    if (navClose) navClose.addEventListener("click", () => activateSub("sub-close"));

    const addBtn = document.getElementById("addSourceBtn");
    if (addBtn) {
      addBtn.addEventListener("click", () => activateSub("sub-upload-bank"));
    }

    const runMatchBtn = document.getElementById("sidebarRunMatchBtn");
    if (runMatchBtn) {
      runMatchBtn.addEventListener("click", async () => {
        activateSub("sub-reconcile");
        try {
          await hydrateExistingRun();
        } catch (_) {}
        const mainRunBtn = document.getElementById("runReconcileBtn");
        if (mainRunBtn) mainRunBtn.click();
      });
    }

    const closeStmtViewBtn = document.getElementById("closeStmtViewBtn");
    if (closeStmtViewBtn) {
      closeStmtViewBtn.addEventListener("click", () => activateSub("sub-upload-bank"));
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
        return;
      }

      statements.forEach((stmt) => renderSourceListItem(stmt, listEl));
    } catch (_) {
      // Ignore error
    }
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

        await loadSidebarSources();
        if (stmt.id) {
          openStatementView(stmt.id);
        }
      } catch (err) {
        const message = err instanceof window.ApiError ? err.message : "Upload failed. Please try again.";
        setStatus(source, message, "error");
        importBtn.disabled = false;
      }
    });
  }

  function initUploads() {
    initTypeSelector();
    initColorPicker();
    document.querySelectorAll(".dropzone").forEach(initDropzone);
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
        if (col.toLowerCase().includes("amount")) {
          td.classList.add("amount-positive");
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

  function initFilterInputs() {
    const txSearch = document.getElementById("txSearchInput");
    const txStatus = document.getElementById("txStatusFilter");
    if (txSearch) txSearch.addEventListener("input", applyTransactionFiltersAndRender);
    if (txStatus) txStatus.addEventListener("change", applyTransactionFiltersAndRender);

    const excSearch = document.getElementById("excSearchInput");
    if (excSearch) excSearch.addEventListener("input", applyExceptionFiltersAndRender);
  }

  function applyTransactionFiltersAndRender() {
    let list = [...currentTransactions];
    const q = (document.getElementById("txSearchInput")?.value || "").toLowerCase().trim();
    const statusVal = document.getElementById("txStatusFilter")?.value || "all";

    if (statusVal !== "all") {
      list = list.filter((tx) => (tx.status || "").toLowerCase() === statusVal);
    }

    if (q) {
      list = list.filter((tx) => {
        const d = (tx.date || "").toLowerCase();
        const b = (tx.bank_description || tx.description || "").toLowerCase();
        const g = (tx.gl_description || "").toLowerCase();
        const a = String(tx.amount || "");
        return d.includes(q) || b.includes(q) || g.includes(q) || a.includes(q);
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
    const percent = s.percent_reconciled != null ? s.percent_reconciled : 0;

    document.getElementById("periodBadge").textContent = run.period_label || "—";
    document.getElementById("periodBadge").classList.toggle("badge-closed", !!run.closed);
    document.getElementById("closePeriodBtn").textContent = run.closed ? "Period Closed ✓" : "Close Period";
    document.getElementById("closePeriodBtn").disabled = !!run.closed;

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
  }

  function statusPillClass(status) {
    if (status === "auto" || status === "matched") return "status-auto";
    if (status === "llm") return "status-llm";
    if (status === "manual") return "status-manual";
    return "status-exception";
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
      const isLlm = tx.status === "llm";
      const pillLabel = isLlm ? "✨ LLM" : (tx.status || "").replace(/^\w/, (c) => c.toUpperCase());
      const titleReason = tx.reason ? `title="${tx.reason}"` : "";
      const descText = tx.bank_description || tx.description || "Transaction Record";

      tr.innerHTML = `
        <td><span class="row-expand-icon">▸</span> ${tx.date ?? "—"}</td>
        <td class="desc">${descText}</td>
        <td><code class="gl-code">${tx.gl_description ?? tx.stage ?? "—"}</code></td>
        <td class="${amountClass}">${formatMoney(tx.amount)}</td>
        <td><span class="status-pill ${statusPillClass(tx.status)}" ${titleReason}>${pillLabel}</span></td>
      `;

      const detailTr = document.createElement("tr");
      detailTr.className = "detail-row";
      detailTr.style.display = "none";
      const confPct = Math.round((tx.confidence || 1.0) * 100);

      detailTr.innerHTML = `
        <td colspan="5">
          <div class="row-expansion-card">
            <div class="expansion-header">
              <div class="expansion-title-group">
                <span class="expansion-stage-badge">${(tx.stage || "reconciler").toUpperCase()} STAGE</span>
                <h4 class="expansion-title">${descText}</h4>
              </div>
              <div class="expansion-conf-badge">
                <span class="conf-dot"></span> ${confPct}% Confidence Match
              </div>
            </div>
            <div class="expansion-grid">
              <div class="expansion-item">
                <span class="lbl">Reference / GL ID</span>
                <span class="val font-mono">${tx.gl_description || "—"}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Transaction Date</span>
                <span class="val">${tx.date || "—"}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Amount</span>
                <span class="val font-mono ${amountClass}">${formatMoney(tx.amount)}</span>
              </div>
              <div class="expansion-item">
                <span class="lbl">Match Status</span>
                <span class="val" style="color:var(--accent-2); font-weight:600;">${(tx.status || "unreconciled").toUpperCase()}</span>
              </div>
              <div class="expansion-item full-width">
                <span class="lbl">Matching Reason & Audit Trail</span>
                <div class="reason-callout">${tx.reason || "Matched deterministically by rule engine."}</div>
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

  async function loadRun(runId) {
    const [reconRes, exceptionsRes] = await Promise.all([
      window.LedgerApi.getReconciliation(runId),
      window.LedgerApi.getExceptions(runId),
    ]);

    document.getElementById("reconcileEmptyState").style.display = "none";
    document.getElementById("reconcileResults").style.display = "block";

    currentTransactions = reconRes.run.transactions || [];
    currentExceptions = exceptionsRes.exceptions || [];

    renderSummary(reconRes.run);
    applyTransactionFiltersAndRender();
    applyExceptionFiltersAndRender();
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
  });
})();
