import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.contextual_controls.ai import (
    AIManager,
    AIProviderError,
    OllamaProvider,
    OpenAICompatibleProvider,
    PrivacySettings,
    apply_order,
    build_prompt,
    parse_order,
)
from custom_components.contextual_controls.models import Ranked

NOW = datetime(2026, 9, 25, 22, 30, tzinfo=UTC)


def items():
    return [
        Ranked("light.one", 0.9, "habit", 8),
        Ranked("script.two", 0.8, "recent", 3),
        Ranked("switch.three", 0.7, "habit", 2),
    ]


def test_prompt_privacy_uses_opaque_tokens():
    package = build_prompt(
        NOW,
        [
            {
                "entity_id": "light.bedroom",
                "friendly_name": "Private bedroom",
                "state": "off",
                "area": "bedroom",
                "score": 0.8,
                "count": 9,
                "reason": "habit",
            }
        ],
        PrivacySettings(
            entity_id=False,
            friendly_name=False,
            current_state=False,
            area=False,
            usage_statistics=False,
            context_entities=False,
        ),
    )
    assert "light.bedroom" not in package.prompt
    assert "Private bedroom" not in package.prompt
    assert "candidate_1" in package.prompt
    assert package.allowed == {"candidate_1": "light.bedroom"}


def test_prompt_contains_only_authorized_context():
    package = build_prompt(
        NOW,
        [{"entity_id": "light.one", "friendly_name": "One", "state": "on"}],
        PrivacySettings(presence_information=False, context_entities=False),
        presence_home=True,
        context_states=[{"id": "input_boolean.sleep", "state": "on"}],
    )
    assert "someone_home" not in package.prompt
    assert "input_boolean.sleep" not in package.prompt
    assert NOW.isoformat() not in package.prompt
    assert '"current_hour":22' in package.prompt


def test_parse_ai_response_and_ignore_invalid_entity():
    allowed = {item.entity_id: item.entity_id for item in items()}
    parsed = parse_order('["script.two", "invalid.entity", "script.two", "light.one"]', allowed)
    assert parsed == ["script.two", "light.one"]


@pytest.mark.parametrize("response", ["not json", '{"entities": []}', "[]", '[1, "light.one"]'])
def test_invalid_ai_response(response):
    with pytest.raises(AIProviderError, match="invalid_response"):
        parse_order(response, {"light.one": "light.one"})


def test_hybrid_and_ai_assisted_ranking():
    hybrid = apply_order(items(), ["switch.three", "script.two", "light.one"], "hybrid")
    assisted = apply_order(items(), ["switch.three", "script.two", "light.one"], "ai_assisted")
    assert [item.entity_id for item in hybrid] == ["light.one", "script.two", "switch.three"]
    assert [item.entity_id for item in assisted] == ["switch.three", "script.two", "light.one"]
    assert all(item.source == "hybrid" for item in hybrid)
    assert all(item.source == "ai_assisted" for item in assisted)


class FakeProvider:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    async def async_order(self, prompt, allowed):
        self.calls += 1
        if self.error:
            raise AIProviderError(self.error)
        return self.result


def test_ai_cache_and_minimum_refresh():
    provider = FakeProvider(["script.two", "light.one"])
    manager = AIManager(provider, 15)
    package = build_prompt(
        NOW,
        [{"entity_id": item.entity_id, "score": item.score} for item in items()],
        PrivacySettings(),
    )
    first = asyncio.run(manager.async_rerank(package, items(), "hybrid", NOW))
    cached = asyncio.run(
        manager.async_rerank(package, items(), "hybrid", NOW + timedelta(minutes=1))
    )
    changed = build_prompt(
        NOW,
        [{"entity_id": "light.one", "score": 0.1}],
        PrivacySettings(),
    )
    throttled = asyncio.run(
        manager.async_rerank(changed, items(), "hybrid", NOW + timedelta(minutes=1))
    )
    assert first.used and cached.used and cached.cached
    assert provider.calls == 1
    assert not throttled.used
    assert throttled.error == "minimum_refresh_interval"


def test_ai_fallback_keeps_statistical_order():
    manager = AIManager(FakeProvider(error="timeout"), 15)
    package = build_prompt(
        NOW,
        [{"entity_id": item.entity_id, "score": item.score} for item in items()],
        PrivacySettings(),
    )
    outcome = asyncio.run(manager.async_rerank(package, items(), "hybrid", NOW))
    assert not outcome.used
    assert outcome.error == "timeout"
    assert outcome.ranked == items()


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self, content_type=None):
        return self.body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_ollama_provider_contract():
    session = FakeSession(FakeResponse({"message": {"content": '["light.one"]'}}))
    provider = OllamaProvider(session, "http://ollama:11434/", "local-model", 5, 0.1)
    result = asyncio.run(provider.async_order("prompt", {"light.one": "light.one"}))
    url, request = session.calls[0]
    assert result == ["light.one"]
    assert url == "http://ollama:11434/api/chat"
    assert request["json"]["stream"] is False
    assert request["json"]["model"] == "local-model"


def test_openai_compatible_provider_contract():
    session = FakeSession(FakeResponse({"choices": [{"message": {"content": '["candidate_1"]'}}]}))
    provider = OpenAICompatibleProvider(session, "http://local-model/v1", "model", 5, 0.1, "secret")
    result = asyncio.run(provider.async_order("prompt", {"candidate_1": "light.private"}))
    url, request = session.calls[0]
    assert result == ["light.private"]
    assert url == "http://local-model/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer secret"
    assert "secret" not in str(request["json"])


def test_http_error_is_sanitized():
    session = FakeSession(FakeResponse({}, status=503))
    provider = OllamaProvider(session, "http://private-host", "model", 5, 0.1)
    with pytest.raises(AIProviderError, match="http_503"):
        asyncio.run(provider.async_order("prompt", {"light.one": "light.one"}))
