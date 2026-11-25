"""Ask the agent something as a given user.

uv run --env-file ../../.env python -m agent --user rep1 "Summarise my overdue invoices"
uv run --env-file ../../.env python -m agent --user rep1 --target servers "..."
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from agent.graph import run_agent
from agent.identities import USERS
from agent.settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Northstar agent once.")
    parser.add_argument("prompt")
    parser.add_argument("--user", required=True, choices=sorted(USERS))
    parser.add_argument("--target", choices=["baseline", "servers"])
    parser.add_argument("--json", action="store_true", help="print the full run as JSON")
    args = parser.parse_args()

    settings = get_settings()
    if args.target:
        settings = settings.model_copy(update={"target": args.target})
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    run = asyncio.run(run_agent(args.user, args.prompt, settings))

    if args.json:
        print(json.dumps(asdict(run), indent=2, default=str))
        return
    for step in run.steps:
        flag = " (error)" if step.is_error else ""
        print(f"- {step.tool}({json.dumps(step.args)}){flag}")
    print(f"\n{run.answer}\n")
    print(
        f"[{run.target} | {run.user} | {len(run.steps)} tool calls | {run.stopped} | "
        f"{run.input_tokens} in / {run.output_tokens} out tokens]"
    )


if __name__ == "__main__":
    main()
