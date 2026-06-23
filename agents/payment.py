"""
Payment Agent — processes approved invoices or logs rejections.

Approved  → calls mock_payment() and returns a success result.
Rejected  → appends a structured record to rejected_invoices.jsonl.
"""
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from models import InvoiceData
from agents.approval import ApprovalResult

REJECTION_LOG = "rejected_invoices.jsonl"


@dataclass
class PaymentResult:
    processed: bool
    status: str     # "success" | "rejected" | "error"
    message: str


def mock_payment(vendor: str, amount: float) -> dict:
    """Simulate a payment API call."""
    print(f"  [Payment] Paying ${amount:,.2f} to '{vendor}'...")
    return {"status": "success", "vendor": vendor, "amount": amount}


def run(invoice: InvoiceData, approval: ApprovalResult) -> PaymentResult:
    """Process payment for an approved invoice, or log the rejection."""
    if not approval.approved:
        _log_rejection(invoice, approval)
        short_reason = approval.reasoning.split("\n")[0][:120]
        return PaymentResult(
            processed=False,
            status="rejected",
            message=f"Invoice {invoice.invoice_number} rejected. Reason: {short_reason}",
        )

    result = mock_payment(invoice.vendor, invoice.total)
    if result.get("status") == "success":
        return PaymentResult(
            processed=True,
            status="success",
            message=(
                f"Payment of ${invoice.total:,.2f} to '{invoice.vendor}' "
                f"processed successfully."
            ),
        )

    return PaymentResult(
        processed=False,
        status="error",
        message=f"Payment API returned unexpected status: {result}",
    )


def _log_rejection(invoice: InvoiceData, approval: ApprovalResult) -> None:
    entry = {
        "timestamp":      datetime.now().isoformat(),
        "invoice_number": invoice.invoice_number,
        "vendor":         invoice.vendor,
        "total":          invoice.total,
        "currency":       invoice.currency,
        "approval_tier":  approval.tier,
        "reasoning":      approval.reasoning,
    }
    log_path = Path(REJECTION_LOG)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"  [Payment] Rejection logged to {log_path}")
