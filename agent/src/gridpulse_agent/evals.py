"""Golden-set evaluation, in two modes.

Planner (default, the PR gate): does the planner turn each question into the expected metric
request? Scoring compares the planned request with the expected one (route, metrics, group-by,
filters, window). It's deterministic and cheap: no answer text is judged. PRs that touch agent/
or semantic/ must keep the pass rate at or above 90%.

End to end (`--e2e`, nightly): runs the full graph against the live semantic API, as a user
would, and records per case the final status, whether the request was right, and whether the
number check failed first time (a rewrite or the table fallback). A case passes when the request
is right and the answer went out grounded (or as "no data" for a right request).

Case kinds in golden.yaml:
- `expect`: the request the question should produce;
- `clarify: true`: an ambiguous question, which must get a clarifying question instead;
- `after: <case id>`: a follow-up, asked in the same conversation after that case.

Scores are stored in the agent's Postgres database (table eval_runs) when
GRIDPULSE_AGENT_CHECKPOINT_DSN is set, so nightly results are kept.

    uv run gridpulse-agent-eval            # needs a model provider and the semantic API
    uv run gridpulse-agent-eval --e2e
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

from gridpulse_agent import clarify
from gridpulse_agent.brain import Brain, LLMBrain
from gridpulse_agent.config import AgentSettings
from gridpulse_agent.contract import MetricRequest
from gridpulse_agent.graph import ask, build_graph
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
    clarify: bool = False
    after: str | None = None


def load_cases(path: Path = GOLDEN) -> tuple[date, list[Case]]:
    doc = yaml.safe_load(path.read_text())
    cases = [
        Case(
            c["id"],
            c["question"],
            c.get("route", "metric"),
            c.get("expect"),
            c.get("clarify", False),
            c.get("after"),
        )
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


def expected_request(expected: dict) -> dict:
    """An expectation as a request body, for a follow-up's history."""
    window = {k: f"{expected[k]}T00:00:00Z" for k in ("start", "end")}
    keep = {k: v for k, v in expected.items() if k in ("metrics", "group_by", "filters")}
    return {**keep, **window}


def _summary(results: list[dict], **extra) -> dict:
    passed = sum(r["passed"] for r in results)
    return {
        "passed": passed,
        "total": len(results),
        "pass_rate": passed / len(results),
        **extra,
        "cases": results,
    }


def run(
    brain: Brain, semantic: SemanticClient, settings: AgentSettings, path: Path = GOLDEN
) -> dict:
    """Planner mode: one plan per question (plus the retry the graph would allow)."""
    today, cases = load_cases(path)
    by_id = {c.id: c for c in cases}
    catalog, bas = semantic.catalog(), semantic.balancing_authorities()
    saved, regions = semantic.saved_queries(), semantic.ba_regions()
    results = []
    for case in cases:
        reasons: list[str] = []
        history = []
        if case.after:
            earlier = by_id[case.after]
            history = [
                {"question": earlier.question, "request": expected_request(earlier.expected)}
            ]

        def plan(errors=(), previous=None, case=case, history=history):
            return brain.plan(
                case.question, catalog, bas, today, list(errors), previous, saved, history
            )

        try:
            route = brain.route(case.question, history).route
            if route != case.route:
                reasons.append(f"route {route} != {case.route}")
            elif case.route == "metric":
                planned = plan()
                errors = validate(
                    planned,
                    catalog,
                    max_window_days=settings.max_window_days,
                    max_rows=settings.max_rows,
                )
                if errors:  # the graph would retry with these errors; give the planner the same
                    planned = plan(errors, planned)
                # The same two sources of a clarifying question as the graph's ambiguity step.
                question = clarify.region_question(case.question, planned, regions) or getattr(
                    planned, "clarify", None
                )
                if case.clarify:
                    if not question:
                        reasons.append("should have asked a clarifying question")
                else:
                    if question:
                        reasons.append(f"asked to clarify: {question}")
                    reasons += score(planned, case.expected)
        except Exception as exc:  # a crash is a failed case, not a failed run
            reasons.append(f"{type(exc).__name__}: {exc}")
        results.append({"id": case.id, "passed": not reasons, "reasons": reasons})
    return _summary(results)


def run_e2e(
    brain: Brain, semantic: SemanticClient, settings: AgentSettings, path: Path = GOLDEN
) -> dict:
    """End-to-end mode: the full graph, as a user would ask, one conversation per case."""
    today, cases = load_cases(path)
    by_id = {c.id: c for c in cases}
    graph = build_graph(brain, semantic, settings)  # in-memory checkpoints: runs don't mix
    results = []
    for case in cases:
        reasons: list[str] = []
        out: dict = {}
        try:
            thread = None
            if case.after:  # the earlier question first, in the same conversation
                thread = ask(graph, by_id[case.after].question, today)["thread_id"]
            out = ask(graph, case.question, today, thread)
            status = out["status"]
            if case.clarify:
                if status != "needs_clarification":
                    reasons.append(f"status {status} != needs_clarification")
            elif case.route != "metric":
                if status != case.route:
                    reasons.append(f"status {status} != {case.route}")
            else:
                if status not in ("answered", "no_data"):
                    reasons.append(f"status {status}")
                if out["metric_request"]:
                    reasons += score(MetricRequest(**out["metric_request"]), case.expected)
        except Exception as exc:
            reasons.append(f"{type(exc).__name__}: {exc}")
        # A rewrite or the table fallback: the first answer had a number not in the data.
        ground_failed = bool(out.get("rewrites")) or out.get("status") == "fallback_table"
        results.append(
            {
                "id": case.id,
                "passed": not reasons,
                "reasons": reasons,
                "status": out.get("status"),
                "ground_check_failed": ground_failed,
                "rejected_numbers": out.get("rejected_numbers", []),
            }
        )
    return _summary(results, ground_check_failures=sum(r["ground_check_failed"] for r in results))


def store(dsn: str, mode: str, settings: AgentSettings, report: dict) -> None:
    """One row per run in the agent database, for trends (nightly accuracy, ...)."""
    import psycopg  # only needed where scores are stored
    from psycopg.types.json import Jsonb

    router, planner = settings.models()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS eval_runs (
                run_at timestamptz NOT NULL,
                mode text NOT NULL,
                provider text NOT NULL,
                router_model text NOT NULL,
                planner_model text NOT NULL,
                passed integer NOT NULL,
                total integer NOT NULL,
                pass_rate double precision NOT NULL,
                ground_check_failures integer,
                report jsonb NOT NULL
            )"""
        )
        conn.execute(
            "INSERT INTO eval_runs VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                datetime.now(UTC),
                mode,
                settings.provider,
                router,
                planner,
                report["passed"],
                report["total"],
                report["pass_rate"],
                report.get("ground_check_failures"),
                Jsonb(report),
            ),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the agent on the golden question set.")
    parser.add_argument("--e2e", action="store_true", help="run the full graph (nightly)")
    args = parser.parse_args(argv)
    settings = AgentSettings()
    brain, semantic = LLMBrain.from_settings(settings), SemanticClient(settings.semantic_api_url)
    report = (run_e2e if args.e2e else run)(brain, semantic, settings)
    for case in report["cases"]:
        mark = "PASS" if case["passed"] else "FAIL"
        print(
            f"{mark}  {case['id']}"
            + ("" if case["passed"] else f"  -> {'; '.join(case['reasons'])}")
        )
    keys = ("passed", "total", "pass_rate", "ground_check_failures")
    print(json.dumps({k: report[k] for k in keys if k in report}))
    if settings.checkpoint_dsn is not None:
        mode = "e2e" if args.e2e else "planner"
        store(settings.checkpoint_dsn.get_secret_value(), mode, settings, report)
    return 0 if report["pass_rate"] >= PASS_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
