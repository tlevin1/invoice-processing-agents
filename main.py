#!/usr/bin/env python3
"""
Acme Corp — Automated Invoice Processing System

Usage:
    python main.py --invoice_path=data/invoices/invoice_1001.txt
    python main.py --invoice_path=data/invoices/invoice_1003.txt
    python main.py --invoice_path=data/invoices/invoice_1013.json --db_path=inventory.db

Prereqs:
    1. python setup_db.py            (creates inventory.db)
    2. export ANTHROPIC_API_KEY=...  (Claude API key)
    3. pip install -r requirements.txt
"""
import argparse
import os
import sys
import time
from pathlib import Path


# ── ANSI color helpers (graceful fallback for non-TTY) ───────────────────────
_USE_COLOR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text

def GREEN(t: str) -> str:  return _c("32", t)
def RED(t: str) -> str:    return _c("31", t)
def YELLOW(t: str) -> str: return _c("33", t)
def CYAN(t: str) -> str:   return _c("36", t)
def BOLD(t: str) -> str:   return _c("1",  t)
def DIM(t: str) -> str:    return _c("2",  t)


# ── Output formatting ────────────────────────────────────────────────────────
WIDTH = 64

def _header(title: str) -> None:
    print()
    print("=" * WIDTH)
    print(f"  {BOLD(title)}")
    print("=" * WIDTH)

def _section(stage: int, title: str) -> None:
    print()
    print(f"  {CYAN(f'STAGE {stage}:')} {BOLD(title)}")
    print("  " + "─" * (WIDTH - 2))

def _row(label: str, value: str, width: int = 18) -> None:
    print(f"  {DIM(label.ljust(width))} {value}")

def _issue(severity: str, field: str, msg: str) -> None:
    if severity == "error":
        icon = RED("✗ ERROR  ")
    else:
        icon = YELLOW("⚠ WARNING")
    print(f"  {icon}  {field}: {msg}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acme Corp Automated Invoice Processing System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--invoice_path",
        required=True,
        metavar="PATH",
        help="Path to an invoice file (.txt, .json, .csv, .pdf, .xml)",
    )
    parser.add_argument(
        "--db_path",
        default="inventory.db",
        metavar="PATH",
        help="Path to SQLite inventory database (default: inventory.db)",
    )
    args = parser.parse_args()

    # ── Pre-flight checks ────────────────────────────────────────────────────
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(RED("ERROR: ANTHROPIC_API_KEY is not set."), file=sys.stderr)
        print("  Set it with: export ANTHROPIC_API_KEY=your-key", file=sys.stderr)
        return 1

    if not Path(args.invoice_path).exists():
        print(RED(f"ERROR: Invoice file not found: {args.invoice_path}"), file=sys.stderr)
        return 1

    if not Path(args.db_path).exists():
        print(RED(f"ERROR: Inventory database not found: {args.db_path}"), file=sys.stderr)
        print("  Run 'python setup_db.py' to create it.", file=sys.stderr)
        return 1

    # Override DB path for tools layer
    import tools.db as db_module
    db_module.DB_PATH = args.db_path

    # Late imports so the pre-flight errors are cheap
    from tools.file_reader import read_invoice
    from agents import ingestion, validation, approval, payment

    _header("ACME CORP — INVOICE PROCESSING SYSTEM")
    print(f"\n  {DIM('Invoice:')} {args.invoice_path}")
    print(f"  {DIM('Database:')} {args.db_path}")

    t_start = time.time()

    # ════════════════════════════════════════════════════════════════════════
    # STAGE 1 — INGESTION
    # ════════════════════════════════════════════════════════════════════════
    _section(1, "INGESTION")
    try:
        content, fmt = read_invoice(args.invoice_path)
        _row("Format:", fmt.upper())
        _row("Content length:", f"{len(content):,} chars")

        invoice = ingestion.run(content, source_path=args.invoice_path)
    except Exception as exc:
        print(RED(f"\n  INGESTION FAILED: {exc}"))
        return 1

    _row("Invoice #:",  invoice.invoice_number)
    _row("Vendor:",     invoice.vendor)
    _row("Date:",       str(invoice.date))
    _row("Due Date:",   str(invoice.due_date))
    _row("Currency:",   invoice.currency)
    _row("Total:",      f"${invoice.total:,.2f}")
    _row("Line items:", str(len(invoice.line_items)))
    for li in invoice.line_items:
        print(
            f"  {DIM('  →'):5s} {li.item:20s} "
            f"qty={li.quantity:>6.0f}  "
            f"@ ${li.unit_price:>8.2f}  "
            f"= ${li.line_total:>10.2f}"
        )

    # ════════════════════════════════════════════════════════════════════════
    # STAGE 2 — VALIDATION
    # ════════════════════════════════════════════════════════════════════════
    _section(2, "VALIDATION")
    val_result = validation.run(invoice, db_path=args.db_path)

    status_str = (
        GREEN("PASSED") if val_result.passed else RED("FAILED")
    )
    _row("Status:", status_str)

    if val_result.issues:
        print()
        for issue in val_result.issues:
            _issue(issue.severity, issue.field, issue.message)
    else:
        print(f"  {GREEN('✓')} No issues found.")

    # ════════════════════════════════════════════════════════════════════════
    # STAGE 3 — APPROVAL
    # ════════════════════════════════════════════════════════════════════════
    _section(3, "APPROVAL")

    tier_labels = {
        "auto":       "Auto (< $5K, clean)",
        "standard":   "Standard LLM Review",
        "high_value": "High-Value Critique Loop",
    }

    try:
        approval_result = approval.run(invoice, val_result)
    except Exception as exc:
        print(RED(f"\n  APPROVAL FAILED: {exc}"))
        return 1

    decision_str = (
        GREEN("APPROVED") if approval_result.approved else RED("REJECTED")
    )
    _row("Tier:",     tier_labels.get(approval_result.tier, approval_result.tier))
    _row("Decision:", BOLD(decision_str))
    print()
    print(DIM("  ── Reasoning ──────────────────────────────────────────"))
    for line in approval_result.reasoning.splitlines():
        print(f"  {line}")
    print(DIM("  ─────────────────────────────────────────────────────"))

    # ════════════════════════════════════════════════════════════════════════
    # STAGE 4 — PAYMENT
    # ════════════════════════════════════════════════════════════════════════
    _section(4, "PAYMENT")
    payment_result = payment.run(invoice, approval_result)

    status_icon = GREEN("✓") if payment_result.processed else RED("✗")
    _row("Status:", f"{status_icon}  {payment_result.status.upper()}")
    print(f"\n  {payment_result.message}")

    # ════════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ════════════════════════════════════════════════════════════════════════
    elapsed = time.time() - t_start
    print()
    print("=" * WIDTH)
    print(f"  {BOLD('PROCESSING COMPLETE')}  {DIM(f'({elapsed:.1f}s)')}")
    outcome = (
        GREEN("✓ PAID") if payment_result.processed else RED("✗ REJECTED")
    )
    print(f"  {invoice.invoice_number}  {invoice.vendor}  "
          f"${invoice.total:,.2f}  →  {BOLD(outcome)}")
    print("=" * WIDTH)
    print()

    return 0 if payment_result.processed else 1


if __name__ == "__main__":
    sys.exit(main())
