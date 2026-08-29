# Ledger AI — Status Classification Specification: SIMILAR

> **Taxonomy Status**: `300_SIMILAR`  
> **Target Outcome**: Potential candidate match identified ($0.50 \le \text{Score} < 0.85$) flagged for review.

---

## 1. Overview & Definition

A record is assigned **`SIMILAR`** status when the reconciliation engine identifies potential counterpart candidates that share descriptive keywords (customer names, transaction modes, reference numbers) or date/amount proximity, but do not meet the automatic acceptance threshold ($\ge 0.85$).

---

## 2. High-Level Classification Algorithm

```
  ┌──────────────────────────────────────────────────────────┐
  │         Candidate Pair Evaluated in Stage 2              │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │               Composite Score Check                      │
  │            0.50 <= Composite Score < 0.85                │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │             Shared Keyword Extraction                    │
  │     Tokenize Description -> Filter Stop Words -> Match  │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │     Queue Candidate Pair into "Find Similar Payments"    │
  │       Surfaced in Comparison Modal Candidate Drawer      │
  └──────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Qualification Criteria

A pair qualifies as **`SIMILAR`** under the following conditions:

1. **Score Window**: Composite score falls between **`0.50`** and **`0.84`**.
2. **Partial Text Alignment**: Shared customer name (e.g. `Meera Iyer`), card network code, or partial reference substring overlap without exact UTR match.
3. **Amount Proximity**: Amount delta is within reasonable candidate variance ($\le ₹10.00$ or percentage ratio $\ge 0.90$).
4. **Surfaced via Candidate Drawer**: Accessible in the frontend comparison modal by clicking **"Find Similar Payments"** (`/api/similar_payments`).

---

## 4. Description Keyword Extraction Algorithm

In `frontend/static/js/dashboard.js`, shared keywords are extracted using tokenized stop-word filtering:

```javascript
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
```

---

## 5. Key Files & Code Reference

| File Path | Responsible Function / Method | Role |
|---|---|---|
| `matcher/tolerance_matcher.py` | `match_tolerance()` | Flags pairs scoring between 0.50 and 0.84 as similar. |
| `frontend/api/routes.py` | `/api/similar_payments` | API endpoint returning candidate pool for an unmatched record. |
| `frontend/static/js/dashboard.js` | `triggerFindSimilarPayments()`, `extractSharedKeywords()` | Fetches candidates and renders keyword match chips. |

---

## 6. User Interface Representation

- **Table Status Pill**: `<span class="status-pill status-similar">SIMILAR</span>` (Amber Gold / Warm Orange)
- **Comparison Modal**: Displays candidate list in drawer and green keyword chips (e.g. `🔑 Shared Keywords: MEERA, IYER`).
