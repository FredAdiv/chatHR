"""Unit tests for the fake deterministic embedding provider."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import math
import pytest

from app.services.embeddings.fake_provider import FakeLocalProvider
from app.services.embeddings.factory import get_embedding_provider
from app.services.embeddings.base import EmbeddingProvider


# ── Provider conformance ──────────────────────────────────────────────────────

def test_fake_provider_implements_protocol():
    provider = FakeLocalProvider()
    assert isinstance(provider, EmbeddingProvider)


def test_fake_provider_model_name():
    provider = FakeLocalProvider(model_name="test-model")
    assert provider.model_name == "test-model"


def test_fake_provider_dimension():
    provider = FakeLocalProvider(dimension=32)
    assert provider.dimension == 32


# ── Determinism ───────────────────────────────────────────────────────────────

def test_fake_provider_same_text_gives_same_vector():
    provider = FakeLocalProvider(dimension=16)
    v1 = provider.embed_texts(["Government employment policy"])[0]
    v2 = provider.embed_texts(["Government employment policy"])[0]
    assert v1 == v2


def test_fake_provider_different_texts_give_different_vectors():
    provider = FakeLocalProvider(dimension=16)
    v1 = provider.embed_texts(["pension regulations"])[0]
    v2 = provider.embed_texts(["recruitment process"])[0]
    assert v1 != v2


# ── Dimension ─────────────────────────────────────────────────────────────────

def test_configured_dimension_respected():
    for dim in [8, 16, 32, 64]:
        provider = FakeLocalProvider(dimension=dim)
        v = provider.embed_texts(["some text"])[0]
        assert len(v) == dim, f"Expected {dim}, got {len(v)}"


def test_vector_is_unit_length():
    provider = FakeLocalProvider(dimension=16)
    v = provider.embed_texts(["civil service leave policy"])[0]
    magnitude = math.sqrt(sum(f * f for f in v))
    assert abs(magnitude - 1.0) < 1e-6


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_text_returns_zero_vector():
    provider = FakeLocalProvider(dimension=16)
    v = provider.embed_texts([""])[0]
    assert len(v) == 16
    assert all(f == 0.0 for f in v)


def test_embed_texts_returns_one_per_input():
    provider = FakeLocalProvider(dimension=16)
    texts = ["a", "b", "c"]
    results = provider.embed_texts(texts)
    assert len(results) == 3
    for v in results:
        assert len(v) == 16


def test_invalid_dimension_raises():
    with pytest.raises(ValueError):
        FakeLocalProvider(dimension=0)


# ── No external calls ─────────────────────────────────────────────────────────

def test_no_external_calls(monkeypatch):
    """Fake provider must not make network calls."""
    import socket
    original_connect = socket.socket.connect

    def _block(*args, **kwargs):
        raise AssertionError("FakeLocalProvider must not make network calls")

    monkeypatch.setattr(socket.socket, "connect", _block)
    provider = FakeLocalProvider(dimension=16)
    # Should not raise
    provider.embed_texts(["HR policy document"])


# ── Factory ───────────────────────────────────────────────────────────────────

def test_factory_returns_fake_local(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.embedding_provider", "fake-local")
    monkeypatch.setattr("app.core.config.settings.embedding_dimension", 16)
    monkeypatch.setattr("app.core.config.settings.embedding_model", "fake-local-v1")
    provider = get_embedding_provider()
    assert isinstance(provider, EmbeddingProvider)
    assert provider.model_name == "fake-local-v1"
    assert provider.dimension == 16


def test_factory_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.embedding_provider", "openai")
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        get_embedding_provider()
