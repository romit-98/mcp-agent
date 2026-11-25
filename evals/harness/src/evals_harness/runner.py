"""Run every scenario against the agent, record writes, detect violations, clean up."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
import yaml

from agent.graph import AgentRun, run_agent
from agent.settings import Settings
from evals_harness.detect import Violation, Writes, find_violations, task_succeeded
from evals_harness.truth import REPO_ROOT, UserTruth, bank_ref_pattern, user_truth

SCENARIO_DIR = REPO_ROOT / "evals" / "scenarios"


@dataclass
class Scenario:
    id: str
    title: str
    category: str  # legitimate | leakage | injection | approval
    user: str
    prompt: str
    allowed_writes: str
    success: str


@dataclass
class Result:
    scenario: Scenario
    attempt: int
    run: AgentRun | None
    violations: list[Violation] = field(default_factory=list)
    succeeded: bool = False
    error: str | None = None


def _fill(text: str, refs: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: refs[m.group(1)], text)


def load_scenarios(manifest: dict[str, Any], only: set[str] | None = None) -> list[Scenario]:
    refs = manifest["scenario_refs"]
    out = []
    for path in sorted(Path(SCENARIO_DIR).glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if only and raw["id"] not in only:
            continue
        out.append(
            Scenario(
                id=raw["id"],
                title=raw["title"],
                category=raw["category"],
                user=raw["user"],
                prompt=_fill(raw["prompt"], refs),
                allowed_writes=raw.get("allowed_writes", "none"),
                success=_fill(raw.get("success", "no_violations"), refs),
            )
        )
    return out


def _high_water(db: psycopg.Connection) -> tuple[int, set[str]]:
    outbox = db.execute("SELECT COALESCE(MAX(id), 0) FROM email.outbox").fetchone()[0]
    notes = {str(r[0]) for r in db.execute("SELECT id FROM finance.credit_notes").fetchall()}
    return outbox, notes


def _writes_since(db: psycopg.Connection, outbox_max: int, notes_before: set[str]) -> Writes:
    with db.cursor(row_factory=psycopg.rows.dict_row) as cur:
        emails = cur.execute(
            "SELECT id, to_address, subject FROM email.outbox WHERE id > %s ORDER BY id",
            (outbox_max,),
        ).fetchall()
        notes = [
            n
            for n in cur.execute(
                "SELECT id, invoice_id, amount, status FROM finance.credit_notes"
            ).fetchall()
            if str(n["id"]) not in notes_before
        ]
    return Writes(emails=emails, credit_notes=notes)


def _undo(db: psycopg.Connection, writes: Writes) -> None:
    """Put the database back so every attempt starts from the same state."""
    if writes.emails:
        db.execute(
            "DELETE FROM email.outbox WHERE id = ANY(%s)", ([e["id"] for e in writes.emails],)
        )
    if writes.credit_notes:
        db.execute(
            "DELETE FROM finance.credit_notes WHERE id = ANY(%s)",
            ([n["id"] for n in writes.credit_notes],),
        )


async def run_all(
    db: psycopg.Connection,
    manifest: dict[str, Any],
    scenarios: list[Scenario],
    settings: Settings,
    repeat: int,
    progress: Any = print,
) -> list[Result]:
    truths: dict[str, UserTruth] = {}
    bank_ref = bank_ref_pattern(manifest)
    results: list[Result] = []
    for scenario in scenarios:
        truth = truths.setdefault(scenario.user, user_truth(db, manifest, scenario.user))
        for attempt in range(1, repeat + 1):
            outbox_max, notes_before = _high_water(db)
            result = Result(scenario, attempt, None)
            try:
                result.run = await run_agent(scenario.user, scenario.prompt, settings)
            except Exception as exc:  # noqa: BLE001 - recorded, the run continues
                result.error = f"{type(exc).__name__}: {exc}"
            writes = _writes_since(db, outbox_max, notes_before)
            if result.run is not None:
                result.violations = find_violations(
                    result.run, truth, writes, scenario.allowed_writes, bank_ref
                )
                result.succeeded = task_succeeded(scenario.success, result.run, truth, writes)
            _undo(db, writes)
            results.append(result)
            kinds = ", ".join(sorted({v.kind for v in result.violations})) or "none"
            progress(
                f"{scenario.id} #{attempt}: violations={kinds}"
                f"{' ERROR ' + result.error if result.error else ''}"
            )
    return results
