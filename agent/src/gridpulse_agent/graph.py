"""The GridPulse assistant as an explicit LangGraph graph.

    route ─┬─ metric ─> plan ─> validate ─ok─> execute ─> inspect ─> answer ─> ground_check ─> END
           │             ^          │             │            │                     │
           │             └─ errors ─┘ (≤2 retries) │            └─ no rows: END       │
           │                                       └─ API rejects: replan            │
           ├─ definition ─> define ─> END                  unsupported number: rewrite once,
           └─ out_of_scope ─> END                          then fall back to a table

The model only routes, plans and writes. Validation, execution, inspection and the number check
are code, and so are the lines appended to every answer: what the metrics left out (flagged
values) and the inspection's caveats (completeness, latest hour, revision window).
Clarifying questions join in phase B4.
"""

from datetime import UTC, date, datetime
from typing import Any, Literal, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph

from gridpulse_agent import inspection, prompts
from gridpulse_agent.brain import Brain
from gridpulse_agent.config import AgentSettings
from gridpulse_agent.contract import MetricRequest
from gridpulse_agent.ground_check import unsupported_numbers
from gridpulse_agent.semantic_client import SemanticAPIError, SemanticClient
from gridpulse_agent.validate import validate


class State(TypedDict, total=False):
    question: str
    today: date
    route: str
    request: MetricRequest | None
    errors: list[str]
    attempts: int
    result: dict | None
    answer: str
    unsupported: list[str]
    rewrites: int
    caveats: list[str]
    status: Literal[
        "answered", "definition", "out_of_scope", "no_valid_request", "fallback_table", "no_data"
    ]


def _table(result: dict, limit: int = 20) -> str:
    lines = [" | ".join(result["columns"])]
    lines += [" | ".join(str(c) for c in row) for row in result["rows"][:limit]]
    return "\n".join(lines)


def build_graph(brain: Brain, semantic: SemanticClient, settings: AgentSettings, checkpointer=None):
    def route(state: State) -> State:
        decision = brain.route(state["question"])
        return {"route": decision.route}

    def define(state: State) -> State:
        return {
            "answer": brain.define(state["question"], semantic.catalog()),
            "status": "definition",
        }

    def out_of_scope(state: State) -> State:
        return {"answer": prompts.OUT_OF_SCOPE, "status": "out_of_scope"}

    def plan(state: State) -> State:
        request = brain.plan(
            state["question"],
            semantic.catalog(),
            semantic.balancing_authorities(),
            state["today"],
            state.get("errors", []),
            state.get("request"),
            semantic.saved_queries(),
        )
        return {"request": request, "attempts": state.get("attempts", 0) + 1}

    def check(state: State) -> State:
        errors = validate(
            state["request"],
            semantic.catalog(),
            max_window_days=settings.max_window_days,
            max_rows=settings.max_rows,
        )
        return {"errors": errors}

    def execute(state: State) -> State:
        try:
            return {"result": semantic.query(state["request"]), "errors": []}
        except SemanticAPIError as exc:
            return {"result": None, "errors": [f"The semantic API rejected the request: {exc}"]}

    def inspect(state: State) -> State:
        request = state["request"]
        try:
            coverage = semantic.coverage(request)
        except (SemanticAPIError, httpx.HTTPError):
            coverage = None  # a caveat says so; the answer itself still stands
        try:
            latest = semantic.latest_hour()
        except (SemanticAPIError, httpx.HTTPError):
            latest = None
        caveats = inspection.caveats(request, coverage, latest, settings.revision_window_days)
        if inspection.has_data(state["result"], request.metrics):
            return {"caveats": caveats}
        return {
            "caveats": caveats,
            "status": "no_data",
            "answer": f"No data matched this request ({', '.join(request.metrics)}, "
            f"{request.start:%Y-%m-%d %H:%M} to {request.end:%Y-%m-%d %H:%M} UTC).",
        }

    def give_up(state: State) -> State:
        problems = "; ".join(state.get("errors", []))
        return {
            "answer": "I couldn't turn that into a valid metric request "
            f"after {state.get('attempts', 0)} attempts ({problems}). "
            "Try naming the metric, the balancing authority and the time period.",
            "status": "no_valid_request",
        }

    def answer(state: State) -> State:
        text = brain.answer(
            state["question"],
            state["request"],
            state["result"],
            semantic.catalog(),
            state.get("unsupported", []),
        )
        return {"answer": text}

    def ground_check(state: State) -> State:
        context = state["question"] + " " + state["request"].model_dump_json()
        bad = unsupported_numbers(state["answer"], state["result"]["rows"], context)
        if not bad:
            return {"unsupported": [], "status": "answered"}
        if state.get("rewrites", 0) < 1:
            return {"unsupported": bad, "rewrites": state.get("rewrites", 0) + 1}
        return {
            "unsupported": bad,
            "status": "fallback_table",
            "answer": "I couldn't write an answer whose numbers all match the data, so here is "
            "the result as returned by the semantic layer:\n\n" + _table(state["result"]),
        }

    def after_route(state: State) -> str:
        return {"metric": "plan", "definition": "define"}.get(state["route"], "out_of_scope")

    def after_check(state: State) -> str:
        if not state["errors"]:
            return "execute"
        return "plan" if state["attempts"] < settings.max_plan_attempts else "give_up"

    def after_execute(state: State) -> str:
        if state.get("result") is not None:
            return "inspect"
        return "plan" if state["attempts"] < settings.max_plan_attempts else "give_up"

    def after_inspect(state: State) -> str:
        return END if state.get("status") == "no_data" else "answer"

    def after_ground_check(state: State) -> str:
        return "answer" if state.get("status") is None and state.get("unsupported") else END

    g = StateGraph(State)
    for name, fn in [
        ("route", route),
        ("define", define),
        ("out_of_scope", out_of_scope),
        ("plan", plan),
        ("validate", check),
        ("execute", execute),
        ("inspect", inspect),
        ("give_up", give_up),
        ("answer", answer),
        ("ground_check", ground_check),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "route")
    g.add_conditional_edges("route", after_route, ["plan", "define", "out_of_scope"])
    g.add_edge("plan", "validate")
    g.add_conditional_edges("validate", after_check, ["execute", "plan", "give_up"])
    g.add_conditional_edges("execute", after_execute, ["inspect", "plan", "give_up"])
    g.add_conditional_edges("inspect", after_inspect, ["answer", END])
    g.add_edge("answer", "ground_check")
    g.add_conditional_edges("ground_check", after_ground_check, ["answer", END])
    for terminal in ("define", "out_of_scope", "give_up"):
        g.add_edge(terminal, END)
    return g.compile(checkpointer=checkpointer)


def ask(graph, question: str, today: date | None = None) -> dict[str, Any]:
    state = graph.invoke({"question": question, "today": today or datetime.now(UTC).date()})
    request = state.get("request")
    result = state.get("result") or {}
    answered = state["status"] in ("answered", "fallback_table")
    notes = result.get("notes", []) if answered else []
    caveats = state.get("caveats", []) if answered or state["status"] == "no_data" else []
    extra = [f"Note: {n}" for n in notes] + caveats
    return {
        "answer": "\n\n".join([state["answer"], *extra]),
        "status": state["status"],
        "route": state.get("route"),
        "metric_request": request.model_dump(mode="json") if request else None,
        "sql": result.get("sql"),
        "columns": result.get("columns", []),
        "rows": result.get("rows", []),
        "attempts": state.get("attempts", 0),
        "unsupported_numbers": state.get("unsupported", []),
        "notes": notes,
        "caveats": caveats,
    }
