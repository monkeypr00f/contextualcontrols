"""Eligibility policy and pinned composition, independent of HA."""

from collections.abc import Mapping
from typing import Any

from .const import SUPPORTED_DOMAINS
from .models import Candidate, Ranked


def eligible(candidate: Candidate, options: Mapping[str, Any]) -> bool:
    entity = candidate.entity_id
    domain = entity.partition(".")[0]
    explicit = entity in options["included_entities"] or entity in options["pinned_entities"]
    if candidate.disabled or domain not in SUPPORTED_DOMAINS:
        return False
    if (
        entity in options["excluded_entities"]
        or domain in options["excluded_domains"]
        or candidate.area_id in options["excluded_areas"]
    ):
        return False
    if not options["all_areas"] and candidate.area_id not in options["included_areas"]:
        return False
    if domain == "lock" and not explicit:
        return False
    return explicit or domain in options["included_domains"]


def available(candidate: Candidate) -> bool:
    if candidate.state == "unavailable":
        return False
    return candidate.state != "unknown" or candidate.entity_id.split(".")[0] in {"scene", "button"}


def compose(
    ranked: list[Ranked], candidates: Mapping[str, Candidate], options: Mapping[str, Any]
) -> list[Ranked]:
    """Reapply exclusions at the output boundary; pinned never defeats a blacklist."""
    allowed = {
        key for key, item in candidates.items() if eligible(item, options) and available(item)
    }
    pins = list(dict.fromkeys(entity for entity in options["pinned_entities"] if entity in allowed))
    count = int(options["suggestion_count"])
    if options["pinned_use_slots"]:
        pins = pins[:count]
    dynamic = [item for item in ranked if item.entity_id in allowed and item.entity_id not in pins]
    slots = max(0, count - len(pins)) if options["pinned_use_slots"] else count
    fixed = [Ranked(entity, 1.0, "pinned", source="pinned", pinned=True) for entity in pins]
    if options["pinned_position"] == "after":
        return dynamic[:slots] + fixed
    return fixed + dynamic[:slots]
