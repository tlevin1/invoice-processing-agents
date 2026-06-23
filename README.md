# Acme Corp — Automated Invoice Processing System

A multi-agent pipeline that ingests invoices in any format, validates them against a live inventory database, routes them through tiered LLM-based approval, and processes or logs the payment result — all from the command line.

---

## Architecture

The system is a four-stage sequential pipeline. Each stage is an independent module in `agents/`; they communicate through plain Python dataclasses (`models.py`) rather than a framework runtime, keeping the code readable and easy to test.

```
Invoice file
     │
     ▼
┌─────────────┐      tools/file_reader.py
│  INGESTION  │  ←── reads TXT / JSON / CSV / PDF / XML
│   (LLM)    │      returns raw text string
└──────┬──────┘
       │  InvoiceData
       ▼
┌─────────────┐      tools/db.py
│ VALIDATION  │  ←── queries SQLite inventory
│ (rule-based)│      fully deterministic
└──────┬──────┘
       │  ValidationResult
       ▼
┌─────────────┐
│  APPROVAL   │  tiered: auto / standard LLM / critique loop
│   (LLM)    │
└──────┬──────┘
       │  ApprovalResult
       ▼
┌─────────────┐
│   PAYMENT   │  mock API call or rejection log (JSONL)
│ (rule-based)│
└─────────────┘
```

### Agents

| Agent | File | LLM? | Responsibility |
|---|---|---|---|
| Ingestion | `agents/ingestion.py` | Yes | Extract structured fields from raw invoice text |
| Validation | `agents/validation.py` | No | Check data integrity and inventory stock levels |
| Approval | `agents/approval.py` | Conditional | Tiered decision logic with optional LLM review |
| Payment | `agents/payment.py` | No | Execute mock payment or log rejection |

### Supporting modules

- `tools/file_reader.py` — format dispatch (TXT, JSON, CSV, PDF via pdfplumber, XML); always returns a plain string so the ingestion LLM handles parsing
- `tools/db.py` — thin SQLite wrapper; `DB_PATH` is overridable at runtime for testing
- `models.py` — `InvoiceData` and `LineItem` dataclasses; the shared contract between all agents
- `setup_db.py` — seeds `inventory.db` with the four canonical items

---

## Key Design Decisions

### 1. Claude as the LLM (not Grok)
The spec recommended xAI Grok but allowed alternatives. Claude was chosen because:
- **Forced tool use** (`tool_choice: {"type": "tool", "name": "..."}`) guarantees structured JSON output with no prompt-engineering fragility
- **Extended thinking** (`thinking: {"type": "adaptive"}`) is available on the critique and approval passes, letting the model reason before committing to a decision
- The Anthropic Python SDK is mature and streaming-first

### 2. Structured extraction via tool use (not prompt parsing)
The ingestion agent uses a single `extract_invoice` tool with a strict JSON Schema. Claude is forced to call it, so the output is always valid, typed, and schema-checked — no regex, no brittle string parsing.

### 3. Self-correction loop in ingestion
After extraction, a second LLM call critiques the result for four concrete problems (negative quantities, math mismatch, missing vendor, zero unit prices). If issues are found, extraction is retried with the critique included in the prompt (up to `MAX_RETRIES = 2`). This catches errors the initial pass misses without requiring human intervention.

### 4. Deterministic validation (no LLM)
Validation is intentionally pure Python with no LLM. Every check is rule-based and reproducible, which makes it fast, cheap, and fully testable. The LLM enters only where judgment is required (approval).

### 5. Tiered approval
| Tier | Condition | Mechanism |
|---|---|---|
| Auto | total < $5,000 AND no validation errors | Immediate approval, no LLM call |
| Standard | $5,000 ≤ total ≤ $10,000 | Single LLM review pass |
| High-value | total > $10,000 | Initial review → independent critique → final decision |

The critique pass in the high-value tier gives a second "VP" perspective on the initial reasoning, catching gaps or overlooked risks before the final decision is committed.

### 6. Overstock as warning, not error
Stock quantity exceeded is flagged as a warning (not an error) so the invoice can still pass validation and proceed to LLM approval — the LLM can then weigh business context. Hard failures (unknown items, zero stock, negative quantities) are errors that block approval automatically.

### 7. Rejection log as append-only JSONL
Rejected invoices are written to `rejected_invoices.jsonl` — one JSON object per line with timestamp, invoice fields, approval tier, and full reasoning. Append-only means no data is ever lost and the file is trivially streamable.

---

## Testing

Tests are split by concern — no LLM calls anywhere in the test suite.

```
tests/
├── test_file_reader.py   — format dispatch, error handling, PDF/XML content
└── test_validation.py    — all validation scenarios + approval tier boundary logic
```

### What's covered (26 tests, all passing)

**File reader (9 tests)**
- Reads all 5 supported formats and correctly identifies the format string
- Raises `ValueError` for unsupported extensions
- Raises `FileNotFoundError` for missing files
- Confirms PDF text extraction works and XML tags are preserved

**Validation (15 tests)**
- Clean invoices within stock limits pass with no issues
- Overstock quantity → warning, invoice still passes
- Zero-stock item → error, invoice fails
- Unknown item (not in DB) → error
- Negative quantity → error
- Multi-line same-item quantities are aggregated before stock check
- Math mismatch (subtotal + tax ≠ total) → warning
- Missing vendor → error
- Empty line items → error
- Negative total → error

**Approval tier boundaries (2 tests, no LLM)**
- Invoice under $5K with clean validation → `tier == "auto"`, approved without API call
- Invoice under $5K with validation errors → does NOT qualify for auto tier

### Running the tests

```bash
# activate the project virtualenv first
source /Users/Tehila1/interviews/bin/activate

pytest tests/ -v
```

All 26 tests run in under 1 second with no API key required.

---

## Requirements

```
anthropic>=0.43.0   # Claude API — ingestion and approval agents
pdfplumber>=0.11.0  # PDF text extraction
```

Python 3.11+ required (uses `match`-compatible features and modern type hints).

---

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create the inventory database
python setup_db.py

# 3. Set your API key
export ANTHROPIC_API_KEY=your-key-here
```

The inventory database is seeded with:

| Item | Stock |
|---|---|
| WidgetA | 15 |
| WidgetB | 10 |
| GadgetX | 5 |
| FakeItem | 0 |

---

## Usage

```bash
# Single invoice
python main.py --invoice_path=data/invoices/invoice_1001.txt

# With explicit DB path
python main.py --invoice_path=data/invoices/invoice_1013.json --db_path=inventory.db

# Run all sample invoices in sequence
python run_all.py
```

Supported input formats: `.txt`, `.json`, `.csv`, `.pdf`, `.xml`

### Sample output

```
================================================================
  ACME CORP — INVOICE PROCESSING SYSTEM
================================================================

  STAGE 1: INGESTION
  ──────────────────────────────────────────────────────────────
  Format:            TXT
  Invoice #:         INV-1001
  Vendor:            Precision Parts Ltd
  Total:             $3,750.00
  Line items:        2

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

================================================================
  PROCESSING COMPLETE  (4.2s)
  INV-1001  Precision Parts Ltd  $3,750.00  →  ✓ PAID
================================================================
```

---

## Sample Invoice Scenarios

| Invoice | Format | Scenario | Expected outcome |
|---|---|---|---|
| INV-1001 | TXT | Clean, under $5K | Auto-approved |
| INV-1002 | TXT | GadgetX × 20 (stock: 5) | Warning, LLM review |
| INV-1003 | TXT | FakeItem (0 stock) | Validation error → rejected |
| INV-1004 | JSON | Clean within stock | Auto-approved |
| INV-1006 | CSV | Clean within stock | Auto-approved |
| INV-1008 | TXT | SuperGizmo, MegaSprocket (unknown) | Validation errors → rejected |
| INV-1009 | JSON | Negative quantity | Validation error → rejected |
| INV-1011 | PDF | Clean PDF format | Standard or auto |
| INV-1013 | JSON | Same item across multiple lines, aggregated overstock | Warnings, LLM review |
| INV-1016 | JSON | WidgetC (unknown item) | Validation error → rejected |
