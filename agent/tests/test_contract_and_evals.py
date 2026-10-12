from datetime import date

from conftest import req

from gridpulse_agent.contract import Filter as AgentFilter
from gridpulse_agent.contract import MetricRequest as AgentRequest
from gridpulse_agent.evals import load_cases, score
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
    assert len(cases) >= 15
    assert len({c.id for c in cases}) == len(cases)
    for case in cases:
        if case.route == "metric":
            AgentRequest.model_validate(
                {
                    **case.expected,
                    "start": f"{case.expected['start']}T00:00:00Z",
                    "end": f"{case.expected['end']}T00:00:00Z",
                }
            )


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
