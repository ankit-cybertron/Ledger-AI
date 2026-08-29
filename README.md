---
title: Ledger AI — Automated Financial Reconciliation Engine
emoji: ⚖️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Ledger AI — Automated Financial Reconciliation Engine

Ledger AI is an enterprise-grade financial reconciliation engine designed to match bank statements, payment gateway settlements (Razorpay, PayPal, Stripe), and internal order books.

## Features
- **3-Pass Matching Cascade**: Clean Exact Match, Fee/MDR-Aware Net Settlement Solver, and 1:N Split/Aggregate Matcher.
- **Evidence-Weighted Scoring Engine**: Calculates confidence scores based on reference IDs, amounts, dates, and narration similarity.
- **Groq LLM Agent**: Resolves ambiguous exceptions ($0.50 \le \text{Confidence} < 0.85$) with automated multi-key rotation.
- **Multi-Format Ingestion**: Supports CSV, Excel (`.xlsx`, `.xls`), and PDF statement parsing.
- **Audit Reports**: PDF and Excel summary exports with full transaction breakdown.

## Local Development
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment variables
cp .env.example .env

# 3. Run application locally
python run.py
```

Open `http://127.0.0.1:5050` in your browser.
