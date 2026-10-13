import json

import pytest
from conftest import FIXTURES, req

from gridpulse_agent.clarify import region_question

BAS = json.loads((FIXTURES / "ba_regions.json").read_text())
CISO = [{"dimension": "balancing_authority", "values": ["CISO"]}]


def ask(question, **request):
    return region_question(question, req(**request), BAS)


def test_a_region_with_several_bas_picked_as_one_ba_is_ambiguous():
    q = ask("What was California's peak demand in September 2026?", filters=CISO)
    assert q.startswith('"California" could mean one balancing authority or all 5')
    assert "(CAL: BANC, CISO, IID, LDWP, TIDC)" in q and '"the whole California region"' in q


@pytest.mark.parametrize(
    "question",
    [
        "What was CISO's peak demand?",  # the BA code
        "What was California ISO's peak demand?",
        "What was the California Independent System Operator's peak demand?",
    ],
)
def test_naming_the_ba_itself_is_not_ambiguous(question):
    assert ask(question, filters=CISO) is None


def test_the_planners_reading_does_not_settle_it():
    # The planner quietly picked the region (or listed every BA): the user still didn't say.
    region = [{"dimension": "demand_scope__scope_code", "values": ["CAL"]}]
    assert ask("What was California's peak demand?", filters=region) is not None
    every = [
        {
            "dimension": "balancing_authority",
            "op": "in",
            "values": ["BANC", "CISO", "IID", "LDWP", "TIDC"],
        }
    ]
    assert ask("What was California's demand?", filters=every) is not None


@pytest.mark.parametrize(
    "question",
    [
        "What was the California region's peak demand?",
        "What was the combined peak of all of California?",
        "What was statewide demand in California?",
    ],
)
def test_asking_for_the_whole_region_is_not_ambiguous(question):
    assert ask(question) is None


@pytest.mark.parametrize("group_by", [["balancing_authority"], ["balancing_authority__region"]])
def test_a_breakdown_shows_every_reading(group_by):
    assert ask("Which California BA had the most demand?", group_by=group_by) is None


def test_single_ba_regions_and_lowercase_words_are_not_ambiguous():
    assert (
        ask(
            "What was Texas demand?",
            filters=[{"dimension": "balancing_authority", "values": ["ERCO"]}],
        )
        is None
    )
    assert ask("Show demand in central hours for PJM", filters=[]) is None  # "central" != Central


def test_long_member_lists_are_shortened():
    q = ask("What was demand in the Northwest last month?")
    assert "all 20 in EIA's Northwest region" in q and ", ...)" in q
