"""Security rule 10: identity comes from the request, and anything doubtful is denied."""

from uuid import UUID

import pytest

from mcp_crm.auth import Identity, Unauthenticated, identity_from_headers

REP1 = "5e1f0000-0000-4000-8000-000000000001"


def test_valid_headers_give_identity() -> None:
    identity = identity_from_headers({"x-dev-user": REP1, "x-dev-role": "sales_rep"}, dev_auth=True)
    assert identity == Identity(user_id=UUID(REP1), role="sales_rep")


def test_header_names_are_case_insensitive() -> None:
    identity = identity_from_headers(
        {"X-Dev-User": REP1, "X-DEV-ROLE": "finance_analyst"}, dev_auth=True
    )
    assert identity.role == "finance_analyst"


def test_dev_auth_off_denies_even_valid_headers() -> None:
    with pytest.raises(Unauthenticated):
        identity_from_headers({"x-dev-user": REP1, "x-dev-role": "sales_rep"}, dev_auth=False)


@pytest.mark.parametrize(
    "headers",
    [
        None,  # stdio transport: no headers at all
        {},
        {"x-dev-role": "sales_rep"},  # no user
        {"x-dev-user": REP1},  # no role
        {"x-dev-user": "rep1", "x-dev-role": "sales_rep"},  # username, not a UUID
        {"x-dev-user": REP1.replace("-", ""), "x-dev-role": "sales_rep"},  # non-canonical
        {"x-dev-user": f"{{{REP1}}}", "x-dev-role": "sales_rep"},  # braces form
        {"x-dev-user": REP1, "x-dev-role": "admin"},  # unknown role
        {"x-dev-user": REP1, "x-dev-role": "SALES_REP"},  # roles are exact
        {"x-dev-user": REP1, "x-dev-role": ""},
    ],
)
def test_doubtful_headers_are_denied(headers: dict[str, str] | None) -> None:
    with pytest.raises(Unauthenticated):
        identity_from_headers(headers, dev_auth=True)


def test_error_message_does_not_say_what_was_wrong() -> None:
    with pytest.raises(Unauthenticated, match="^unauthenticated$"):
        identity_from_headers({"x-dev-user": REP1, "x-dev-role": "admin"}, dev_auth=True)
