from __future__ import annotations

import re

from app.matching.names import normalize_station_name

_SEARCH_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def fts_prefix_expression(value: str) -> str:
    """Build a quoted FTS5 prefix expression from untrusted search text."""

    tokens = [token.casefold() for token in _SEARCH_TOKEN.findall(value)]
    normalized = normalize_station_name(value)
    expressions: list[str] = []
    if tokens:
        expressions.append(" AND ".join(f'"{token}"*' for token in tokens))
    if normalized and normalized not in tokens:
        expressions.append(f'"{normalized}"*')
    return " OR ".join(f"({expression})" for expression in expressions)
