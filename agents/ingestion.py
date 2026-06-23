"""
Ingestion Agent — extracts structured invoice data from raw text.

Uses Claude tool-use (forced) for structured extraction, then runs a
self-critique pass to catch math errors, negative quantities, and missing
fields. Retries extraction up to MAX_RETRIES times if issues are found.
"""
import os
import json

import anthropic

from models import InvoiceData, LineItem

MODEL = "claude-opus-4-8"
MAX_RETRIES = 2

_EXTRACT_TOOL = {
    "name": "extract_invoice",
    "description": (
        "Extract all structured data from an invoice document. "
        "Use null for fields that are genuinely missing or unparseable. "
        "Item names should be normalized: remove spaces between words "
        "(e.g. 'Widget A' → 'WidgetA', 'Gadget X' → 'GadgetX'). "
        "All monetary values must be plain numbers (no currency symbols or commas)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "invoice_number": {
                "type": "string",
                "description": "Invoice/reference number (e.g. 'INV-1001')"
            },
            "vendor": {
                "type": "string",
                "description": "Vendor / supplier name"
            },
            "date": {
                "type": ["string", "null"],
                "description": "Invoice date, YYYY-MM-DD preferred"
            },
            "due_date": {
                "type": ["string", "null"],
                "description": "Payment due date, YYYY-MM-DD preferred"
            },
            "line_items": {
                "type": "array",
                "description": "Every line item on the invoice (one entry per line, even duplicates)",
                "items": {
                    "type": "object",
                    "properties": {
                        "item":       {"type": "string"},
                        "quantity":   {"type": "number"},
                        "unit_price": {"type": "number"},
                    },
                    "required": ["item", "quantity", "unit_price"],
                },
            },
            "subtotal":      {"type": "number", "description": "Pre-tax subtotal"},
            "tax_amount":    {"type": "number", "description": "Tax in currency units (0 if none)"},
            "total":         {"type": "number", "description": "Final total amount due"},
            "payment_terms": {"type": ["string", "null"], "description": "e.g. 'Net 30'"},
            "currency":      {"type": "string",           "description": "ISO currency code, default USD"},
        },
        "required": ["invoice_number", "vendor", "line_items", "subtotal", "tax_amount", "total"],
    },
}


def _extract(client: anthropic.Anthropic, content: str, prior_issues: str = "") -> dict:
    """Call Claude with forced tool use to extract structured invoice fields."""
    preamble = ""
    if prior_issues:
        preamble = (
            f"A previous extraction attempt had these problems — fix them:\n"
            f"{prior_issues}\n\n"
        )

    with client.messages.stream(
        model=MODEL,
        max_tokens=4096,
        tools=[_EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_invoice"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"{preamble}"
                    "Extract every invoice field from the document below. "
                    "Be precise with numbers. Use null for missing fields.\n\n"
                    f"<invoice>\n{content}\n</invoice>"
                ),
            }
        ],
    ) as stream:
        response = stream.get_final_message()

    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_invoice":
            return block.input

    raise RuntimeError("Claude did not return an extract_invoice tool call")


def _critique(client: anthropic.Anthropic, content: str, extracted: dict) -> str:
    """
    Ask Claude to spot data-integrity problems in the extraction.
    Returns "" if extraction looks correct, or a brief description of issues.
    """
    with client.messages.stream(
        model=MODEL,
        max_tokens=512,
        thinking={"type": "adaptive"},
        messages=[
            {
                "role": "user",
                "content": (
                    "You are auditing an invoice data extraction for correctness. "
                    "Check ONLY for these concrete data problems:\n"
                    "1. Any quantity that is zero, negative, or implausibly large\n"
                    "2. subtotal + tax_amount does NOT equal total (allow ±$1 rounding)\n"
                    "3. Vendor name is empty or clearly missing\n"
                    "4. Any unit price that is zero or negative\n\n"
                    f"Original invoice:\n<invoice>\n{content}\n</invoice>\n\n"
                    f"Extracted data:\n{json.dumps(extracted, indent=2)}\n\n"
                    "If the data looks correct, reply with exactly: OK\n"
                    "If there are problems, list them briefly (under 80 words). "
                    "Do not comment on missing optional fields."
                ),
            }
        ],
    ) as stream:
        response = stream.get_final_message()

    for block in response.content:
        if block.type == "text":
            text = block.text.strip()
            return "" if text.upper() == "OK" else text

    return ""


def run(content: str, source_path: str = "") -> InvoiceData:
    """
    Extract structured invoice data from raw text with a self-correction loop.

    Flow:
      1. Extract via forced tool call
      2. Critique the result
      3. If issues found and retries remain, re-extract with critique context
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=api_key)

    print("  [Ingestion] Extracting structured data from invoice...")
    extracted = _extract(client, content)

    for attempt in range(MAX_RETRIES):
        print(f"  [Ingestion] Self-critique pass {attempt + 1}/{MAX_RETRIES}...")
        issues = _critique(client, content, extracted)
        if not issues:
            print("  [Ingestion] Extraction verified — no issues found.")
            break
        print(f"  [Ingestion] Issues detected: {issues}")
        print("  [Ingestion] Re-extracting with correction context...")
        extracted = _extract(client, content, prior_issues=issues)
    else:
        # After all retries, run one final critique for logging but proceed regardless
        final_issues = _critique(client, content, extracted)
        if final_issues:
            print(f"  [Ingestion] Warning: residual issues after {MAX_RETRIES} retries: {final_issues}")
        else:
            print("  [Ingestion] Extraction verified on final pass.")

    line_items = [
        LineItem(
            item=str(li["item"]),
            quantity=float(li["quantity"]),
            unit_price=float(li["unit_price"]),
        )
        for li in extracted.get("line_items", [])
    ]

    return InvoiceData(
        invoice_number=str(extracted.get("invoice_number") or "UNKNOWN"),
        vendor=str(extracted.get("vendor") or "UNKNOWN"),
        date=extracted.get("date"),
        due_date=extracted.get("due_date"),
        line_items=line_items,
        subtotal=float(extracted.get("subtotal") or 0.0),
        tax_amount=float(extracted.get("tax_amount") or 0.0),
        total=float(extracted.get("total") or 0.0),
        payment_terms=extracted.get("payment_terms"),
        currency=str(extracted.get("currency") or "USD"),
        source_path=source_path,
    )
