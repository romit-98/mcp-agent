"""Tool inputs and outputs. Money is Decimal end to end, never float."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

InvoiceStatus = Literal["open", "paid", "overdue"]
CreditNoteStatus = Literal["pending_approval", "approved", "rejected"]
AccountId = Annotated[str, Field(pattern=r"^ACC-\d{4}$", description="Account ID, e.g. ACC-0001")]
InvoiceId = Annotated[str, Field(pattern=r"^INV-\d{4}$", description="Invoice ID, e.g. INV-1042")]
Amount = Annotated[
    Decimal,
    Field(gt=0, max_digits=12, decimal_places=2, description="Dollars, e.g. 500 or 500.00"),
]
Reason = Annotated[str, Field(min_length=3, max_length=500, description="Why the credit is due")]


class InvoiceSummary(BaseModel):
    id: str
    account_id: str
    amount: Decimal
    due_date: date
    status: InvoiceStatus


class InvoiceList(BaseModel):
    invoices: list[InvoiceSummary]
    truncated: bool = Field(description="True if more invoices matched than were returned")


class Invoice(InvoiceSummary):
    account_name: str
    bank_ref: str = Field(description="Payment details. Sensitive: redacted by the gateway.")


class CreditNote(BaseModel):
    id: UUID
    invoice_id: str
    amount: Decimal
    reason: str
    status: CreditNoteStatus
    requested_by: UUID
    created_at: datetime
    message: str = "Drafted and pending approval. Nothing has been issued to the customer."
