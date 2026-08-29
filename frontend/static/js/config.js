/**
 * config.js — Centralized UI Configuration for Ledger AI Frontend.
 *
 * Encapsulates UI display constants, chart palettes, log buffer sizes,
 * title truncation limits, and currency symbols.
 */

window.UI_CONFIG = {
  log_buffer_size: 200,
  title_truncation_length: 48,
  currency_symbol: "₹",
  currency_symbol_report: "Rs.",
  status_colors: {
    SETTLED: "#10b981",
    MATCHED: "#3b82f6",
    SIMILAR: "#f59e0b",
    UNMATCHED: "#ef4444"
  },
  chart_colors: {
    SETTLED: "#10b981",
    MATCHED: "#3b82f6",
    SIMILAR: "#f59e0b",
    UNMATCHED: "#ef4444"
  },
  confidence_histogram_buckets: [
    "0.0-0.5",
    "0.5-0.7",
    "0.7-0.85",
    "0.85-0.95",
    "0.95-1.0"
  ],
  thresholds: {
    auto_match_confidence: 0.85,
    similar_min_confidence: 0.50,
    llm_trigger_lower: 0.50,
    llm_trigger_upper: 0.85
  }
};
