/* ==========================================================================
   Ledger AI — Theme Toggle Script
   Phase 1: Dark / Light Mode with localStorage persistence
   ========================================================================== */
(function () {
  'use strict';

  const STORAGE_KEY  = 'ledger-theme';
  const DARK_THEME   = 'dark';
  const LIGHT_THEME  = 'light';

  /* ── Apply saved theme immediately (before DOM renders) ─────────────── */
  const savedTheme = localStorage.getItem(STORAGE_KEY) || DARK_THEME;
  document.documentElement.setAttribute('data-theme', savedTheme);

  /* ── Toggle function (called by button click) ────────────────────────── */
  function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || DARK_THEME;
    const next    = current === DARK_THEME ? LIGHT_THEME : DARK_THEME;
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem(STORAGE_KEY, next);
    updateToggleIcon(next);
  }

  /* ── Update icon on toggle button ───────────────────────────────────── */
  function updateToggleIcon(theme) {
    const btn = document.getElementById('themeToggleBtn');
    const label = document.querySelector('.sidebar-theme-label');
    const isDark = theme === DARK_THEME;

    if (btn) {
      btn.title = isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode';
      btn.setAttribute('aria-label', btn.title);
      btn.innerHTML = isDark
        ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`
        : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;
    }

    if (label) {
      label.textContent = isDark ? 'Dark Mode' : 'Light Mode';
    }
  }

  /* ── Bind toggle button after DOM is ready ───────────────────────────── */
  function bindToggle() {
    const btn = document.getElementById('themeToggleBtn');
    if (btn) {
      btn.addEventListener('click', toggleTheme);
      updateToggleIcon(document.documentElement.getAttribute('data-theme') || DARK_THEME);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindToggle);
  } else {
    bindToggle();
  }

  /* ── Expose for external use ─────────────────────────────────────────── */
  window.LedgerTheme = { toggle: toggleTheme, current: () => document.documentElement.getAttribute('data-theme') };

}());
