from conftest import TODAY, FakeSemantic, ScriptedBrain, req

from gridpulse_agent.graph import ask, build_graph

RESULT = {
    "columns": ["balancing_authority", "demand"],
    "rows": [["PJM", 70276500.0]],
    "sql": "select ...",
}


def run(brain, semantic, settings, question="What was PJM's demand in September 2026?"):
    graph = build_graph(brain, semantic, settings)
    return ask(graph, question, today=TODAY)


def test_happy_path(catalog, settings):
    brain = ScriptedBrain(
        plans=[req(group_by=["balancing_authority"])], answers=["PJM: 70,276,500 MWh."]
    )
    out = run(brain, FakeSemantic(catalog, [RESULT]), settings)
    assert out["status"] == "answered"
    assert out["metric_request"]["metrics"] == ["demand"]
    assert out["sql"] == "select ..." and out["rows"] == RESULT["rows"]


def test_validation_errors_go_back_to_the_planner(catalog, settings):
    bad = req(metrics=["peak_demand"])  # pooled across BAs: blocked by code
    good = req(metrics=["peak_demand"], group_by=["balancing_authority"])
    brain = ScriptedBrain(plans=[bad, good], answers=["PJM peaked at 70,276,500."])
    semantic = FakeSemantic(catalog, [RESULT])
    out = run(brain, semantic, settings)
    assert out["status"] == "answered" and out["attempts"] == 2
    assert "single BA-hour" in brain.plan_calls[1]["errors"][0]
    assert brain.plan_calls[1]["previous"] == bad
    assert semantic.queries == [good]  # the invalid request never reached the API


def test_gives_up_after_three_invalid_plans(catalog, settings):
    brain = ScriptedBrain(plans=[req(metrics=["revenue"])] * 3)
    semantic = FakeSemantic(catalog)
    out = run(brain, semantic, settings)
    assert out["status"] == "no_valid_request" and out["attempts"] == 3
    assert semantic.queries == []


def test_semantic_api_rejection_is_fed_back(catalog, settings):
    brain = ScriptedBrain(plans=[req(), req()], answers=["70,276,500 MWh."])
    semantic = FakeSemantic(catalog, [RESULT], reject_first="dimension(s) not available")
    out = run(brain, semantic, settings)
    assert out["status"] == "answered"
    assert "not available" in brain.plan_calls[1]["errors"][0]


def test_wrong_number_triggers_one_rewrite(catalog, settings):
    brain = ScriptedBrain(
        plans=[req()], answers=["PJM used 99,999 MWh.", "PJM used 70,276,500 MWh."]
    )
    out = run(brain, FakeSemantic(catalog, [RESULT]), settings)
    assert out["status"] == "answered"
    assert brain.answer_calls == [[], ["99,999"]]  # the rewrite was told which number was wrong


def test_persistent_wrong_number_falls_back_to_the_table(catalog, settings):
    brain = ScriptedBrain(
        plans=[req()], answers=["About 71 million MWh.", "Roughly 71 million MWh."]
    )
    out = run(brain, FakeSemantic(catalog, [RESULT]), settings)
    assert out["status"] == "fallback_table"
    assert "70276500.0" in out["answer"] and "71 million" in out["unsupported_numbers"]


def test_definition_questions_skip_the_query(catalog, settings):
    semantic = FakeSemantic(catalog)
    out = run(ScriptedBrain(route="definition", definition="MAPE is..."), semantic, settings)
    assert out["status"] == "definition" and out["answer"] == "MAPE is..."
    assert semantic.queries == []


def test_out_of_scope(catalog, settings):
    out = run(ScriptedBrain(route="out_of_scope"), FakeSemantic(catalog), settings)
    assert out["status"] == "out_of_scope" and "Prices" in out["answer"]
