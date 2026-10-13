"""The GridPulse assistant as an explicit LangGraph graph.

    route ─┬─ metric ─> plan ─> validate ─ok─> ambiguity ─> execute ─> inspect ─> answer ─> ...
           │             ^ ^        │                 │           │            │
           │             │ └ errors ┘ (≤2 retries)    │           │            └─ no rows: END
           │             └──── clarify <─ ambiguous ──┘           └─ API rejects: replan
           │                   (interrupt: ask the user once, resume with their reply)
           ├─ definition ─> define ─> END        ... answer ─> ground_check ─> END; unsupported
           └─ out_of_scope ─> END                number: rewrite once, then a plain table

The model only routes, plans and writes. Validation, execution, inspection and the number check
are code, and so are the lines appended to every answer: what the metrics left out (flagged
values) and the inspection's caveats (completeness, latest hour, revision window).
A clarifying question pauses the graph (LangGraph interrupt); the conversation's checkpoint
holds it until the user's reply resumes the same thread (see `ask`). Answered questions are
remembered in the thread (`history`), so a follow-up ("and last year?") can build on them.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Literal, TypedDict
from uuid import uuid4

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from gridpulse_agent import clarify, inspection, prompts
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
    planner_clarify: str | None  # the planner's own question, if it had one
    clarify_question: str | None  # the question to ask now, if any
    clarifications: int  # asked this turn (at most one)
    asked: str | None  # the clarifying question asked this turn, and the user's reply
    reply: str | None
    history: list[dict]  # earlier answered questions in this conversation: {question, request}
    errors: list[str]
    attempts: int
    result: dict | None
    answer: str
    unsupported: list[str]
    rewrites: int
    caveats: list[str]
    status: Literal[
        "answered",
        "definition",
        "out_of_scope",
        "no_valid_request",
        "fallback_table",
        "no_data",
        "needs_clarification",
    ]


# Our own types stored in checkpoints; LangGraph only deserializes types it is told to trust.
CHECKPOINT_TYPES = [
    ("gridpulse_agent.contract", "MetricRequest"),
    ("gridpulse_agent.contract", "Filter"),
]


def checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)


def _user_text(state: State) -> str:
    """What the user said this turn: the question, plus their reply to a clarifying question.
    Our own question is left out: it lists BA codes and would look like the user's choice."""
    return " ".join(filter(None, [state["question"], state.get("reply")]))


def _planner_text(state: State) -> str:
    if not state.get("reply"):
        return state["question"]
    return f"{state['question']}\n(I asked: {state['asked']} They answered: {state['reply']})"


def _table(result: dict, limit: int = 20) -> str:
    lines = [" | ".join(result["columns"])]
    lines += [" | ".join(str(c) for c in row) for row in result["rows"][:limit]]
    return "\n".join(lines)


def build_graph(brain: Brain, semantic: SemanticClient, settings: AgentSettings, checkpointer=None):
    def route(state: State) -> State:
        decision = brain.route(state["question"], state.get("history", []))
        return {"route": decision.route}

    def define(state: State) -> State:
        return {
            "answer": brain.define(state["question"], semantic.catalog()),
            "status": "definition",
        }

    def out_of_scope(state: State) -> State:
        return {"answer": prompts.OUT_OF_SCOPE, "status": "out_of_scope"}

    def plan(state: State) -> State:
        planned = brain.plan(
            _planner_text(state),
            semantic.catalog(),
            semantic.balancing_authorities(),
            state["today"],
            state.get("errors", []),
            state.get("request"),
            semantic.saved_queries(),
            state.get("history", []),
        )
        clarify_q = getattr(planned, "clarify", None)
        request = planned.request() if hasattr(planned, "request") else planned
        return {
            "request": request,
            "planner_clarify": clarify_q,
            "attempts": state.get("attempts", 0) + 1,
        }

    def check(state: State) -> State:
        errors = validate(
            state["request"],
            semantic.catalog(),
            max_window_days=settings.max_window_days,
            max_rows=settings.max_rows,
        )
        return {"errors": errors}

    def ambiguity(state: State) -> State:
        if state.get("clarifications", 0) >= 1:
            return {"clarify_question": None}  # asked once already: go with the best request
        try:
            bas = semantic.ba_regions()
        except (SemanticAPIError, httpx.HTTPError):
            bas = []  # the region rule can't run; the planner's own question still can
        question = clarify.region_question(_user_text(state), state["request"], bas)
        return {"clarify_question": question or state.get("planner_clarify")}

    def ask_user(state: State) -> State:
        asked = state["clarify_question"]
        reply = interrupt({"question": asked})  # pauses here until the user answers
        return {
            "asked": asked,
            "reply": reply,
            "clarifications": state.get("clarifications", 0) + 1,
            "clarify_question": None,
            "planner_clarify": None,
            "request": None,
            "errors": [],
            "attempts": 0,
        }

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
            _planner_text(state),
            state["request"],
            state["result"],
            semantic.catalog(),
            state.get("unsupported", []),
        )
        return {"answer": text}

    def ground_check(state: State) -> State:
        context = _user_text(state) + " " + state["request"].model_dump_json()
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

    def remember(state: State) -> State:
        """Keep this question and its request for follow-ups (the last few only)."""
        entry = {"question": _user_text(state), "request": state["request"].model_dump(mode="json")}
        return {"history": [*state.get("history", []), entry][-settings.history_turns :]}

    def after_route(state: State) -> str:
        return {"metric": "plan", "definition": "define"}.get(state["route"], "out_of_scope")

    def after_check(state: State) -> str:
        if not state["errors"]:
            return "ambiguity"
        return "plan" if state["attempts"] < settings.max_plan_attempts else "give_up"

    def after_execute(state: State) -> str:
        if state.get("result") is not None:
            return "inspect"
        return "plan" if state["attempts"] < settings.max_plan_attempts else "give_up"

    def after_ambiguity(state: State) -> str:
        return "clarify" if state.get("clarify_question") else "execute"

    def after_inspect(state: State) -> str:
        return "remember" if state.get("status") == "no_data" else "answer"

    def after_ground_check(state: State) -> str:
        return "answer" if state.get("status") is None and state.get("unsupported") else "remember"

    g = StateGraph(State)
    for name, fn in [
        ("route", route),
        ("define", define),
        ("out_of_scope", out_of_scope),
        ("plan", plan),
        ("validate", check),
        ("ambiguity", ambiguity),
        ("clarify", ask_user),
        ("execute", execute),
        ("inspect", inspect),
        ("give_up", give_up),
        ("answer", answer),
        ("ground_check", ground_check),
        ("remember", remember),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "route")
    g.add_conditional_edges("route", after_route, ["plan", "define", "out_of_scope"])
    g.add_edge("plan", "validate")
    g.add_conditional_edges("validate", after_check, ["ambiguity", "plan", "give_up"])
    g.add_conditional_edges("ambiguity", after_ambiguity, ["clarify", "execute"])
    g.add_edge("clarify", "plan")
    g.add_conditional_edges("execute", after_execute, ["inspect", "plan", "give_up"])
    g.add_conditional_edges("inspect", after_inspect, ["answer", "remember"])
    g.add_edge("answer", "ground_check")
    g.add_conditional_edges("ground_check", after_ground_check, ["answer", "remember"])
    for terminal in ("define", "out_of_scope", "give_up", "remember"):
        g.add_edge(terminal, END)
    # A checkpointer is required: a clarifying question pauses the run until the reply arrives.
    return g.compile(checkpointer=checkpointer or InMemorySaver(serde=checkpoint_serializer()))


# Everything one question sets, reset at the start of the next one in the same conversation.
_FRESH_TURN = {
    "route": None,
    "request": None,
    "planner_clarify": None,
    "clarify_question": None,
    "clarifications": 0,
    "asked": None,
    "reply": None,
    "errors": [],
    "attempts": 0,
    "result": None,
    "answer": "",
    "unsupported": [],
    "rewrites": 0,
    "caveats": [],
    "status": None,
}


def ask_stream(
    graph, question: str, today: date | None = None, thread_id: str | None = None
) -> Iterator[dict[str, Any]]:
    """One message in a conversation, as events: {"type": "step", "node": ...} as each graph
    step finishes, then {"type": "result", ...}. If the conversation is waiting for the answer
    to a clarifying question, the message is that answer and the paused run resumes."""
    thread_id = thread_id or uuid4().hex
    config = {"configurable": {"thread_id": thread_id}}
    if graph.get_state(config).interrupts:
        payload = Command(resume=question)
    else:
        payload = {**_FRESH_TURN, "question": question, "today": today or datetime.now(UTC).date()}
    for update in graph.stream(payload, config, stream_mode="updates"):
        for node in update:
            if node != "__interrupt__":
                yield {"type": "step", "node": node}
    snapshot = graph.get_state(config)
    yield {"type": "result", **_result(snapshot.values, snapshot.interrupts, thread_id)}


def ask(
    graph, question: str, today: date | None = None, thread_id: str | None = None
) -> dict[str, Any]:
    """ask_stream without the progress events: the final result."""
    *_, last = ask_stream(graph, question, today, thread_id)
    return {k: v for k, v in last.items() if k != "type"}


def _result(state: dict, interrupts, thread_id: str) -> dict[str, Any]:
    request = state.get("request")
    if interrupts:
        return {
            "answer": interrupts[0].value["question"],
            "status": "needs_clarification",
            "thread_id": thread_id,
            "route": state.get("route"),
            "metric_request": request.model_dump(mode="json") if request else None,
            "sql": None,
            "columns": [],
            "rows": [],
            "attempts": state.get("attempts", 0),
            "unsupported_numbers": [],
            "notes": [],
            "caveats": [],
        }
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
        "thread_id": thread_id,
    }
