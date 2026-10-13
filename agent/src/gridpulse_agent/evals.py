"""Golden-set evaluation: does the planner turn each question into the expected metric request?

Scoring compares the planned request with the expected one (route, metrics, group-by, filters,
window). It's deterministic and cheap: no answer text is judged. PRs that touch agent/ or
semantic/ must keep the pass rate at or above 90%.

    uv run gridpulse-agent-eval            # needs a model provider and the semantic API
"""

import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from gridpulse_agent.brain import Brain, LLMBrain
from gridpulse_agent.config import AgentSettings
from gridpulse_agent.contract import MetricRequest
from gridpulse_agent.semantic_client import SemanticClient
from gridpulse_agent.validate import validate

# From the source tree by default; the image installs the package into a venv and copies the
# golden set elsewhere, so it points GRIDPULSE_AGENT_GOLDEN_SET at the copy.
GOLDEN = Path(
    os.environ.get(
        "GRIDPULSE_AGENT_GOLDEN_SET", Path(__file__).resolve().parents[2] / "evals" / "golden.yaml"
    )
)
PASS_RATE = 0.9


@dataclass
class Case:
    id: str
    question: str
    route: str
    expected: dict | None


def load_cases(path: Path = GOLDEN) -> tuple[date, list[Case]]:
    doc = yaml.safe_load(path.read_text())
    cases = [
        Case(c["id"], c["question"], c.get("route", "metric"), c.get("expect"))
        for c in doc["cases"]
    ]
    return date.fromisoformat(str(doc["today"])), cases


def _filters(items) -> set:
    return {(f["dimension"], f.get("op", "="), tuple(sorted(f["values"]))) for f in items}


def score(planned: MetricRequest, expected: dict) -> list[str]:
    """Reasons the plan differs from the expectation (empty = pass)."""
    reasons = []
    if set(planned.metrics) != set(expected["metrics"]):
        reasons.append(f"metrics {planned.metrics} != {expected['metrics']}")
    if set(planned.group_by) != set(expected.get("group_by", [])):
        reasons.append(f"group_by {planned.group_by} != {expected.get('group_by', [])}")
    got_filters = _filters(f.model_dump() for f in planned.filters)
    if got_filters != _filters(expected.get("filters", [])):
        reasons.append(
            f"filters {sorted(got_filters)} != {sorted(_filters(expected.get('filters', [])))}"
        )
    start = datetime.fromisoformat(str(expected["start"])).date()
    end = datetime.fromisoformat(str(expected["end"])).date()
    if planned.start.date() != start:
        reasons.append(f"start {planned.start.date()} != {start}")
    # "through today" vs "up to today" are both reasonable readings of open-ended windows.
    if abs(planned.end.date() - end) > timedelta(days=expected.get("end_tolerance_days", 0)):
        reasons.append(f"end {planned.end.date()} != {end}")
    return reasons


def run(brain: Brain, semantic: SemanticClient, settings: AgentSettings) -> dict:
    today, cases = load_cases()
    catalog, bas = semantic.catalog(), semantic.balancing_authorities()
    saved = semantic.saved_queries()
    results = []
    for case in cases:
        reasons: list[str] = []
        try:
            route = brain.route(case.question).route
            if route != case.route:
                reasons.append(f"route {route} != {case.route}")
            elif case.route == "metric":
                planned = brain.plan(case.question, catalog, bas, today, [], None, saved)
                errors = validate(
                    planned,
                    catalog,
                    max_window_days=settings.max_window_days,
                    max_rows=settings.max_rows,
                )
                if (
                    errors
                ):  # the graph would retry with these errors; give the planner the same chance
                    planned = brain.plan(case.question, catalog, bas, today, errors, planned, saved)
                if getattr(planned, "clarify", None):  # golden questions are unambiguous
                    reasons.append(f"asked to clarify: {planned.clarify}")
                reasons += score(planned, case.expected)
        except Exception as exc:  # a crash is a failed case, not a failed run
            reasons.append(f"{type(exc).__name__}: {exc}")
        results.append({"id": case.id, "passed": not reasons, "reasons": reasons})
    passed = sum(r["passed"] for r in results)
    return {
        "passed": passed,
        "total": len(results),
        "pass_rate": passed / len(results),
        "cases": results,
    }


def main() -> int:
    settings = AgentSettings()
    report = run(
        LLMBrain.from_settings(settings), SemanticClient(settings.semantic_api_url), settings
    )
    for case in report["cases"]:
        mark = "PASS" if case["passed"] else "FAIL"
        print(
            f"{mark}  {case['id']}"
            + ("" if case["passed"] else f"  -> {'; '.join(case['reasons'])}")
        )
    print(json.dumps({k: report[k] for k in ("passed", "total", "pass_rate")}))
    return 0 if report["pass_rate"] >= PASS_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
