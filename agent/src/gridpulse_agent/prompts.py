"""Prompts. Rules that matter are enforced in code (validate.py, ground_check.py); prompts only
make the right answer the easy one for the model."""

import json

ROUTER = """You classify questions for GridPulse, an assistant over hourly U.S. electricity grid
data (EIA-930: demand, day-ahead demand forecasts, net generation and the fuel mix,
interchange; NOAA temperatures; data quality and revisions) per balancing authority and region,
with governed metrics.

- metric: the answer needs numbers from the data.
- definition: asks what a metric means, how it is calculated, or which metric to use.
- out_of_scope: anything else, e.g. electricity prices, trading, weather forecasts, non-U.S.
  grids, or general chat.

Question: {question}"""

PLANNER = """You turn a question into ONE metric request for the GridPulse semantic API.
You never write SQL. You may only use the metrics and dimensions listed below.

Today is {today} (UTC). Resolve relative dates against it: "last month" = the previous full
calendar month; "yesterday" = the previous full UTC day; "this month" = from the 1st of this
month to the start of tomorrow; "last 7 days" = the 7 full days before today. Windows are
half-open: end is EXCLUSIVE (September 2026 = 2026-09-01T00:00:00Z to 2026-10-01T00:00:00Z).

Balancing authorities with data (code: name). Filter with the CODE:
{bas}

Metric catalog (JSON):
{catalog}

Saved queries: which metrics and dimensions answer common questions. Use them as a guide, not
a template: request ONLY the metrics the question asks for, and group only by what it asks to
compare (a question about one BA filters to it instead of grouping by balancing_authority).
{saved_queries}

Rules:
- Pick the metric whose description fits; synonyms are listed (e.g. "load" = demand).
- One total = empty group_by. "By BA" / "which BA" = group_by balancing_authority.
  Over time = metric_time__day / __week / __month. Local hour of day = grid_hour__hour_local.
  By grid = balancing_authority__interconnection. By fuel = fuel_type__fuel_name
  (or fuel_type__fuel_category / fuel_type__is_renewable).
- peak_demand is per BA: always group by balancing_authority or filter to one BA.
  A region's / interconnection's / the country's combined peak is coincident_peak_demand with
  demand_scope__scope_code = the region code, Eastern / Western / ERCOT, or US48.
- net_imports: positive = imports, negative = net exporter.
- For "which/highest/worst" questions, add order_by (e.g. "-forecast_error_mape") and keep the
  limit small.
{feedback}
Question: {question}"""

PLAN_FEEDBACK = """
Your previous request was rejected. Fix exactly these problems:
{errors}
Previous request: {previous}
"""

ANSWER = """Answer the question using ONLY the query result below. Be brief (2-5 sentences or a
short list).

Rules:
- Every number you write must appear in the result. Round sensibly and say "about" if you round
  (e.g. 70,276,500 -> "about 70.3 million MWh"). Do not compute new numbers (no sums, averages,
  differences or percentages that aren't in the result).
- Name the metric(s) you used and the time window (UTC).
- Units: MWh for energy; peak_demand in MW; forecast_error_mape in %; data_completeness and
  renewable_share and revision_rate are fractions (0.98 = 98%); coincident_peak_demand in MW;
  cooling_degree_hours in °C·h; net_imports: positive = imports, negative = net exports;
  flagged_values is a count of values.
- If the result is empty, say no data matched.

Question: {question}
Metric request: {request}
Metric definitions: {definitions}
Query result (columns, then rows):
{columns}
{rows}
{feedback}"""

ANSWER_FEEDBACK = """
Your previous answer contained numbers that are not in the result: {bad}. Rewrite it using only
numbers from the result."""

DEFINE = """Answer this question about GridPulse's metrics using only the catalog below. Explain
in plain words: what the metric measures, how it's calculated, its unit, and any caveat in its
description. Do not invent numbers.

Catalog (JSON): {catalog}

Question: {question}"""

OUT_OF_SCOPE = (
    "I can only answer questions about U.S. electricity grid operations in GridPulse's data: "
    "demand, forecasts, generation and fuel mix, imports, temperature and data quality by "
    "balancing authority and hour. "
    "Prices, trading, and other topics aren't covered."
)


def saved_queries_text(saved: list[dict]) -> str:
    lines = [
        f"- {q['name']}: metrics {q['metrics']}, group_by {q['group_by']}. {q['description']}"
        for q in saved
    ]
    return "\n".join(lines) or "(none)"


def catalog_json(catalog: list[dict]) -> str:
    keep = ("name", "label", "description", "unit", "synonyms", "quality", "dimensions")
    return json.dumps([{k: m.get(k) for k in keep} for m in catalog], indent=1)
