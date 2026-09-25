"""Optional shortlist-only AI reranking with strict output validation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Protocol

from .models import Ranked


class AIProviderError(Exception):
    """A sanitized provider failure safe for sensor attributes."""


class AIReranker(Protocol):
    """Minimal provider contract; providers can only return an order."""

    async def async_order(self, prompt: str, allowed: Mapping[str, str]) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class PrivacySettings:
    entity_id: bool = True
    friendly_name: bool = True
    current_state: bool = True
    area: bool = True
    usage_statistics: bool = True
    exact_timestamps: bool = False
    presence_information: bool = False
    context_entities: bool = True


@dataclass(frozen=True, slots=True)
class PromptPackage:
    prompt: str
    allowed: Mapping[str, str]
    cache_key: str


@dataclass(frozen=True, slots=True)
class AIOutcome:
    ranked: list[Ranked]
    used: bool
    error: str | None = None
    cached: bool = False
    last_update: datetime | None = None


def _candidate_payload(
    rows: Sequence[Mapping[str, Any]], privacy: PrivacySettings
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    payload: list[dict[str, Any]] = []
    allowed: dict[str, str] = {}
    for index, row in enumerate(rows, 1):
        entity_id = str(row["entity_id"])
        token = entity_id if privacy.entity_id else f"candidate_{index}"
        allowed[token] = entity_id
        item: dict[str, Any] = {"id": token}
        if privacy.friendly_name and row.get("friendly_name"):
            item["friendly_name"] = row["friendly_name"]
        if privacy.current_state and row.get("state") is not None:
            item["current_state"] = row["state"]
        if privacy.area and row.get("area"):
            item["area"] = row["area"]
        if privacy.usage_statistics:
            item["historical_score"] = row.get("score", 0)
            item["uses_in_time_window"] = row.get("count", 0)
            item["statistical_reason"] = row.get("reason", "")
        payload.append(item)
    return payload, allowed


def build_prompt(
    now: datetime,
    candidates: Sequence[Mapping[str, Any]],
    privacy: PrivacySettings,
    *,
    presence_home: bool | None = None,
    context_states: Sequence[Mapping[str, Any]] = (),
) -> PromptPackage:
    """Build an allowlisted prompt; raw history and user IDs are never accepted."""
    candidate_payload, allowed = _candidate_payload(candidates, privacy)
    context: dict[str, Any] = {
        "weekday": now.strftime("%A"),
        "current_hour": now.hour,
    }
    if privacy.exact_timestamps:
        context["current_time"] = now.isoformat()
    if privacy.presence_information and presence_home is not None:
        context["someone_home"] = presence_home
    if privacy.context_entities:
        context["configured_context"] = list(context_states)
    document = {"context": context, "candidates": candidate_payload}
    prompt = (
        "You are a reranker for Home Assistant controls. You cannot execute actions. "
        "Rank only the supplied candidates by likely usefulness now. Return ONLY a JSON "
        "array containing each candidate id at most once. Do not add explanations, markdown, "
        "commands, services, or ids that are not in the candidates.\n"
        + json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )
    cache_key = hashlib.sha256(prompt.encode()).hexdigest()
    return PromptPackage(prompt, allowed, cache_key)


def parse_order(text: str, allowed: Mapping[str, str]) -> list[str]:
    """Parse an ordered JSON list, dropping duplicates and out-of-shortlist IDs."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            cleaned = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise AIProviderError("invalid_response") from err
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AIProviderError("invalid_response")
    result: list[str] = []
    seen: set[str] = set()
    for token in value:
        entity_id = allowed.get(token)
        if entity_id is not None and entity_id not in seen:
            seen.add(entity_id)
            result.append(entity_id)
    if not result:
        raise AIProviderError("invalid_response")
    return result


def apply_order(ranked: Sequence[Ranked], order: Sequence[str], mode: str) -> list[Ranked]:
    """Blend rank positions while preserving the local shortlist and metadata."""
    if not ranked:
        return []
    ai_weight = 0.75 if mode == "ai_assisted" else 0.35
    size = len(ranked)
    ai_positions = {entity_id: index for index, entity_id in enumerate(order)}

    def position_score(index: int) -> float:
        return 1.0 if size == 1 else 1 - index / (size - 1)

    blended: list[tuple[float, int, Ranked]] = []
    for statistical_index, item in enumerate(ranked):
        ai_index = ai_positions.get(item.entity_id, size)
        ai_score = position_score(min(ai_index, size - 1)) if ai_index < size else 0.0
        combined = (1 - ai_weight) * position_score(statistical_index) + ai_weight * ai_score
        blended.append((combined, statistical_index, item))
    blended.sort(key=lambda value: (-value[0], value[1], value[2].entity_id))
    source = "ai_assisted" if mode == "ai_assisted" else "hybrid"
    return [
        replace(
            item,
            score=round(combined, 4),
            reason_key="ai_selected" if item.entity_id in ai_positions else item.reason_key,
            source=source,
        )
        for combined, _index, item in blended
    ]


class _HTTPProvider:
    def __init__(self, session: Any, endpoint: str, model: str, timeout: int, temperature: float):
        self._session = session
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._temperature = temperature

    async def _request(
        self, url: str, payload: Mapping[str, Any], headers: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]:
        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.post(url, json=payload, headers=headers) as response:
                    if response.status >= 400:
                        raise AIProviderError(f"http_{response.status}")
                    body = await response.json(content_type=None)
        except TimeoutError as err:
            raise AIProviderError("timeout") from err
        except AIProviderError:
            raise
        except (OSError, ValueError) as err:
            raise AIProviderError("connection_error") from err
        if not isinstance(body, Mapping):
            raise AIProviderError("invalid_response")
        return body


class OllamaProvider(_HTTPProvider):
    async def async_order(self, prompt: str, allowed: Mapping[str, str]) -> list[str]:
        body = await self._request(
            f"{self._endpoint}/api/chat",
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "options": {"temperature": self._temperature},
            },
        )
        try:
            content = body["message"]["content"]
        except (KeyError, TypeError) as err:
            raise AIProviderError("invalid_response") from err
        return parse_order(content, allowed)


class OpenAICompatibleProvider(_HTTPProvider):
    def __init__(
        self,
        session: Any,
        endpoint: str,
        model: str,
        timeout: int,
        temperature: float,
        api_key: str,
    ) -> None:
        super().__init__(session, endpoint, model, timeout, temperature)
        self._api_key = api_key

    def _url(self) -> str:
        if self._endpoint.endswith("/chat/completions"):
            return self._endpoint
        if self._endpoint.endswith("/v1"):
            return f"{self._endpoint}/chat/completions"
        return f"{self._endpoint}/v1/chat/completions"

    async def async_order(self, prompt: str, allowed: Mapping[str, str]) -> list[str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = await self._request(
            self._url(),
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": self._temperature,
            },
            headers,
        )
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as err:
            raise AIProviderError("invalid_response") from err
        return parse_order(content, allowed)


class AIManager:
    """Rate-limit providers and cache results by authorized prompt payload."""

    def __init__(self, provider: AIReranker, minimum_refresh_minutes: int) -> None:
        self._provider = provider
        self._minimum_refresh = timedelta(minutes=minimum_refresh_minutes)
        self._cache: dict[str, tuple[list[str], datetime]] = {}
        self._last_request: datetime | None = None

    async def async_rerank(
        self, package: PromptPackage, ranked: Sequence[Ranked], mode: str, now: datetime
    ) -> AIOutcome:
        cached = self._cache.get(package.cache_key)
        if cached is not None:
            order, updated = cached
            return AIOutcome(
                apply_order(ranked, order, mode), True, cached=True, last_update=updated
            )
        if self._last_request is not None and now - self._last_request < self._minimum_refresh:
            return AIOutcome(list(ranked), False, "minimum_refresh_interval")
        self._last_request = now
        try:
            order = await self._provider.async_order(package.prompt, package.allowed)
        except AIProviderError as err:
            return AIOutcome(list(ranked), False, str(err) or "provider_error")
        except Exception:
            return AIOutcome(list(ranked), False, "provider_error")
        self._cache[package.cache_key] = (order, now)
        if len(self._cache) > 32:
            self._cache.pop(next(iter(self._cache)))
        return AIOutcome(apply_order(ranked, order, mode), True, last_update=now)
