from conftest import TODAY, FakeSemantic, ScriptedBrain, req

from gridpulse_agent.contract import PlannedRequest
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


def test_answer_ends_with_the_quality_notes(catalog, settings):
    note = "Excludes demand values flagged suspect (one-hour spikes) or invalid (zeros)."
    brain = ScriptedBrain(plans=[req()], answers=["PJM: 70,276,500 MWh."])
    out = run(brain, FakeSemantic(catalog, [{**RESULT, "notes": [note]}]), settings)
    assert out["status"] == "answered" and out["notes"] == [note]
    assert out["answer"].startswith(f"PJM: 70,276,500 MWh.\n\nNote: {note}\n\nData: 100%")


def test_inspection_caveats_end_the_answer(catalog, settings):
    brain = ScriptedBrain(plans=[req()], answers=["PJM: 70,276,500 MWh."])
    semantic = FakeSemantic(catalog, [RESULT], coverage=[["PJM", 700, 720]])
    out = run(brain, semantic, settings)
    assert out["caveats"][:2] == [
        "Data: 97.2% of expected BA-hours have valid demand.",
        "Latest hour loaded: 2026-10-12 09:00 UTC.",
    ]
    assert out["caveats"][2].startswith("Hours after 2026-09-12 are recent")  # Sept ends Oct 1
    assert out["answer"].endswith(out["caveats"][2])
    assert semantic.coverage_requests[0].start == req().start  # same window as the answer


def test_empty_result_skips_the_model(catalog, settings):
    brain = ScriptedBrain(plans=[req()])  # no answers queued: the model must not be asked
    empty = {"columns": ["demand"], "rows": [[None]], "sql": "select ..."}  # total, no data
    out = run(brain, FakeSemantic(catalog, [empty]), settings)
    assert out["status"] == "no_data" and brain.answer_calls == []
    assert out["answer"].startswith("No data matched this request (demand, 2026-09-01 00:00")
    assert "Latest hour loaded" in out["answer"]


def test_failed_coverage_check_still_answers(catalog, settings):
    from gridpulse_agent.semantic_client import SemanticAPIError

    brain = ScriptedBrain(plans=[req()], answers=["PJM: 70,276,500 MWh."])
    semantic = FakeSemantic(catalog, [RESULT], coverage=SemanticAPIError("down"))
    out = run(brain, semantic, settings)
    assert out["status"] == "answered"
    assert "Couldn't check data completeness." in out["caveats"]


def test_validation_errors_go_back_to_the_planner(catalog, settings):
    bad = req(metrics=["peak_demand"])  # pooled across BAs: blocked by code
    good = req(metrics=["peak_demand"], group_by=["balancing_authority"])
    brain = ScriptedBrain(plans=[bad, good], answers=["PJM peaked at 152,547."])
    peak = {
        **RESULT,
        "columns": ["balancing_authority", "peak_demand"],
        "rows": [["PJM", 152547.0]],
    }
    semantic = FakeSemantic(catalog, [peak])
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


CALIFORNIA = "What was California's peak demand in September 2026?"
CISO_PEAK = req(
    metrics=["peak_demand"], filters=[{"dimension": "balancing_authority", "values": ["CISO"]}]
)
PEAK = {"columns": ["peak_demand"], "rows": [[46213.0]], "sql": "select ..."}


def test_ambiguous_region_pauses_then_resumes_with_the_reply(catalog, settings):
    brain = ScriptedBrain(plans=[CISO_PEAK, CISO_PEAK], answers=["CISO peaked at 46,213 MW."])
    semantic = FakeSemantic(catalog, [PEAK])
    graph = build_graph(brain, semantic, settings)

    first = ask(graph, CALIFORNIA, today=TODAY)
    assert first["status"] == "needs_clarification"
    assert first["answer"].startswith('"California" could mean one balancing authority')
    assert semantic.queries == []  # nothing ran on a guess

    second = ask(graph, "CISO only", thread_id=first["thread_id"])
    assert second["status"] == "answered" and second["thread_id"] == first["thread_id"]
    assert "They answered: CISO only" in brain.plan_calls[1]["question"]
    assert semantic.queries == [CISO_PEAK]


def test_the_planner_can_ask_too(catalog, settings):
    unsure = PlannedRequest(**req().model_dump(), clarify="Which week do you mean?")
    brain = ScriptedBrain(plans=[unsure, req()], answers=["PJM: 70,276,500 MWh."])
    graph = build_graph(brain, FakeSemantic(catalog, [RESULT]), settings)
    first = ask(graph, "What was PJM's demand that week?", today=TODAY)
    assert (first["status"], first["answer"]) == ("needs_clarification", "Which week do you mean?")
    assert ask(graph, "the first week of September", thread_id=first["thread_id"])["status"] == (
        "answered"
    )


def test_only_one_clarifying_question_per_turn(catalog, settings):
    brain = ScriptedBrain(plans=[CISO_PEAK, CISO_PEAK], answers=["CISO peaked at 46,213 MW."])
    graph = build_graph(brain, FakeSemantic(catalog, [PEAK]), settings)
    first = ask(graph, CALIFORNIA, today=TODAY)
    # A reply that settles nothing still gets an answer, from the best request, not a loop.
    second = ask(graph, "not sure", thread_id=first["thread_id"])
    assert second["status"] == "answered"


def test_a_new_question_in_the_same_conversation_starts_fresh(catalog, settings):
    brain = ScriptedBrain(plans=[req(), req()], answers=["PJM: 70,276,500 MWh."] * 2)
    graph = build_graph(brain, FakeSemantic(catalog, [RESULT, RESULT]), settings)
    first = ask(graph, "What was PJM's demand in September 2026?", today=TODAY)
    second = ask(graph, "And again?", today=TODAY, thread_id=first["thread_id"])
    assert second["status"] == "answered" and second["attempts"] == 1
    assert brain.plan_calls[1]["question"] == "And again?" and brain.plan_calls[1]["errors"] == []


def test_follow_ups_see_the_earlier_question_and_request(catalog, settings):
    july = req(start="2025-07-01T00:00:00Z", end="2025-08-01T00:00:00Z")
    brain = ScriptedBrain(plans=[req(), july], answers=["PJM: 70,276,500 MWh."] * 2)
    graph = build_graph(brain, FakeSemantic(catalog, [RESULT, RESULT]), settings)
    first = ask(graph, "What was PJM's demand in September 2026?", today=TODAY)
    ask(graph, "And the same month last year?", today=TODAY, thread_id=first["thread_id"])
    assert brain.plan_calls[0]["history"] == []
    (earlier,) = brain.plan_calls[1]["history"]
    assert earlier["question"] == "What was PJM's demand in September 2026?"
    assert earlier["request"]["metrics"] == ["demand"]


def test_history_keeps_only_the_last_few_turns(catalog, settings):
    settings.history_turns = 2
    n = 4
    brain = ScriptedBrain(plans=[req()] * n, answers=["PJM: 70,276,500 MWh."] * n)
    graph = build_graph(brain, FakeSemantic(catalog, [RESULT] * n), settings)
    thread = None
    for i in range(n):
        thread = ask(graph, f"question {i}", today=TODAY, thread_id=thread)["thread_id"]
    assert [t["question"] for t in brain.plan_calls[-1]["history"]] == ["question 1", "question 2"]


def test_other_conversations_dont_share_history(catalog, settings):
    brain = ScriptedBrain(plans=[req(), req()], answers=["PJM: 70,276,500 MWh."] * 2)
    graph = build_graph(brain, FakeSemantic(catalog, [RESULT, RESULT]), settings)
    ask(graph, "What was PJM's demand in September 2026?", today=TODAY)
    ask(graph, "What was PJM's demand in September 2026?", today=TODAY)  # new thread
    assert brain.plan_calls[1]["history"] == []


def test_stream_reports_each_step_then_the_result(catalog, settings):
    from gridpulse_agent.graph import ask_stream

    brain = ScriptedBrain(plans=[req()], answers=["PJM: 70,276,500 MWh."])
    graph = build_graph(brain, FakeSemantic(catalog, [RESULT]), settings)
    events = list(ask_stream(graph, "What was PJM's demand in September 2026?", today=TODAY))
    steps = [e["node"] for e in events if e["type"] == "step"]
    assert steps == [
        "route",
        "plan",
        "validate",
        "ambiguity",
        "execute",
        "inspect",
        "answer",
        "ground_check",
        "remember",
    ]
    assert events[-1]["type"] == "result" and events[-1]["status"] == "answered"
