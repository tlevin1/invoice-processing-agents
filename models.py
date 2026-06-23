from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class LineItem:
    item: str
    quantity: float
    unit_price: float

    @property
    def line_total(self) -> float:
        return self.quantity * self.unit_price


@dataclass
class InvoiceData:
    invoice_number: str
    vendor: str
    date: Optional[str]
    due_date: Optional[str]
    line_items: List[LineItem]
    subtotal: float
    tax_amount: float
    total: float
    payment_terms: Optional[str] = None
    currency: str = "USD"
    source_path: str = ""
