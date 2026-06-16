"""Unit tests for load_single_source_to_active_index script.

Tests:
1. Rejects non-gov.il URLs
2. Does not activate index on parse failure
3. Creates IndexVersion with status=building before generating embeddings
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from scripts.load_single_source_to_active_index import validate_gov_il_url


# ── 1. URL validation ──────────────────────────────────────────────────────────

def test_rejects_non_gov_il_url():
    with pytest.raises(ValueError, match="gov.il"):
        validate_gov_il_url("https://example.com/some-page")


def test_rejects_localhost_url():
    with pytest.raises(ValueError):
        validate_gov_il_url("http://localhost/page")


def test_rejects_private_ip():
    with pytest.raises(ValueError):
        validate_gov_il_url("http://192.168.1.1/page")


def test_accepts_www_gov_il():
    result = validate_gov_il_url("https://www.gov.il/he/departments")
    assert result == "https://www.gov.il/he/departments"


def test_accepts_subdomain_gov_il():
    result = validate_gov_il_url("https://www.mod.gov.il/pages/policy.aspx")
    assert result.startswith("https://")


def test_rejects_gov_il_in_path_not_host():
    with pytest.raises(ValueError, match="gov.il"):
        validate_gov_il_url("https://attacker.com/fake/gov.il/policy")


# ── 2. No activation on parse failure ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_activation_on_parse_failure():
    """If parse_and_chunk_source_document returns a failed ParsedDocument,
    the script must raise RuntimeError and NOT activate any index."""
    from scripts.load_single_source_to_active_index import load_source
    from app.services.ingestion.downloader import FetchResult

    db = AsyncMock()

    # Make db.execute return empty results so no existing records are found
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    execute_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=execute_result)

    fake_ks = MagicMock()
    fake_ks.id = 1
    fake_sd = MagicMock()
    fake_sd.id = 2

    fake_parsed = MagicMock()
    fake_parsed.id = 3
    fake_parsed.parse_status = "failed"
    fake_parsed.error_message = "parser exploded"

    fake_fetch = FetchResult(
        url="https://www.gov.il/he/test",
        status_code=200,
        content_type="text/html",
        etag=None,
        last_modified=None,
        content=b"<html>content</html>",
        error=None,
    )

    with (
        patch("scripts.load_single_source_to_active_index.get_embedding_provider", return_value=MagicMock()),
        patch("scripts.load_single_source_to_active_index.fetch_url", AsyncMock(return_value=fake_fetch)),
        patch("scripts.load_single_source_to_active_index.put_bytes"),
        patch("scripts.load_single_source_to_active_index.sha256_hex", return_value="abc123" * 10),
        patch("scripts.load_single_source_to_active_index.detect_document_type", return_value="html"),
        patch("scripts.load_single_source_to_active_index.parse_and_chunk_source_document", AsyncMock(return_value=fake_parsed)),
    ):
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        # Patch db.execute to return KnowledgeSource / SourceDocument as None so they get created
        call_count = 0
        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            result.scalars.return_value.all.return_value = []
            return result

        db.execute = mock_execute

        # Simulate flush giving the fake models IDs
        def fake_add(obj):
            if hasattr(obj, "id") and obj.id is None:
                obj.id = call_count
        db.add.side_effect = fake_add

        with pytest.raises(RuntimeError, match="Parsing failed"):
            await load_source(
                db=db,
                url="https://www.gov.il/he/test",
                context_type="government_ministries",
                authority_level=3,
                source_name=None,
                index_version_label="test-v1",
            )

        # Commit is called once after saving SourceDocument (step 5), but never
        # again for index activation — confirmed by the RuntimeError raised in step 6.
        assert db.commit.call_count == 1, (
            f"Expected exactly 1 commit (source doc save), got {db.commit.call_count}"
        )


# ── 3. Building status before embeddings ──────────────────────────────────────

@pytest.mark.asyncio
async def test_index_building_before_embeddings():
    """IndexVersion must have status='building' when embed_texts is called."""
    from scripts.load_single_source_to_active_index import load_source
    from app.services.ingestion.downloader import FetchResult

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    statuses_at_embed_time = []

    fake_chunk = MagicMock()
    fake_chunk.id = 10
    fake_chunk.source_document_id = 2
    fake_chunk.parsed_document_id = 3
    fake_chunk.chunk_hash = "ch" * 32
    fake_chunk.chunk_text = "זהו טקסט בדיקה"

    fake_parsed = MagicMock()
    fake_parsed.id = 3
    fake_parsed.parse_status = "parsed"
    fake_parsed.error_message = None

    fake_fetch = FetchResult(
        url="https://www.gov.il/he/test",
        status_code=200,
        content_type="text/html",
        etag=None,
        last_modified=None,
        content=b"<html>test</html>",
        error=None,
    )

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        # Chunks query returns one chunk
        result.scalars.return_value.all.return_value = [fake_chunk]
        result.scalar_one_or_none.return_value = None
        return result

    db.execute = mock_execute

    added_objects = []

    def fake_add(obj):
        added_objects.append(obj)

    db.add.side_effect = fake_add

    fake_provider = MagicMock()
    fake_provider.model_name = "fake-local-v1"
    fake_provider.dimension = 16

    def embed_and_capture(texts):
        # Capture status of any IndexVersion objects added so far
        for obj in added_objects:
            if hasattr(obj, "status") and hasattr(obj, "version_label"):
                statuses_at_embed_time.append(obj.status)
        return [[0.1] * 16]

    fake_provider.embed_texts.side_effect = embed_and_capture

    with (
        patch("scripts.load_single_source_to_active_index.get_embedding_provider", return_value=fake_provider),
        patch("scripts.load_single_source_to_active_index.fetch_url", AsyncMock(return_value=fake_fetch)),
        patch("scripts.load_single_source_to_active_index.put_bytes"),
        patch("scripts.load_single_source_to_active_index.sha256_hex", return_value="ab" * 32),
        patch("scripts.load_single_source_to_active_index.detect_document_type", return_value="html"),
        patch("scripts.load_single_source_to_active_index.parse_and_chunk_source_document", AsyncMock(return_value=fake_parsed)),
        patch("scripts.load_single_source_to_active_index.record_audit_event", AsyncMock()),
    ):
        await load_source(
            db=db,
            url="https://www.gov.il/he/test",
            context_type="government_ministries",
            authority_level=3,
            source_name=None,
            index_version_label="test-build-v1",
        )

    # The IndexVersion must have been in 'building' state at embed time
    assert "building" in statuses_at_embed_time, (
        f"Expected 'building' status during embed, got: {statuses_at_embed_time}"
    )
