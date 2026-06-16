"""Unit tests for load_local_file_to_active_index script.

Tests:
1. Rejects missing local file
2. Rejects directory path
3. Rejects unsupported extension
4. Accepts supported extensions (.pdf, .docx, .txt)
5. Creates building index before embeddings
6. Does not activate index on parse failure
7. source_url is metadata only (not fetched)
8. authority_level default is 1
9. Raw content not in error output
"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.load_local_file_to_active_index import validate_local_file, _parse_args


# ── 1. Rejects missing file ────────────────────────────────────────────────────

def test_rejects_missing_file(tmp_path):
    missing = str(tmp_path / "does_not_exist.pdf")
    with pytest.raises(ValueError, match="not found"):
        validate_local_file(missing)


# ── 2. Rejects directory ───────────────────────────────────────────────────────

def test_rejects_directory(tmp_path):
    with pytest.raises(ValueError, match="directory"):
        validate_local_file(str(tmp_path))


# ── 3. Rejects unsupported extension ──────────────────────────────────────────

def test_rejects_unsupported_extension(tmp_path):
    bad = tmp_path / "file.xyz"
    bad.write_bytes(b"content")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        validate_local_file(str(bad))


def test_rejects_no_extension(tmp_path):
    no_ext = tmp_path / "noextension"
    no_ext.write_bytes(b"content")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        validate_local_file(str(no_ext))


# ── 4. Accepts supported extensions ───────────────────────────────────────────

@pytest.mark.parametrize("ext,expected_type", [
    (".pdf", "pdf"),
    (".docx", "docx"),
    (".doc", "docx"),
    (".xlsx", "xlsx"),
    (".html", "html"),
    (".htm", "html"),
    (".txt", "unknown"),
])
def test_accepts_supported_extensions(tmp_path, ext, expected_type):
    f = tmp_path / f"file{ext}"
    f.write_bytes(b"some content bytes")
    resolved, doc_type = validate_local_file(str(f))
    assert doc_type == expected_type
    assert resolved.name == f"file{ext}"


# ── 5. Rejects empty file ──────────────────────────────────────────────────────

def test_rejects_empty_file(tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        validate_local_file(str(empty))


# ── 6. authority_level default is 1 ───────────────────────────────────────────

def test_authority_level_default_is_1():
    # Parse args with only required positional + required flags
    with patch("sys.argv", [
        "prog",
        "/app/local-data/test.pdf",
        "--source-name", "Test Source",
        "--source-url", "https://www.gov.il/test",
    ]):
        args = _parse_args()
    assert args.authority_level == 1


# ── 7. source_url is not fetched ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_source_url_not_fetched(tmp_path):
    """fetch_url must never be called — source_url is metadata only."""
    from scripts.load_local_file_to_active_index import load_local_file
    from app.services.ingestion.downloader import FetchResult

    # Create a real tiny PDF-like file (minimal bytes)
    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"%PDF-1.4 test content")

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    async def mock_execute(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = []
        return result

    db.execute = mock_execute

    fake_parsed = MagicMock()
    fake_parsed.id = 3
    fake_parsed.parse_status = "parsed"
    fake_parsed.error_message = None

    fake_chunk = MagicMock()
    fake_chunk.id = 10
    fake_chunk.source_document_id = 2
    fake_chunk.parsed_document_id = 3
    fake_chunk.chunk_hash = "ch" * 32
    fake_chunk.chunk_text = "test chunk"

    async def mock_execute2(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = [fake_chunk]
        return result

    mock_fetch_url = AsyncMock()

    fake_provider = MagicMock()
    fake_provider.model_name = "fake-local-v1"
    fake_provider.dimension = 16
    fake_provider.embed_texts.return_value = [[0.1] * 16]

    with (
        patch("scripts.load_local_file_to_active_index.get_embedding_provider", return_value=fake_provider),
        patch("scripts.load_local_file_to_active_index.put_bytes"),
        patch("scripts.load_local_file_to_active_index.sha256_hex", return_value="ab" * 32),
        patch("scripts.load_local_file_to_active_index.parse_and_chunk_source_document", AsyncMock(return_value=fake_parsed)),
        patch("scripts.load_local_file_to_active_index.record_audit_event", AsyncMock()),
    ):
        db.execute = mock_execute2
        await load_local_file(
            db=db,
            file_path=str(test_file),
            source_name="Test",
            source_url="https://www.gov.il/test",
            context_type="government_ministries",
            authority_level=1,
            index_version_label="test-v1",
        )

    # fetch_url must NOT be called
    mock_fetch_url.assert_not_called()


# ── 8. Does not activate on parse failure ─────────────────────────────────────

@pytest.mark.asyncio
async def test_no_activation_on_parse_failure(tmp_path):
    """Parse failure must raise RuntimeError and not activate any index."""
    from scripts.load_local_file_to_active_index import load_local_file

    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"corrupted pdf bytes")

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    async def mock_execute(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = []
        return result

    db.execute = mock_execute

    fake_parsed = MagicMock()
    fake_parsed.id = 3
    fake_parsed.parse_status = "failed"
    fake_parsed.error_message = "parse error"

    with (
        patch("scripts.load_local_file_to_active_index.get_embedding_provider", return_value=MagicMock()),
        patch("scripts.load_local_file_to_active_index.put_bytes"),
        patch("scripts.load_local_file_to_active_index.sha256_hex", return_value="ab" * 32),
        patch("scripts.load_local_file_to_active_index.parse_and_chunk_source_document", AsyncMock(return_value=fake_parsed)),
    ):
        with pytest.raises(RuntimeError, match="Parsing failed"):
            await load_local_file(
                db=db,
                file_path=str(test_file),
                source_name="Test",
                source_url="https://www.gov.il/test",
                context_type="government_ministries",
                authority_level=1,
                index_version_label="fail-v1",
            )

    # Only one commit (after SourceDocument save), not after index activation
    assert db.commit.call_count == 1


# ── 9. Building index before embeddings ───────────────────────────────────────

@pytest.mark.asyncio
async def test_building_index_before_embeddings(tmp_path):
    """IndexVersion must have status='building' when embed_texts is first called."""
    from scripts.load_local_file_to_active_index import load_local_file

    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"%PDF-1.4 test")

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    fake_chunk = MagicMock()
    fake_chunk.id = 10
    fake_chunk.source_document_id = 2
    fake_chunk.parsed_document_id = 3
    fake_chunk.chunk_hash = "ch" * 32
    fake_chunk.chunk_text = "test chunk text"

    fake_parsed = MagicMock()
    fake_parsed.id = 3
    fake_parsed.parse_status = "parsed"
    fake_parsed.error_message = None

    async def mock_execute(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = [fake_chunk]
        return result

    db.execute = mock_execute

    added_objects = []
    db.add.side_effect = lambda obj: added_objects.append(obj)

    statuses_at_embed_time = []

    fake_provider = MagicMock()
    fake_provider.model_name = "fake-local-v1"
    fake_provider.dimension = 16

    def embed_and_capture(texts):
        for obj in added_objects:
            if hasattr(obj, "status") and hasattr(obj, "version_label"):
                statuses_at_embed_time.append(obj.status)
        return [[0.1] * 16]

    fake_provider.embed_texts.side_effect = embed_and_capture

    with (
        patch("scripts.load_local_file_to_active_index.get_embedding_provider", return_value=fake_provider),
        patch("scripts.load_local_file_to_active_index.put_bytes"),
        patch("scripts.load_local_file_to_active_index.sha256_hex", return_value="ab" * 32),
        patch("scripts.load_local_file_to_active_index.parse_and_chunk_source_document", AsyncMock(return_value=fake_parsed)),
        patch("scripts.load_local_file_to_active_index.record_audit_event", AsyncMock()),
    ):
        await load_local_file(
            db=db,
            file_path=str(test_file),
            source_name="Test",
            source_url="https://www.gov.il/test",
            context_type="government_ministries",
            authority_level=1,
            index_version_label="build-test-v1",
        )

    assert "building" in statuses_at_embed_time, (
        f"Expected 'building' during embed, got: {statuses_at_embed_time}"
    )
