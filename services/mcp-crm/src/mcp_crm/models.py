"""Tool inputs and outputs. The return types become each tool's output schema."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from northstar_common.untrusted import UntrustedText

__all__ = ["UntrustedText"]  # re-exported for server.py

AccountStatus = Literal["active", "on_hold", "closed"]
AccountId = Annotated[str, Field(pattern=r"^ACC-\d{4}$", description="Account ID, e.g. ACC-0001")]
SearchText = Annotated[
    str | None,
    Field(max_length=100, description="Text to match in the account name or ID"),
]


class AccountSummary(BaseModel):
    id: str
    name: str
    region: str
    status: AccountStatus


class SearchAccountsResult(BaseModel):
    accounts: list[AccountSummary]
    truncated: bool = Field(description="True if more accounts matched than were returned")


class Account(AccountSummary):
    owner_username: str
    notes: UntrustedText | None


class Contact(BaseModel):
    id: str
    name: str
    email: str
    phone: str | None
    is_billing: bool


class ContactList(BaseModel):
    account_id: str
    contacts: list[Contact]
