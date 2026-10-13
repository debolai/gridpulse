"""Clarify: when to stop and ask the user one question instead of guessing (blueprint step 4).

Two sources, checked after a request passes validation:
- a code rule: the question names an EIA region with several balancing authorities ("California",
  "Florida", "the Carolinas") without saying whether it means one BA or the whole region;
- the planner's own `clarify` question, for anything else it can't resolve (see prompts.PLANNER).
The rule runs first and reads only what the USER wrote, so it holds even when the planner quietly
picks one reading (it tends to pick the region, or the largest BA).
"""

import re

from gridpulse_agent.contract import MetricRequest

REGION_LEVEL = {"balancing_authority__region", "balancing_authority__region_name"}
SCOPE = "demand_scope__scope_code"
# Words that say "the region as a whole".
WHOLE_REGION = re.compile(
    r"\b(region|regions|regional|whole|entire|all|combined|statewide)\b", re.I
)


def _mentions(question: str, phrase: str) -> bool:
    # Case-sensitive on purpose: region names are proper nouns ("Central", not "central").
    return re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", question) is not None


def _region_resolved(text: str, request: MetricRequest, name: str, bas: list[dict]) -> bool:
    # A breakdown by BA or region shows every reading at once.
    by = {"balancing_authority", SCOPE} | REGION_LEVEL
    if any(g in by for g in request.group_by):
        return True
    if WHOLE_REGION.search(text):
        return True
    # The user named the BA itself: its code (CISO), its name, or "<region> ISO".
    lowered = text.lower()
    return (
        any(_mentions(text, b["code"]) or b["name"].lower() in lowered for b in bas)
        or _mentions(text, f"{name} ISO")
        or _mentions(text, f"{name} Independent System Operator")
    )


def region_question(text: str, request: MetricRequest, bas: list[dict]) -> str | None:
    """text: what the user wrote this turn. bas: active BAs as {code, name, region, region_name}.
    None when nothing is ambiguous."""
    regions: dict[tuple[str, str], list[dict]] = {}
    for b in bas:
        regions.setdefault((b["region"], b["region_name"]), []).append(b)
    for (code, name), members in sorted(regions.items()):
        if len(members) < 2 or not _mentions(text, name):
            continue
        if _region_resolved(text, request, name, members):
            continue
        listed = ", ".join(sorted(b["code"] for b in members)[:8])
        more = ", ..." if len(members) > 8 else ""
        return (
            f'"{name}" could mean one balancing authority or all {len(members)} in EIA\'s '
            f"{name} region ({code}: {listed}{more}). Which do you mean? Reply with a BA code "
            f'from the list, or "the whole {name} region".'
        )
    return None
