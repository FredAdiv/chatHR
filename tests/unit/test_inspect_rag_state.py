"""Unit tests for scripts.inspect_rag_state."""
from __future__ import annotations

import importlib
import sys
import types


def test_module_importable(monkeypatch):
    """Script is importable without a live DB connection."""
    # Stub out app dependencies so import doesn't try to connect to DB or config
    fake_settings = types.SimpleNamespace(async_database_url="postgresql+asyncpg://x/y")
    fake_config = types.ModuleType("app.core.config")
    fake_config.settings = fake_settings  # type: ignore[attr-defined]

    for mod_name in [
        "app", "app.core", "app.core.config",
        "app.db", "app.db.base", "app.db.models",
        "app.db.models.chunk_embedding",
        "app.db.models.document_chunk",
        "app.db.models.index_version",
        "app.db.models.knowledge_source",
        "app.db.models.parsed_document",
        "app.db.models.source_document",
    ]:
        if mod_name not in sys.modules:
            monkeypatch.setitem(sys.modules, mod_name, types.ModuleType(mod_name))

    monkeypatch.setitem(sys.modules, "app.core.config", fake_config)

    # Stub SQLAlchemy-dependent model modules with empty namespaces
    for model_mod in [
        "app.db.models.chunk_embedding",
        "app.db.models.document_chunk",
        "app.db.models.index_version",
        "app.db.models.knowledge_source",
        "app.db.models.parsed_document",
        "app.db.models.source_document",
    ]:
        m = types.ModuleType(model_mod)
        class_name = model_mod.split(".")[-1]
        # Add a dummy class for each expected model
        setattr(m, _to_class_name(class_name), type(_to_class_name(class_name), (), {}))
        monkeypatch.setitem(sys.modules, model_mod, m)

    # Stub pgvector so SQLAlchemy models don't fail on import
    pgvector_mod = types.ModuleType("pgvector")
    pgvector_sqlalchemy = types.ModuleType("pgvector.sqlalchemy")
    pgvector_sqlalchemy.Vector = lambda *a, **kw: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pgvector", pgvector_mod)
    monkeypatch.setitem(sys.modules, "pgvector.sqlalchemy", pgvector_sqlalchemy)

    if "scripts.inspect_rag_state" in sys.modules:
        del sys.modules["scripts.inspect_rag_state"]

    # Import should succeed without DB
    mod = importlib.import_module("scripts.inspect_rag_state")
    assert hasattr(mod, "run_diagnostic")
    assert hasattr(mod, "_truncate_excerpt")


def _to_class_name(snake: str) -> str:
    return "".join(word.capitalize() for word in snake.split("_"))


def test_excerpt_truncated_at_300():
    from scripts.inspect_rag_state import _truncate_excerpt
    long_text = "א" * 400
    result = _truncate_excerpt(long_text)
    assert len(result) <= 301  # 300 chars + "…"
    assert result.endswith("…")


def test_excerpt_short_text_unchanged():
    from scripts.inspect_rag_state import _truncate_excerpt
    short = "קצובת נסיעה לעובד"
    assert _truncate_excerpt(short) == short


def test_excerpt_exactly_300_unchanged():
    from scripts.inspect_rag_state import _truncate_excerpt
    text = "x" * 300
    assert _truncate_excerpt(text) == text
    assert not _truncate_excerpt(text).endswith("…")


def test_excerpt_301_is_truncated():
    from scripts.inspect_rag_state import _truncate_excerpt
    text = "y" * 301
    result = _truncate_excerpt(text)
    assert result.endswith("…")
    assert len(result) == 301  # 300 chars + ellipsis char
