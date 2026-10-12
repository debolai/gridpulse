"""Every number in an answer must come from the query result (or the question itself).

The main risk in an analytics assistant is a confident wrong number. This extracts each number
from the answer, applies its scale word ("70.3 million") or percent sign, and accepts it only if
it matches a result value to the precision it was written with.
"""

import re
from collections.abc import Iterable

_NUMBER = re.compile(
    r"(?<![\w.])(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    r"(\s*(?:%|percent\b|thousand\b|million\b|billion\b|[kKMB]\b))?"
)
_SCALE = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "billion": 1e9, "b": 1e9}
_DATE_PARTS = re.compile(r"\d+")


def _numbers(text: str) -> list[tuple[str, float, float, bool]]:
    """(raw, value, rounding tolerance, is_percent) for each number written in text."""
    found = []
    for match in _NUMBER.finditer(text):
        raw, suffix = match.group(1), (match.group(2) or "").strip().lower()
        value = float(raw.replace(",", ""))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        scale = _SCALE.get(suffix, 1.0)
        tolerance = 0.5 * 10 ** (-decimals) * scale
        found.append(
            (raw + (match.group(2) or ""), value * scale, tolerance, suffix in ("%", "percent"))
        )
    return found


def _allowed_values(rows: Iterable[Iterable], extra_text: str) -> list[float]:
    allowed: list[float] = []
    for row in rows:
        for cell in row:
            if isinstance(cell, bool):
                continue
            if isinstance(cell, int | float):
                allowed.append(float(cell))
            elif isinstance(cell, str):
                # Dates and labels: 2026-09-01T00:00:00 -> 2026, 9, 1 ...; 'Q3' -> 3
                allowed.extend(float(p) for p in _DATE_PARTS.findall(cell))
    allowed.extend(float(p) for p in _DATE_PARTS.findall(extra_text))
    return allowed


def unsupported_numbers(answer: str, rows: list[list], context: str = "") -> list[str]:
    """Numbers in `answer` that no result value (or number in `context`) supports."""
    allowed = _allowed_values(rows, context)
    bad = []
    for raw, value, tolerance, is_percent in _numbers(answer):
        # (candidate, tolerance) pairs; a percent may also stand for a 0-1 fraction (0.98 -> 98%)
        candidates = [(value, tolerance)]
        if is_percent:
            candidates.append((value / 100, tolerance / 100))
        ok = any(abs(c - a) <= tol + 1e-9 * abs(a) for c, tol in candidates for a in allowed)
        if not ok:
            bad.append(raw)
    return bad
