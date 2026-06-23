"""
Validation Agent — deterministic checks against the inventory database.

Checks performed:
  - Vendor name present
  - Total amount is positive
  - At least one line item exists
  - Each line item: non-negative quantity, positive unit price
  - Per-item aggregated quantity does not exceed available stock
  - Items exist in inventory (flags unknowns and zero-stock items)
  - Math integrity: subtotal + tax ≈ total
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import List

from models import InvoiceData
from tools.db import get_item_stock


@dataclass
class ValidationIssue:
    severity: str   # "error" | "warning"
    field: str
    message: str


@dataclass
class ValidationResult:
    passed: bool        # True iff no errors (warnings are allowed)
    issues: List[ValidationIssue]

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def summary(self) -> str:
        if self.passed and not self.warnings:
            return "All checks passed"
        parts = []
        if self.errors:
            parts.append(f"{len(self.errors)} error(s)")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning(s)")
        prefix = "PASSED with" if self.passed else "FAILED —"
        return f"{prefix} {', '.join(parts)}"


def run(invoice: InvoiceData, db_path: str = "") -> ValidationResult:
    """Validate invoice data against the inventory database."""
    issues: List[ValidationIssue] = []

    # ── Basic field checks ──────────────────────────────────────────────────
    if not invoice.vendor or invoice.vendor.strip() in ("", "UNKNOWN"):
        issues.append(ValidationIssue(
            severity="error",
            field="vendor",
            message="Vendor name is missing or unknown",
        ))

    if not invoice.line_items:
        issues.append(ValidationIssue(
            severity="error",
            field="line_items",
            message="Invoice contains no line items",
        ))

    if invoice.total <= 0:
        issues.append(ValidationIssue(
            severity="error",
            field="total",
            message=f"Total amount is non-positive: {invoice.total}",
        ))

    # ── Per-line-item checks ────────────────────────────────────────────────
    # Track aggregated quantity per item for stock comparison
    aggregated: dict = defaultdict(float)

    for li in invoice.line_items:
        if li.quantity <= 0:
            issues.append(ValidationIssue(
                severity="error",
                field=f"{li.item}.quantity",
                message=f"'{li.item}' has non-positive quantity: {li.quantity}",
            ))
        else:
            aggregated[li.item] += li.quantity

        if li.unit_price <= 0:
            issues.append(ValidationIssue(
                severity="error",
                field=f"{li.item}.unit_price",
                message=f"'{li.item}' has non-positive unit price: {li.unit_price}",
            ))

    # ── Inventory checks (on aggregated quantities) ─────────────────────────
    kwargs = {"db_path": db_path} if db_path else {}
    for item_name, total_qty in aggregated.items():
        stock = get_item_stock(item_name, **kwargs)

        if stock is None:
            issues.append(ValidationIssue(
                severity="error",
                field=f"{item_name}.inventory",
                message=f"'{item_name}' is not found in inventory — unknown item",
            ))
        elif stock == 0:
            issues.append(ValidationIssue(
                severity="error",
                field=f"{item_name}.stock",
                message=f"'{item_name}' is out of stock (0 units available)",
            ))
        elif total_qty > stock:
            issues.append(ValidationIssue(
                severity="warning",
                field=f"{item_name}.stock",
                message=(
                    f"'{item_name}' requests {total_qty:.0f} units "
                    f"but only {stock} in stock"
                ),
            ))

    # ── Math integrity check ────────────────────────────────────────────────
    computed = invoice.subtotal + invoice.tax_amount
    if abs(computed - invoice.total) > 1.00:
        issues.append(ValidationIssue(
            severity="warning",
            field="total",
            message=(
                f"Total mismatch: subtotal {invoice.subtotal:.2f} + "
                f"tax {invoice.tax_amount:.2f} = {computed:.2f} "
                f"but invoice total is {invoice.total:.2f}"
            ),
        ))

    has_errors = any(i.severity == "error" for i in issues)
    return ValidationResult(passed=not has_errors, issues=issues)
