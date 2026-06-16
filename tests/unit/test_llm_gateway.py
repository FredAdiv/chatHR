"""LLM Gateway unit tests — gateway, providers, usage logging, factory."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm_gateway.fake_provider import FakeLocalLLMProvider
from app.services.llm_gateway.gateway import generate_with_gateway
from app.services.llm_gateway.protocol import (
    LLMMessage,
    LLMProviderError,
    PrivacyGuardBlockedError,
)


# ── Fake provider ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fake_provider_returns_deterministic_response():
    provider = FakeLocalLLMProvider()
    messages = [LLMMessage(role="user", content="What is annual leave?")]
    resp = await provider.generate(messages, "fake-local-v1", "chat")
    assert "[fake-local]" in resp.content
    assert resp.provider == "fake-local"
    assert resp.model == "fake-local-v1"


@pytest.mark.asyncio
async def test_fake_provider_response_is_deterministic():
    provider = FakeLocalLLMProvider()
    messages = [LLMMessage(role="user", content="Same question")]
    resp1 = await provider.generate(messages, "fake-local-v1", "chat")
    resp2 = await provider.generate(messages, "fake-local-v1", "chat")
    assert resp1.content == resp2.content


@pytest.mark.asyncio
async def test_fake_provider_can_simulate_failure():
    provider = FakeLocalLLMProvider(fail_count=1)
    messages = [LLMMessage(role="user", content="test")]
    with pytest.raises(LLMProviderError, match="Simulated"):
        await provider.generate(messages, "fake-local-v1", "chat")
    # Second call succeeds after fail_count exhausted
    resp = await provider.generate(messages, "fake-local-v1", "chat")
    assert "[fake-local]" in resp.content


# ── Gateway: privacy guard ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_privacy_guard_blocks_email():
    messages = [LLMMessage(role="user", content="My email is test@example.com")]
    with pytest.raises(PrivacyGuardBlockedError):
        await generate_with_gateway(messages, "chat", db=None)


@pytest.mark.asyncio
async def test_blocked_input_does_not_call_provider():
    """Provider.generate must NOT be called when privacy guard blocks."""
    messages = [LLMMessage(role="user", content="Call 050-1234567")]

    mock_provider = AsyncMock()
    mock_provider.provider_name = "fake-local"
    mock_provider.generate = AsyncMock()

    with patch("app.services.llm_gateway.gateway.get_llm_provider", return_value=mock_provider):
        with pytest.raises(PrivacyGuardBlockedError):
            await generate_with_gateway(messages, "chat", db=None)

    mock_provider.generate.assert_not_called()


@pytest.mark.asyncio
async def test_safe_message_reaches_provider():
    messages = [LLMMessage(role="user", content="מה כללי חופשה שנתית?")]
    with patch("app.services.llm_gateway.gateway.get_llm_provider",
               return_value=FakeLocalLLMProvider()):
        resp = await generate_with_gateway(messages, "chat", db=None)
    assert "[fake-local]" in resp.content


# ── Gateway: fallback ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_provider_failure_uses_fallback():
    messages = [LLMMessage(role="user", content="test question")]
    fail_provider = FakeLocalLLMProvider(fail_count=1)

    with patch("app.services.llm_gateway.gateway.get_llm_provider", return_value=fail_provider), \
         patch("app.services.llm_gateway.gateway.settings") as mock_settings:
        mock_settings.default_chat_model = "model-primary"
        mock_settings.fallback_chat_model = "model-fallback"
        resp = await generate_with_gateway(messages, "chat", db=None)

    assert resp.used_fallback is True


# ── Usage logging ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_usage_log_does_not_include_prompt():
    messages = [LLMMessage(role="user", content="sensitive question about HR policy")]
    added: list = []
    mock_db = AsyncMock()
    mock_db.add = lambda obj: added.append(obj)

    with patch("app.services.llm_gateway.gateway.get_llm_provider",
               return_value=FakeLocalLLMProvider()):
        await generate_with_gateway(messages, "chat", db=mock_db)

    for obj in added:
        obj_repr = str(vars(obj)) if hasattr(obj, "__dict__") else str(obj)
        assert "sensitive question" not in obj_repr


@pytest.mark.asyncio
async def test_usage_log_records_status_and_model():
    from app.db.models.llm_usage_log import LLMUsageLog
    messages = [LLMMessage(role="user", content="leave policy question")]
    logged: list[LLMUsageLog] = []
    mock_db = AsyncMock()
    mock_db.add = lambda obj: logged.append(obj) if isinstance(obj, LLMUsageLog) else None

    with patch("app.services.llm_gateway.gateway.get_llm_provider",
               return_value=FakeLocalLLMProvider()):
        await generate_with_gateway(messages, "chat", db=mock_db)

    assert logged, "Expected at least one LLMUsageLog entry"
    log = logged[0]
    assert log.provider == "fake-local"
    assert log.purpose == "chat"
    assert log.status in ("success", "fallback_success")


@pytest.mark.asyncio
async def test_blocked_call_logged_as_blocked_by_privacy_guard():
    from app.db.models.llm_usage_log import LLMUsageLog
    messages = [LLMMessage(role="user", content="email: pii@example.com")]
    logged: list[LLMUsageLog] = []
    mock_db = AsyncMock()
    mock_db.add = lambda obj: logged.append(obj) if isinstance(obj, LLMUsageLog) else None

    with patch("app.services.llm_gateway.gateway.get_llm_provider",
               return_value=FakeLocalLLMProvider()):
        with pytest.raises(PrivacyGuardBlockedError):
            await generate_with_gateway(messages, "chat", db=mock_db)

    assert logged
    assert logged[0].status == "blocked_by_privacy_guard"
    log_repr = str(vars(logged[0]))
    assert "pii@example.com" not in log_repr


@pytest.mark.asyncio
async def test_fallback_not_used_for_privacy_block():
    """When privacy guard blocks, the fallback model must NOT be tried."""
    messages = [LLMMessage(role="user", content="My ID: 123456782")]
    mock_provider = AsyncMock()
    mock_provider.provider_name = "fake-local"
    mock_provider.generate = AsyncMock()

    with patch("app.services.llm_gateway.gateway.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_gateway.gateway.settings") as mock_settings:
        mock_settings.default_chat_model = "primary-model"
        mock_settings.fallback_chat_model = "fallback-model"
        with pytest.raises(PrivacyGuardBlockedError):
            await generate_with_gateway(messages, "chat", db=None)

    mock_provider.generate.assert_not_called()


# ── Factory ───────────────────────────────────────────────────────────────────

def test_unknown_provider_rejected():
    with patch("app.services.llm_gateway.factory.settings") as mock_settings:
        mock_settings.llm_provider = "unknown-provider"
        from app.services.llm_gateway.factory import get_llm_provider
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_llm_provider()


def test_fake_local_provider_returned_by_default():
    with patch("app.services.llm_gateway.factory.settings") as mock_settings:
        mock_settings.llm_provider = "fake-local"
        from app.services.llm_gateway.factory import get_llm_provider
        provider = get_llm_provider()
    assert isinstance(provider, FakeLocalLLMProvider)


def test_no_openrouter_without_explicit_config():
    """fake-local is the default; OpenRouter is never called without opt-in."""
    with patch("app.services.llm_gateway.factory.settings") as mock_settings:
        mock_settings.llm_provider = "fake-local"
        from app.services.llm_gateway.factory import get_llm_provider
        provider = get_llm_provider()
    assert provider.provider_name == "fake-local"


# ── OpenRouter skeleton ───────────────────────────────────────────────────────

def test_openrouter_requires_api_key():
    from app.services.llm_gateway.openrouter_provider import OpenRouterProvider
    with pytest.raises(ValueError, match="API key"):
        OpenRouterProvider(api_key="")


def test_openrouter_timeout_configured():
    from app.services.llm_gateway.openrouter_provider import OpenRouterProvider
    provider = OpenRouterProvider(api_key="test-key", timeout=45)
    assert provider._timeout == 45


def test_factory_creates_openrouter_provider_with_valid_key():
    """factory returns OpenRouterProvider when LLM_PROVIDER=openrouter and key is set."""
    from app.services.llm_gateway.openrouter_provider import OpenRouterProvider
    with patch("app.services.llm_gateway.factory.settings") as mock_settings:
        mock_settings.llm_provider = "openrouter"
        mock_settings.openrouter_api_key = "sk-or-real-key-abc123"
        mock_settings.llm_request_timeout_seconds = 30
        from app.services.llm_gateway.factory import get_llm_provider
        provider = get_llm_provider()
    assert isinstance(provider, OpenRouterProvider)
    assert provider.provider_name == "openrouter"


def test_factory_rejects_envfile_placeholder_key():
    """factory must reject the .env.example placeholder, not just CHANGE_ME."""
    with patch("app.services.llm_gateway.factory.settings") as mock_settings:
        mock_settings.llm_provider = "openrouter"
        mock_settings.openrouter_api_key = "REPLACE_WITH_REAL_KEY_FOR_OPENROUTER"
        mock_settings.llm_request_timeout_seconds = 30
        from app.services.llm_gateway.factory import get_llm_provider
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            get_llm_provider()


@pytest.mark.asyncio
async def test_openrouter_http_call_is_mockable():
    """OpenRouter HTTP calls can be injected — no real network needed."""
    from app.services.llm_gateway.openrouter_provider import OpenRouterProvider

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "model": "gpt-4o-mini",
        "choices": [{"message": {"content": "Mocked response"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    provider = OpenRouterProvider(api_key="test-key", http_client=mock_client)
    messages = [LLMMessage(role="user", content="test")]
    resp = await provider.generate(messages, "gpt-4o-mini", "chat")

    assert resp.content == "Mocked response"
    assert resp.provider == "openrouter"
    assert resp.input_token_count == 10


@pytest.mark.asyncio
async def test_openrouter_auth_header_not_in_error():
    """API key must NOT appear in LLMProviderError messages."""
    import httpx
    from app.services.llm_gateway.openrouter_provider import OpenRouterProvider

    api_key = "sk-secret-key-12345"
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Unauthorized", request=MagicMock(), response=mock_response
    )
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    provider = OpenRouterProvider(api_key=api_key, http_client=mock_client)
    with pytest.raises(LLMProviderError) as exc_info:
        await provider.generate([LLMMessage(role="user", content="test")], "model", "chat")

    assert api_key not in str(exc_info.value)


@pytest.mark.asyncio
async def test_openrouter_prompt_not_in_error_on_timeout():
    """Prompt content must NOT appear in error messages on timeout."""
    import httpx
    from app.services.llm_gateway.openrouter_provider import OpenRouterProvider

    secret = "Very sensitive HR content"
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    provider = OpenRouterProvider(api_key="test-key", http_client=mock_client)
    with pytest.raises(LLMProviderError) as exc_info:
        await provider.generate([LLMMessage(role="user", content=secret)], "model", "chat")

    assert secret not in str(exc_info.value)


@pytest.mark.asyncio
async def test_gateway_full_flow_with_openrouter():
    """End-to-end: gateway privacy check → OpenRouter HTTP mock → LLMResponse."""
    from app.services.llm_gateway.openrouter_provider import OpenRouterProvider

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "model": "openai/gpt-oss-120b:free",
        "choices": [{"message": {"content": "על פי תקשי\"ר, הוראות אלה חלות על כלל עובדי המדינה."}}],
        "usage": {"prompt_tokens": 150, "completion_tokens": 30},
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    provider = OpenRouterProvider(api_key="sk-test", http_client=mock_client)
    messages = [LLMMessage(role="user", content="על מי חלות הוראות התקשי\"ר?")]

    with patch("app.services.llm_gateway.gateway.get_llm_provider", return_value=provider), \
         patch("app.services.llm_gateway.gateway.settings") as mock_settings:
        mock_settings.default_chat_model = "openai/gpt-oss-120b:free"
        mock_settings.fallback_chat_model = "openai/gpt-oss-20b:free"
        resp = await generate_with_gateway(messages, "chat", db=None)

    assert "תקשי" in resp.content
    assert resp.provider == "openrouter"
    assert resp.input_token_count == 150
    assert resp.output_token_count == 30
