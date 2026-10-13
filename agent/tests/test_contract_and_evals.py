import json
from datetime import date

from conftest import FIXTURES, FakeSemantic, ScriptedBrain, req

from gridpulse_agent.contract import Filter as AgentFilter
from gridpulse_agent.contract import MetricRequest as AgentRequest
from gridpulse_agent.contract import PlannedRequest
from gridpulse_agent.evals import load_cases, run, run_e2e, score
from gridpulse_semantic.requests import Filter as ApiFilter
from gridpulse_semantic.requests import MetricRequest as ApiRequest


def test_agent_request_matches_the_semantic_api_contract():
    assert set(AgentRequest.model_fields) == set(ApiRequest.model_fields)
    assert set(AgentFilter.model_fields) == set(ApiFilter.model_fields)
    assert AgentFilter.model_fields["op"].annotation == ApiFilter.model_fields["op"].annotation
    # Anything the planner can produce, the API accepts.
    planned = req(group_by=["balancing_authority"], filters=[{"dimension": "x", "values": ["a"]}])
    ApiRequest.model_validate(planned.model_dump(mode="json"))


def test_golden_set_loads_and_is_large_enough():
    today, cases = load_cases()
    assert today == date(2026, 10, 12)
    assert len(cases) >= 50
    ids = [c.id for c in cases]
    assert len(set(ids)) == len(ids)
    for case in cases:
        if case.after:  # a follow-up comes after the case it continues, which has a request
            assert ids.index(case.after) < ids.index(case.id) and case.expected
        if case.route == "metric" and not case.clarify:
            AgentRequest.model_validate(
                {
                    **case.expected,
                    "start": f"{case.expected['start']}T00:00:00Z",
                    "end": f"{case.expected['end']}T00:00:00Z",
                }
            )
    assert sum(c.clarify for c in cases) >= 3 and sum(bool(c.after) for c in cases) >= 3


def test_golden_set_covers_every_agent_metric_and_saved_query():
    _, cases = load_cases()
    asked = [set((c.expected or {}).get("metrics", [])) for c in cases]
    catalog = json.loads((FIXTURES / "catalog.json").read_text())
    assert {m["name"] for m in catalog} <= set().union(*asked)
    saved = json.loads((FIXTURES / "saved_queries.json").read_text())

    def shape(case):
        e = case.expected or {}
        # Filtering a dimension to one value is the same question for that value.
        dims = set(e.get("group_by", [])) | {f["dimension"] for f in e.get("filters", [])}
        return set(e.get("metrics", [])), dims

    shapes = [shape(c) for c in cases]
    for q in saved:  # some case asks the saved query's question
        assert any(m == set(q["metrics"]) and set(q["group_by"]) <= dims for m, dims in shapes), q[
            "name"
        ]


def test_scoring():
    expected = {
        "metrics": ["demand"],
        "filters": [{"dimension": "balancing_authority", "values": ["PJM"]}],
        "start": "2026-09-01",
        "end": "2026-10-01",
    }
    good = req(filters=[{"dimension": "balancing_authority", "values": ["PJM"]}])
    assert score(good, expected) == []
    wrong_ba = req(filters=[{"dimension": "balancing_authority", "values": ["MISO"]}])
    assert any("filters" in r for r in score(wrong_ba, expected))
    wrong_end = req(
        filters=[{"dimension": "balancing_authority", "values": ["PJM"]}],
        end="2026-09-30T00:00:00Z",
    )
    assert any("end" in r for r in score(wrong_end, expected))


GOLDEN_MINI = """
today: 2026-10-12
cases:
  - id: first
    question: What was PJM's demand in September 2026?
    expect:
      metrics: [demand]
      start: 2026-09-01
      end: 2026-10-01
  - id: follow-up
    after: first
    question: And in August?
    expect:
      metrics: [demand]
      start: 2026-08-01
      end: 2026-09-01
  - id: ambiguous
    question: What was California's demand in August 2026?
    clarify: true
"""
RESULT = {"columns": ["demand"], "rows": [[70276500.0]], "sql": "select ..."}
AUGUST = req(start="2026-08-01T00:00:00Z", end="2026-09-01T00:00:00Z")


def test_planner_eval_scores_follow_ups_with_history_and_clarification(tmp_path, settings, catalog):
    path = tmp_path / "golden.yaml"
    path.write_text(GOLDEN_MINI)
    brain = ScriptedBrain(plans=[req(), AUGUST, AUGUST])
    report = run(brain, FakeSemantic(catalog), settings, path)
    assert report["passed"] == 3, report["cases"]
    (earlier,) = brain.plan_calls[1]["history"]  # the follow-up saw the first question
    assert earlier["question"] == "What was PJM's demand in September 2026?"
    assert earlier["request"]["start"] == "2026-09-01T00:00:00Z"


def test_planner_eval_fails_needless_and_missing_clarifications(tmp_path, settings, catalog):
    path = tmp_path / "golden.yaml"
    path.write_text(GOLDEN_MINI)
    unsure = PlannedRequest(**req().model_dump(), clarify="Which month?")
    clear_california = req(group_by=["balancing_authority"])  # a breakdown: no question asked
    brain = ScriptedBrain(plans=[unsure, AUGUST, clear_california])
    reasons = {
        c["id"]: c["reasons"] for c in run(brain, FakeSemantic(catalog), settings, path)["cases"]
    }
    assert reasons["first"] == ["asked to clarify: Which month?"]
    assert reasons["ambiguous"] == ["should have asked a clarifying question"]


def test_e2e_eval_runs_the_graph_and_counts_ground_check_failures(tmp_path, settings, catalog):
    path = tmp_path / "golden.yaml"
    path.write_text(GOLDEN_MINI)
    brain = ScriptedBrain(
        # first; follow-up's earlier question + the follow-up; the ambiguous question
        plans=[req(), req(), AUGUST, req()],
        answers=["70,276,500 MWh.", "70,276,500 MWh.", "99 MWh.", "70,276,500 MWh."],
    )
    report = run_e2e(brain, FakeSemantic(catalog, [RESULT] * 3), settings, path)
    by_id = {c["id"]: c for c in report["cases"]}
    assert report["passed"] == 3, report["cases"]
    assert by_id["ambiguous"]["status"] == "needs_clarification"
    assert by_id["follow-up"]["ground_check_failed"]  # "99" needed a rewrite
    assert report["ground_check_failures"] == 1
