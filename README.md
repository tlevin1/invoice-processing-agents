# Acme Corp — Automated Invoice Processing System

A multi-agent pipeline that takes an invoice in any format, validates it against live inventory, routes it through tiered approval logic, and pays or rejects it — all from a single command. Built as a working prototype, not a design doc.

---

## How to run it

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Seed the inventory database
python setup_db.py

# 3. Set your API key
export ANTHROPIC_API_KEY=your-key-here

# 4. Process a single invoice
python main.py --invoice_path=data/invoices/invoice_1001.txt

# Or run every invoice in the sample set at once
python run_all.py
```

Supported formats: `.txt`, `.json`, `.csv`, `.pdf`, `.xml`

---

## Architecture

Four agents in sequence. Each is a separate module; they talk to each other through plain Python dataclasses, not a framework.

```
Invoice file
     │
     ▼
┌─────────────┐   reads TXT / JSON / CSV / PDF / XML
│  INGESTION  │   extracts structured fields via LLM tool use
│   (LLM)    │   self-corrects if math or data issues found
└──────┬──────┘
       │  InvoiceData
       ▼
┌─────────────┐   queries SQLite inventory
│ VALIDATION  │   deterministic rule checks
│ (no LLM)   │   flags stock mismatches, unknown items, bad data
└──────┬──────┘
       │  ValidationResult
       ▼
┌─────────────┐   auto / standard / critique-loop tiers
│  APPROVAL   │   LLM sees full validation report
│ (LLM)      │   high-value invoices get an independent critique pass
└──────┬──────┘
       │  ApprovalResult
       ▼
┌─────────────┐   mock payment API call
│   PAYMENT   │   or appends to rejected_invoices.jsonl
└─────────────┘
```

---

## Decisions I made and why

**Claude over Grok.** The spec suggested Grok but said alternatives were fine. I went with Claude because of forced tool use — you can tell the API "call this specific function and nothing else," which means the ingestion output is always valid structured JSON. No prompt engineering, no parsing, no "sometimes it returns markdown." That's the kind of thing that causes the 30% error rate the spec describes, and forced tool use eliminates it at the source.

**LLM extraction with a self-correction loop.** After the initial extraction, a second LLM call audits the result for four concrete problems: negative quantities, math that doesn't add up, missing vendor, zero prices. If it finds something, it feeds the critique back and re-extracts (up to twice). This catches the kind of subtle errors — a quantity pulled as -5 instead of 5, or a total that's off by $100 — that would otherwise slip through to payment. The critique prompt uses extended thinking so the model actually reasons before flagging something.

**Validation is pure Python, no LLM.** Checking whether GadgetX qty=20 exceeds stock=5 doesn't need a language model. Keeping validation deterministic means it's fast, cheap, and fully testable — the test suite covers all 17 validation scenarios without touching the API. The LLM comes in only where judgment is actually needed.

**Overstock is a warning, not a hard failure.** This was a deliberate call. If a vendor requests 20 units and we only have 5, that's worth flagging, but it's not necessarily fraud — maybe procurement is planning ahead, or stock levels are stale. Blocking it outright at validation would create false positives. Instead it surfaces as a warning that the approval agent sees and weighs in context.

**Tiered approval.** Not every invoice needs the same scrutiny. Under $5K with a clean validation? Approve automatically — no API call, no latency, no cost. $5K–$10K gets a single LLM review. Over $10K gets two passes: an initial review, then an independent critique of that review before the final decision. This mirrors how actual finance teams work (auto-pay small invoices, VP sign-off on large ones) and means we're not burning LLM calls on a $300 order.

**Rejection log as append-only JSONL.** Every rejected invoice gets a timestamped record with the full reasoning. Append-only means nothing is ever overwritten and the file is trivially parseable. In a real system this would feed into a review queue; here it's at `rejected_invoices.jsonl`.

---

## Tests

After installing dependencies (`pip install -r requirements.txt`):

```bash
pytest tests/ -v
```

26 tests, all passing, no API key required. The test suite covers every scenario from the spec table — clean invoices, overstock, zero stock, unknown items, negative quantities, multi-line aggregation, math mismatches, missing fields — plus the approval tier boundary logic.

```
tests/test_file_reader.py    — format dispatch, error handling, PDF and XML content
tests/test_validation.py     — all validation scenarios + auto-approval boundary
```

---

## Sample output

```
================================================================
  ACME CORP — INVOICE PROCESSING SYSTEM
================================================================

  Invoice:   data/invoices/invoice_1001.txt
  Database:  inventory.db

  STAGE 1: INGESTION
  ──────────────────────────────────────────────────────────────
  Format:            TXT
  Invoice #:         INV-1001
  Vendor:            Precision Parts Ltd
  Total:             $3,750.00
  Line items:        2
    →  WidgetA               qty=     5  @   $250.00  =   $1,250.00
    →  WidgetB               qty=     5  @   $500.00  =   $2,500.00

  STAGE 2: VALIDATION
  ──────────────────────────────────────────────────────────────
  Status:            PASSED
  ✓ No issues found.

  STAGE 3: APPROVAL
  ──────────────────────────────────────────────────────────────
  Tier:              Auto (< $5K, clean)
  Decision:          APPROVED

  STAGE 4: PAYMENT
  ──────────────────────────────────────────────────────────────
  Status:            ✓  SUCCESS

  Payment of $3,750.00 to 'Precision Parts Ltd' processed successfully.

================================================================
  PROCESSING COMPLETE  (3.8s)
  INV-1001  Precision Parts Ltd  $3,750.00  →  ✓ PAID
================================================================
```

---

## Invoice scenarios covered

| Invoice | Format | What it tests |
|---|---|---|
| INV-1001 | TXT | Clean order, auto-approved |
| INV-1002 | TXT | GadgetX × 20 (stock: 5) — overstock warning |
| INV-1003 | TXT | FakeItem, 0 stock — rejected |
| INV-1004 | JSON | Clean JSON format, auto-approved |
| INV-1006 | CSV | Clean CSV format |
| INV-1008 | TXT | Unknown items (SuperGizmo, MegaSprocket) — rejected |
| INV-1009 | JSON | Negative quantity — rejected |
| INV-1011 | PDF | PDF extraction |
| INV-1013 | JSON | Same item across multiple lines, aggregated stock check |
| INV-1016 | JSON | WidgetC not in inventory — rejected |

---

## Requirements

```
anthropic>=0.43.0   # Claude API
pdfplumber>=0.11.0  # PDF text extraction
```

Python 3.11+. SQLite is in the standard library.

The inventory database is seeded with four items: WidgetA (15 in stock), WidgetB (10), GadgetX (5), FakeItem (0 — always rejected).
