"""Data quality gates — freshness, schema, and source validation.

Extracted from publish_gate.py. Pure functions; callers pass in already-collected
FetchResult collections.
"""
from __future__ import annotations

from contracts import FetchResult


def _is_index_source(f: FetchResult) -> bool:
    return f.dataset_name in {"sh_index", "sz_index", "cy_index"}


def index_majority_available(sources: dict[str, FetchResult], *, require_majority: bool) -> bool:
    indices = [s for s in sources.values() if _is_index_source(s)]
    if not indices:
        return not require_majority
    ok = sum(1 for s in indices if s.status.value == "OK")
    return ok > len(indices) / 2


def check_source_freshness(
    sources: dict[str, FetchResult],
    *,
    max_age_seconds: int = 180,
) -> list[str]:
    from datetime import UTC, datetime

    warnings: list[str] = []
    now = datetime.now(UTC)
    for name, src in sources.items():
        if src.status != "OK":
            continue
        try:
            fetched = datetime.fromisoformat(src.fetched_at)
            age = (now - fetched).total_seconds()
            if age > max_age_seconds:
                warnings.append(f"{name}: stale ({age:.0f}s > {max_age_seconds}s)")
        except Exception:
            warnings.append(f"{name}: unparsable fetched_at")
    return warnings
