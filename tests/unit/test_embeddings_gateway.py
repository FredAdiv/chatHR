"""Targeted tests for the Embeddings Gateway (real-embeddings-gateway-1)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.embeddings.fake_provider import FakeLocalProvider
from app.services.embeddings.factory import get_embedding_provider


# ── Gateway dispatches to fake-local ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_gateway_uses_fake_local_by_default():
    from app.services.embeddings.gateway import embed_with_gateway
    with patch("app.services.embeddings.gateway.settings") as mock_settings:
        mock_settings.embedding_provider = "fake-local"
        mock_settings.embedding_model = "fake-local-v1"
        mock_settings.embedding_dimension = 16
        result = await embed_with_gateway(["test text"])
    assert len(result) == 1
    assert len(result[0]) == 16


@pytest.mark.asyncio
async def test_gateway_fake_local_is_deterministic():
    from app.services.embeddings.gateway import embed_with_gateway
    with patch("app.services.embeddings.gateway.settings") as mock_settings:
        mock_settings.embedding_provider = "fake-local"
        mock_settings.embedding_model = "fake-local-v1"
        mock_settings.embedding_dimension = 16
        r1 = await embed_with_gateway(["government HR policy"])
        r2 = await embed_with_gateway(["government HR policy"])
    assert r1 == r2


@pytest.mark.asyncio
async def test_gateway_unknown_provider_raises():
    from app.services.embeddings.gateway import embed_with_gateway
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        await embed_with_gateway(["text"], embedding_provider="nonexistent")


# ── Gateway dispatches to OpenRouter ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_gateway_openrouter_makes_http_call():
    from app.services.embeddings.gateway import embed_with_gateway

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": [{"embedding": [0.1] * 1536, "index": 0}]
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    with patch("app.services.embeddings.gateway.settings") as mock_settings, \
         patch("app.services.embeddings.openrouter_provider.httpx.AsyncClient", return_value=mock_client):
        mock_settings.embedding_provider = "openrouter"
        mock_settings.openrouter_api_key = "sk-test-key"
        mock_settings.openrouter_embedding_model = "openai/text-embedding-3-small"
        mock_settings.llm_request_timeout_seconds = 30

        result = await embed_with_gateway(["על מי חלות הוראות התקשיר?"])

    assert len(result) == 1
    assert len(result[0]) == 1536


@pytest.mark.asyncio
async def test_gateway_openrouter_rejects_placeholder_key():
    from app.services.embeddings.gateway import embed_with_gateway

    with patch("app.services.embeddings.gateway.settings") as mock_settings:
        mock_settings.embedding_provider = "openrouter"
        mock_settings.openrouter_api_key = "REPLACE_WITH_REAL_KEY_FOR_OPENROUTER"
        mock_settings.openrouter_embedding_model = "openai/text-embedding-3-small"
        mock_settings.llm_request_timeout_seconds = 30

        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            await embed_with_gateway(["text"])


# ── OpenRouter provider direct tests ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_openrouter_provider_requires_api_key():
    from app.services.embeddings.openrouter_provider import OpenRouterEmbeddingProvider
    with pytest.raises(ValueError, match="API key"):
        OpenRouterEmbeddingProvider(api_key="", model="openai/text-embedding-3-small")


@pytest.mark.asyncio
async def test_openrouter_provider_injectable_client():
    from app.services.embeddings.openrouter_provider import OpenRouterEmbeddingProvider

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {"embedding": [0.5] * 1536, "index": 0},
            {"embedding": [0.3] * 1536, "index": 1},
        ]
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    provider = OpenRouterEmbeddingProvider(
        api_key="sk-test",
        model="openai/text-embedding-3-small",
        http_client=mock_client,
    )
    result = await provider.embed(["text one", "text two"])

    assert len(result) == 2
    assert len(result[0]) == 1536
    assert len(result[1]) == 1536
    assert provider.dimension == 1536


@pytest.mark.asyncio
async def test_openrouter_provider_api_key_not_in_error():
    import httpx
    from app.services.embeddings.openrouter_provider import OpenRouterEmbeddingProvider, EmbeddingProviderError

    api_key = "sk-secret-embedding-key-99999"
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Unauthorized", request=MagicMock(), response=mock_resp
    )
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    provider = OpenRouterEmbeddingProvider(
        api_key=api_key,
        model="openai/text-embedding-3-small",
        http_client=mock_client,
    )
    with pytest.raises(EmbeddingProviderError) as exc_info:
        await provider.embed(["sensitive text"])

    assert api_key not in str(exc_info.value)


@pytest.mark.asyncio
async def test_openrouter_provider_timeout_not_in_error():
    import httpx
    from app.services.embeddings.openrouter_provider import OpenRouterEmbeddingProvider, EmbeddingProviderError

    secret_text = "Highly sensitive employee PII content"
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    provider = OpenRouterEmbeddingProvider(
        api_key="sk-test",
        model="openai/text-embedding-3-small",
        http_client=mock_client,
    )
    with pytest.raises(EmbeddingProviderError) as exc_info:
        await provider.embed([secret_text])

    assert secret_text not in str(exc_info.value)


# ── Factory supports openrouter ───────────────────────────────────────────────

def test_factory_creates_openrouter_provider():
    from app.services.embeddings.openrouter_provider import OpenRouterEmbeddingProvider
    with patch("app.services.embeddings.factory.settings") as mock_settings:
        mock_settings.embedding_provider = "openrouter"
        mock_settings.openrouter_api_key = "sk-or-real-key"
        mock_settings.openrouter_embedding_model = "openai/text-embedding-3-small"
        mock_settings.llm_request_timeout_seconds = 30
        provider = get_embedding_provider()
    assert isinstance(provider, OpenRouterEmbeddingProvider)
    assert provider.provider_name == "openrouter"


def test_factory_openrouter_rejects_placeholder_key():
    with patch("app.services.embeddings.factory.settings") as mock_settings:
        mock_settings.embedding_provider = "openrouter"
        mock_settings.openrouter_api_key = "CHANGE_ME"
        mock_settings.openrouter_embedding_model = "openai/text-embedding-3-small"
        mock_settings.llm_request_timeout_seconds = 30
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            get_embedding_provider()


# ── Quality check: fake embeddings rejected in production ─────────────────────

@pytest.mark.asyncio
async def test_quality_check_fails_fake_embeddings_in_production():
    """quality-check must fail if embedding_provider=fake-local and production mode."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock
    from app.db.models.index_version import IndexVersion

    iv = MagicMock(spec=IndexVersion)
    iv.id = uuid.uuid4()
    iv.status = "draft"
    iv.embedding_provider = "fake-local"
    iv.embedding_model = "fake-local-v1"
    iv.embedding_dimensions = 16

    # Simulate quality check internals with fake-local not allowed
    from app.services.embeddings.gateway import embed_with_gateway
    with patch("app.api.admin_knowledge_index.settings") as mock_settings:
        mock_settings.embedding_fake_local_allowed = False
        # Call the private helper directly
        from app.api.admin_knowledge_index import _run_quality_checks

        mock_db = AsyncMock()
        # has_embeddings check — return 1
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 1

        # orphan check — return 0
        mock_orphan = MagicMock()
        mock_orphan.scalar_one.return_value = 0

        # sd_id_rows
        mock_sd_ids = MagicMock()
        mock_sd_ids.scalars.return_value.all.return_value = []

        # sd_rows
        mock_sd_rows = MagicMock()
        mock_sd_rows.scalars.return_value.all.return_value = []

        # chunk texts
        mock_chunks = MagicMock()
        mock_chunks.scalars.return_value.all.return_value = ["some chunk text"]

        execute_results = [mock_count, mock_orphan, mock_sd_ids, mock_sd_rows, mock_sd_rows, mock_chunks]
        call_idx = [0]

        async def _execute(stmt, *args, **kwargs):
            i = call_idx[0]
            call_idx[0] += 1
            if i < len(execute_results):
                return execute_results[i]
            return MagicMock()

        mock_db.execute = AsyncMock(side_effect=_execute)
        checks = await _run_quality_checks(mock_db, iv)

    fake_check = next((c for c in checks if c.name == "embedding_not_fake_in_production"), None)
    assert fake_check is not None
    assert fake_check.passed is False


@pytest.mark.asyncio
async def test_quality_check_passes_fake_embeddings_in_dev():
    """quality-check passes for fake-local when embedding_fake_local_allowed=True."""
    import uuid
    from app.db.models.index_version import IndexVersion

    iv = MagicMock(spec=IndexVersion)
    iv.id = uuid.uuid4()
    iv.status = "draft"
    iv.embedding_provider = "fake-local"
    iv.embedding_model = "fake-local-v1"
    iv.embedding_dimensions = 16

    with patch("app.api.admin_knowledge_index.settings") as mock_settings:
        mock_settings.embedding_fake_local_allowed = True
        from app.api.admin_knowledge_index import _run_quality_checks

        mock_db = AsyncMock()
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 1
        mock_orphan = MagicMock()
        mock_orphan.scalar_one.return_value = 0
        mock_empty = MagicMock()
        mock_empty.scalars.return_value.all.return_value = []
        mock_chunks = MagicMock()
        mock_chunks.scalars.return_value.all.return_value = ["some chunk text"]

        results_seq = [mock_count, mock_orphan, mock_empty, mock_empty, mock_empty, mock_chunks]
        idx = [0]

        async def _execute(stmt, *args, **kwargs):
            i = idx[0]; idx[0] += 1
            return results_seq[i] if i < len(results_seq) else MagicMock()

        mock_db.execute = AsyncMock(side_effect=_execute)
        checks = await _run_quality_checks(mock_db, iv)

    fake_check = next((c for c in checks if c.name == "embedding_not_fake_in_production"), None)
    assert fake_check is not None
    assert fake_check.passed is True


# ── IndexVersion stores embedding metadata ────────────────────────────────────

def test_index_version_model_has_embedding_fields():
    from app.db.models.index_version import IndexVersion
    cols = {c.name for c in IndexVersion.__table__.columns}
    assert "embedding_provider" in cols
    assert "embedding_dimensions" in cols
    assert "embedding_model" in cols


# ── get_embedding_dimension helper ────────────────────────────────────────────

def test_get_embedding_dimension_fake_local():
    from app.services.embeddings.gateway import get_embedding_dimension
    with patch("app.services.embeddings.gateway.settings") as mock_settings:
        mock_settings.embedding_provider = "fake-local"
        mock_settings.embedding_dimension = 16
        dim = get_embedding_dimension("fake-local")
    assert dim == 16


def test_get_embedding_dimension_openrouter():
    from app.services.embeddings.gateway import get_embedding_dimension
    dim = get_embedding_dimension("openrouter")
    assert dim == 1536
