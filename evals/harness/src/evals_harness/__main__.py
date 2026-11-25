"""Run the scenarios and write a report.

cd evals/harness
uv run --env-file ../../.env python -m evals_harness --target baseline --repeat 3
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime

import psycopg
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent.settings import get_settings
from evals_harness.report import markdown
from evals_harness.runner import load_scenarios, run_all
from evals_harness.truth import REPO_ROOT, load_manifest


class DbSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EVAL_DB_", extra="ignore")
    host: str = "localhost"
    port: int = 5433
    name: str = "northstar"
    user: str
    password: SecretStr


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Northstar scenarios.")
    parser.add_argument("--target", choices=["baseline", "servers"], default="baseline")
    parser.add_argument("--repeat", type=int, default=3, help="attempts per scenario")
    parser.add_argument("--only", nargs="*", help="scenario IDs, e.g. S2 S5")
    parser.add_argument("--report", help="report name (default: the target name)")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    settings = get_settings().model_copy(update={"target": args.target})
    d = DbSettings()
    manifest = load_manifest()
    with psycopg.connect(
        host=d.host,
        port=d.port,
        dbname=d.name,
        user=d.user,
        password=d.password.get_secret_value(),
        autocommit=True,
    ) as db:
        scenarios = load_scenarios(manifest, set(args.only) if args.only else None)
        results = asyncio.run(run_all(db, manifest, scenarios, settings, args.repeat))

    name = args.report or args.target
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    title = {"baseline": "Baseline (insecure) results"}.get(name, f"{name} results")
    reports = REPO_ROOT / "evals" / "reports"
    (reports / f"{name}.md").write_text(
        markdown(results, title, args.target, settings.model, when), encoding="utf-8"
    )
    raw = [
        {
            "scenario": r.scenario.id,
            "attempt": r.attempt,
            "error": r.error,
            "succeeded": r.succeeded,
            "violations": [asdict(v) for v in r.violations],
            "run": asdict(r.run) if r.run else None,
        }
        for r in results
    ]
    (reports / f"{name}.json").write_text(json.dumps(raw, indent=2, default=str), encoding="utf-8")
    print(f"wrote evals/reports/{name}.md and {name}.json")


if __name__ == "__main__":
    main()
