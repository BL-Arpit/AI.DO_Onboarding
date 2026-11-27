"""Probe actual local model tool use. Does not connect to application databases."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--context", type=int, default=2048)
parser.add_argument("--report")
args = parser.parse_args()
os.environ.update(
    GGUF_MODEL_PATH=args.model, GGUF_CONTEXT_TOKENS=str(args.context), GGUF_THREADS="1"
)
from app.chat import smollm_agent as agent

captured = []
generate = agent._generate


def trace(*a, **kw):
    value = generate(*a, **kw)
    captured.append(value)
    return value


agent._generate = trace
cases = [
    ("add aishwarya in hr", {}, "invite_hr", {"name": "aishwarya"}),
    ("who are all our HR administrators?", {}, "list_hr", {}),
    (
        "her email is aishwarya@example.org",
        {"task_draft": {"tool": "invite_hr", "values": {"name": "Aishwarya"}}},
        "invite_hr",
        {"email": "aishwarya@example.org"},
    ),
]
report = []
for text, state, expected, expected_args in cases:
    started = time.monotonic()
    row = {"request": text, "expected_tool": expected, "expected_arguments": expected_args}
    try:
        result = agent.choose(
            {
                "messages": [],
                "planner_context": {
                    **state,
                    "business": {"role": "owner", "company": "Acme", "company_assigned": True},
                },
            },
            state,
            text,
            "owner",
        )
        values = result.arguments.model_dump(exclude_unset=True)
        row.update(
            tool=result.tool,
            arguments=values,
            passed=result.tool == expected
            and all(
                str(values.get(k, "")).casefold() == v.casefold() for k, v in expected_args.items()
            ),
        )
    except Exception as exc:
        row.update(error=getattr(exc, "detail", type(exc).__name__), passed=False)
    row.update(
        seconds=round(time.monotonic() - started, 2),
        raw_response=captured[-1] if captured else None,
    )
    report.append(row)
if args.report:
    Path(args.report).write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
raise SystemExit(0 if all(row["passed"] for row in report) else 1)
