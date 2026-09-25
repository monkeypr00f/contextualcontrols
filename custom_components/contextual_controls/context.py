"""Small, deterministic helpers for contextual snapshots."""

from collections.abc import Mapping


def is_home(entity_id: str, state: str) -> bool:
    """Interpret only stable HA presence states, without semantic guessing."""
    domain = entity_id.partition(".")[0]
    return state == "on" if domain == "binary_sensor" else state == "home"


def presence_status(states: Mapping[str, str], entity_ids: tuple[str, ...]) -> bool | None:
    """Return None when presence is not configured or has no usable state."""
    usable = {
        entity_id: state
        for entity_id in entity_ids
        if (state := states.get(entity_id)) not in (None, "unknown", "unavailable")
    }
    if not entity_ids or not usable:
        return None
    return any(is_home(entity_id, state) for entity_id, state in usable.items())


def snapshot_context(
    states: Mapping[str, str], entity_ids: tuple[str, ...]
) -> tuple[tuple[str, str], ...]:
    """Capture configured states only; sorting makes storage and tests stable."""
    return tuple(
        sorted(
            (entity_id, state)
            for entity_id in entity_ids
            if (state := states.get(entity_id)) not in (None, "unknown", "unavailable")
        )
    )


def context_similarity(
    current: tuple[tuple[str, str], ...], historical: tuple[tuple[str, str], ...]
) -> float:
    """Compare opaque states exactly; no domain-specific semantic inference."""
    current_map = dict(current)
    historical_map = dict(historical)
    common = current_map.keys() & historical_map.keys()
    if not common:
        return 1.0
    matches = sum(current_map[key] == historical_map[key] for key in common)
    return 0.75 + 0.3 * matches / len(common)
