"""The five demo users. Phase 5 replaces this with a Keycloak sign-in that yields a token."""

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    username: str
    user_id: str  # fixed UUIDs from the seed (data/seed/seed.py)
    role: str
    description: str


USERS: dict[str, User] = {
    u.username: u
    for u in (
        User("rep1", "5e1f0000-0000-4000-8000-000000000001", "sales_rep", "a sales rep"),
        User("rep2", "5e1f0000-0000-4000-8000-000000000002", "sales_rep", "a sales rep"),
        User("rep3", "5e1f0000-0000-4000-8000-000000000003", "sales_rep", "a sales rep"),
        User(
            "finance1",
            "5e1f0000-0000-4000-8000-000000000004",
            "finance_analyst",
            "a finance analyst",
        ),
        User("contractor1", "5e1f0000-0000-4000-8000-000000000005", "contractor", "a contractor"),
    )
}
