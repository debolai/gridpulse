import pytest

from gridpulse_agent.ground_check import unsupported_numbers

ROWS = [
    ["PJM", 70276500.0, 152547.0],
    ["ERCO", 48839000.0, 86595.0],
]


@pytest.mark.parametrize(
    "answer",
    [
        "PJM's demand was 70,276,500 MWh with a peak of 152,547 MW.",
        "PJM used about 70.3 million MWh; ERCOT about 48.8 million MWh.",
        "PJM peaked at 152.5k MW.",
        # 2026 and 9 come from the request window
        "In September 2026, PJM led with 70276500.0 MWh.",
    ],
)
def test_numbers_from_the_result_pass(answer):
    assert unsupported_numbers(answer, ROWS, context="2026-09-01 2026-10-01") == []


def test_injected_wrong_number_is_caught():
    answer = "PJM's demand was 71,276,500 MWh, peaking at 152,547 MW."
    assert unsupported_numbers(answer, ROWS) == ["71,276,500"]


def test_computed_numbers_are_caught():
    # 70.3 + 48.8 = 119.1 million is arithmetic the model did itself; not in the result.
    assert unsupported_numbers("Together they used 119.1 million MWh.", ROWS) == ["119.1 million"]


def test_rounding_must_match_written_precision():
    assert unsupported_numbers("PJM used 70.2 million MWh.", ROWS) == ["70.2 million"]


def test_fractions_may_be_written_as_percent():
    rows = [["ERCO", 0.857142857]]
    assert unsupported_numbers("ERCOT reported 85.7% of expected hours.", rows) == []
    assert unsupported_numbers("ERCOT reported 95.7% of expected hours.", rows) == ["95.7%"]


def test_mape_already_in_percent():
    rows = [["CISO", 8.0228]]
    assert unsupported_numbers("CISO's forecast error was 8.02%.", rows) == []
