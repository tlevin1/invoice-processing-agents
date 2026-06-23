#!/usr/bin/env python3
"""
Run every invoice in data/invoices/ through the full pipeline.
Shows live progress then a summary table.

Usage:
    python3 run_all.py
"""
import contextlib
import io
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RunResult:
    fname: str
    invoice_number: str = "?"
    vendor: str = "?"
    total: float = 0.0
    currency: str = "USD"
    val_passed: bool = False
    val_errors: int = 0
    val_warnings: int = 0
    tier: str = "?"
    approved: bool = False
    elapsed: float = 0.0
    error: Optional[str] = None
    log: str = ""


@contextlib.contextmanager
def _capture_output():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield buf


def process_invoice(path: str) -> RunResult:
    from tools.file_reader import read_invoice
    from agents import ingestion, validation, approval, payment

    result = RunResult(fname=Path(path).name)
    t = time.time()
    try:
        with _capture_output() as log:
            content, _ = read_invoice(path)
            inv = ingestion.run(content, source_path=path)
            val = validation.run(inv)
            app = approval.run(inv, val)
            pay = payment.run(inv, app)

        result.log = log.getvalue()
        result.invoice_number = inv.invoice_number
        result.vendor = inv.vendor[:22]
        result.total = inv.total
        result.currency = inv.currency
        result.val_passed = val.passed
        result.val_errors = len(val.errors)
        result.val_warnings = len(val.warnings)
        result.tier = app.tier
        result.approved = app.approved
    except Exception as exc:
        result.error = str(exc)[:80]

    result.elapsed = time.time() - t
    return result


def _color(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set.")
        return 1

    if not Path("inventory.db").exists():
        print("ERROR: inventory.db not found. Run 'python3 setup_db.py' first.")
        return 1

    invoice_dir = Path("data/invoices")
    files = sorted(
        p for p in invoice_dir.iterdir()
        if p.suffix.lower() in (".txt", ".json", ".csv", ".pdf", ".xml")
    )

    print(f"\nProcessing {len(files)} invoices...\n")

    results: list[RunResult] = []
    for path in files:
        label = path.name
        print(f"  {label:<40}", end=" ", flush=True)
        r = process_invoice(str(path))
        results.append(r)
        if r.error:
            print(_color("31", f"ERROR  ({r.elapsed:.1f}s)"))
        else:
            decision = _color("32", "APPROVED") if r.approved else _color("31", "REJECTED")
            print(f"{decision}  ({r.elapsed:.1f}s)")

    # ── Summary table ──────────────────────────────────────────────────────────
    W = 110
    print()
    print("=" * W)
    print(f"  {'INVOICE':13} {'FILE':38} {'VENDOR':22} {'TOTAL':>12} "
          f"{'VAL':>7} {'TIER':>12} {'DECISION':>10}")
    print("  " + "-" * (W - 2))

    for r in results:
        if r.error:
            print(f"  {'?':13} {r.fname:38} {'ERROR: ' + r.error[:50]}")
            continue

        val_str = (_color("32", "PASS") if r.val_passed else _color("31", "FAIL"))
        if r.val_warnings:
            val_str += _color("33", f"+{r.val_warnings}w")
        if r.val_errors:
            val_str += _color("31", f" {r.val_errors}e")

        decision = _color("32", "APPROVED") if r.approved else _color("31", "REJECTED")

        tier_short = {"auto": "auto", "standard": "standard", "high_value": "high-value"}.get(r.tier, r.tier)

        print(
            f"  {r.invoice_number:13} "
            f"{r.fname:38} "
            f"{r.vendor:22} "
            f"{r.currency} {r.total:>8,.0f}  "
            f"{val_str:>5}  "
            f"{tier_short:>10}  "
            f"{decision}"
        )

    print("  " + "-" * (W - 2))
    approved = sum(1 for r in results if r.approved and not r.error)
    rejected = sum(1 for r in results if not r.approved and not r.error)
    errors   = sum(1 for r in results if r.error)
    total_t  = sum(r.elapsed for r in results)
    print(f"  {_color('32', f'{approved} approved')}  |  "
          f"{_color('31', f'{rejected} rejected')}  |  "
          f"{errors} errors  |  {total_t:.0f}s total")
    print("=" * W)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
