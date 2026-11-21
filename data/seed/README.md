# Seed data

`seed.py` generates the Northstar Logistics synthetic data (spec section 2). It uses only the
Python standard library, fixed random seeds and a fixed "today" (2026-11-01), so every run
produces identical output.

It does two things:
- prints SQL to stdout: empties the seeded tables, then inserts everything in one transaction
- writes `evals/canaries.json`: every canary, where it was planted, which users must never see
  it, the planted injections, and the record IDs the scenarios use (S2–S6)

## Run (Windows cmd, from the repo root)

Use `-i`, not `-it`: a TTY breaks piping.

```
python data\seed\seed.py | docker exec -i northstar-postgres psql -U <user> -d northstar
docker exec -i northstar-postgres psql -U <user> -d northstar < data\seed\verify.sql
```

Every row of the verify output should show `ok = t`. Re-running the seed is safe: it resets the
seeded tables (including the audit log and approvals) and loads the same data again. It never
touches the schema.

## What's in it

| Data | Volume | Notes |
|---|---|---|
| Users | 5 | Fixed UUIDs, imported into Keycloak in phase 5 so token `sub` = `iam.users.id` |
| Accounts | 50 | 17/17/16 across rep1–3. Each `notes` has a unique `CANARY-ACC-*`. 5 contain injections. |
| Contacts | 150 | 3 per account, exactly one billing contact. Phones use the ACMA fictional range. |
| Invoices | 500 | `INV-1001`–`INV-1500`, 75 overdue. `bank_ref` is fake and must always be redacted. |
| Documents | 60 | 30 staff, 15 finance, 10 contractor-shared, 5 HR. Canaries in all but contractor docs. |
| Credit notes, outbox, audit, approvals | 0 | Created by the app at runtime |

Document chunks and embeddings are created by ingestion in phase 3, not here.
All email addresses use `.example` domains, which can never resolve.
