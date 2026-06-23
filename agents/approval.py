"""
Approval Agent — simulates VP-level invoice review with tiered logic.

Tiers:
  AUTO    total < $5,000 AND no validation errors → immediate approval
  STANDARD $5,000 ≤ total ≤ $10,000 → single LLM review
  HIGH     total > $10,000 → LLM propose → critique → final decision loop

The LLM sees the full validation report so it can weigh issues in context.
"""
import os
from dataclasses import dataclass

import anthropic

from models import InvoiceData
from agents.validation import ValidationResult

MODEL = "claude-opus-4-8"
AUTO_THRESHOLD = 5_000.0
HIGH_VALUE_THRESHOLD = 10_000.0

_SYSTEM_PROMPT = (
    "You are the VP of Finance at Acme Corp, a PE-backed manufacturing firm. "
    "Your job is to approve or reject vendor invoices. You care about:\n"
    "  • Fraud signals (suspicious vendors, pressure tactics, impossible items)\n"
    "  • Data integrity (negative quantities, math errors, missing due dates)\n"
    "  • Stock availability (over-ordering creates waste and cash flow problems)\n"
    "  • Business legitimacy (unknown products may indicate fictitious invoices)\n\n"
    "Be concise and direct. End your response with a decision line containing "
    "ONLY the word APPROVE or REJECT."
)


@dataclass
class ApprovalResult:
    approved: bool
    reasoning: str
    tier: str   # "auto" | "standard" | "high_value"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _build_invoice_brief(invoice: InvoiceData, validation: ValidationResult) -> str:
    items_str = "\n".join(
        f"    {li.item:20s}  qty={li.quantity:>6.0f}  "
        f"@${li.unit_price:>9.2f}  = ${li.line_total:>10.2f}"
        for li in invoice.line_items
    )
    issues_str = "\n".join(
        f"    [{i.severity.upper():7s}] {i.field}: {i.message}"
        for i in validation.issues
    ) or "    None"

    return (
        f"Invoice:        {invoice.invoice_number}\n"
        f"Vendor:         {invoice.vendor}\n"
        f"Date:           {invoice.date}  /  Due: {invoice.due_date}\n"
        f"Currency:       {invoice.currency}\n"
        f"Payment Terms:  {invoice.payment_terms}\n"
        f"\nLine Items:\n{items_str}\n"
        f"\nSubtotal: ${invoice.subtotal:,.2f}  "
        f"Tax: ${invoice.tax_amount:,.2f}  "
        f"TOTAL: ${invoice.total:,.2f}\n"
        f"\nValidation Issues:\n{issues_str}"
    )


def _llm_review(
    client: anthropic.Anthropic,
    brief: str,
    prior_reasoning: str = "",
) -> str:
    """
    Ask Claude to review the invoice and return reasoning ending with APPROVE or REJECT.
    If prior_reasoning is provided, this is a critique pass.
    """
    if prior_reasoning:
        user_msg = (
            "A colleague reviewed this invoice and produced the reasoning below. "
            "Critically evaluate their reasoning for any gaps, biases, or overlooked risks. "
            "Then provide your own final assessment and decision.\n\n"
            f"=== Invoice Brief ===\n{brief}\n\n"
            f"=== Colleague's Reasoning ===\n{prior_reasoning}\n\n"
            "Your critique and final decision:"
        )
    else:
        user_msg = (
            f"Review this invoice and provide your approval decision.\n\n"
            f"=== Invoice Brief ===\n{brief}\n\n"
            "Your assessment and decision:"
        )

    with client.messages.stream(
        model=MODEL,
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        response = stream.get_final_message()

    for block in response.content:
        if block.type == "text":
            return block.text.strip()

    return "REJECT"


def _parse_decision(text: str) -> bool:
    """Parse APPROVE/REJECT from the last few non-empty lines of the response."""
    for line in reversed(text.strip().splitlines()):
        line = line.strip().upper()
        if not line:
            continue
        if "APPROVE" in line and "REJECT" not in line:
            return True
        if "REJECT" in line:
            return False
    return False


# ── Public entry point ───────────────────────────────────────────────────────

def run(invoice: InvoiceData, validation: ValidationResult) -> ApprovalResult:
    """Run tiered approval logic and return an ApprovalResult."""
    total = invoice.total
    brief = _build_invoice_brief(invoice, validation)

    # ── Tier: AUTO ──────────────────────────────────────────────────────────
    if total < AUTO_THRESHOLD and validation.passed:
        print(
            f"  [Approval] Auto-approved "
            f"(${total:,.2f} < ${AUTO_THRESHOLD:,.0f} threshold, no errors)"
        )
        return ApprovalResult(
            approved=True,
            reasoning=(
                f"Auto-approved: total ${total:,.2f} is below the ${AUTO_THRESHOLD:,.0f} "
                f"threshold and all validation checks passed."
            ),
            tier="auto",
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable is not set")
    client = anthropic.Anthropic(api_key=api_key)

    # ── Tier: STANDARD ──────────────────────────────────────────────────────
    if total <= HIGH_VALUE_THRESHOLD:
        print(f"  [Approval] Standard LLM review (${total:,.2f})...")
        reasoning = _llm_review(client, brief)
        approved = _parse_decision(reasoning)
        return ApprovalResult(approved=approved, reasoning=reasoning, tier="standard")

    # ── Tier: HIGH VALUE ────────────────────────────────────────────────────
    print(f"  [Approval] High-value critique loop (${total:,.2f} > ${HIGH_VALUE_THRESHOLD:,.0f})...")
    print("  [Approval] Step 1: Initial review...")
    initial = _llm_review(client, brief)

    print("  [Approval] Step 2: Independent critique...")
    critique = _llm_review(client, brief, prior_reasoning=initial)

    approved = _parse_decision(critique)
    combined = (
        "=== Initial Review ===\n"
        f"{initial}\n\n"
        "=== Independent Critique & Final Decision ===\n"
        f"{critique}"
    )
    return ApprovalResult(approved=approved, reasoning=combined, tier="high_value")
