"""Seed local demo data for ChatHR manual testing.

Creates a chat user, knowledge source, document, parsed chunks, fake-local
embeddings, and an active index version so the full RAG chat flow can be
tested end-to-end without real documents or external services.

DEMO DATA ONLY — not real official policy.

Usage (inside the API container):
    python -m scripts.seed_demo_chat_data

Idempotent: safe to run multiple times without creating duplicates.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.db.models.chunk_embedding import ChunkEmbedding
from app.db.models.document_chunk import DocumentChunk
from app.db.models.index_version import IndexVersion
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.parsed_document import ParsedDocument
from app.db.models.role import Role
from app.db.models.source_document import SourceDocument
from app.db.models.user import User
from app.db.models.user_role import UserRole
from app.services.embeddings.factory import get_embedding_provider
from app.services.ingestion.hash_utils import sha256_hex

# ── Demo constants ─────────────────────────────────────────────────────────────

DEMO_USER_EMAIL = "chat@example.com"
DEMO_USER_PASSWORD = "chat_dev_password"
DEMO_USER_DISPLAY = "Demo Chat User"

DEMO_KS_NAME = "Demo HR Policy Source"
DEMO_DOC_URL = "https://www.gov.il/he/demo/chathr-local-demo"
DEMO_DOC_TITLE = "מסמך הדגמה מקומי - לא מקור רשמי אמיתי"

DEMO_INDEX_LABEL = "demo-local-v1"

DEMO_CHUNKS = [
    (
        0,
        "חופשת מחלה לעובד בשירות המדינה נבחנת לפי כללי הזכאות והמסמכים הרפואיים שהעובד מציג. "
        "לצורך הדגמת המערכת, עובד המבקש לנצל ימי מחלה נדרש להגיש אישור מחלה בהתאם לנוהלי המשרד.",
        "חופשת מחלה",
    ),
    (
        1,
        "חופשה שנתית לעובד בשירות המדינה מנוהלת לפי יתרת הזכאות והוראות המשרד. "
        "לצורך הדגמת המערכת, בקשת חופשה צריכה להיות מאושרת על ידי הגורם המוסמך.",
        "חופשה שנתית",
    ),
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _embed_chunk(provider, chunk_text: str, chunk_hash: str, chunk: DocumentChunk, iv_id, now: datetime) -> ChunkEmbedding:
    vector = provider.embed_texts([chunk_text])[0]
    return ChunkEmbedding(
        document_chunk_id=chunk.id,
        source_document_id=chunk.source_document_id,
        parsed_document_id=chunk.parsed_document_id,
        index_version_id=iv_id,
        embedding_model=provider.model_name,
        embedding_dimension=provider.dimension,
        embedding=vector,
        content_hash=chunk_hash,
        status="embedded",
        created_at=now,
        updated_at=now,
    )


# ── Main seed logic ────────────────────────────────────────────────────────────

async def seed(db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    provider = get_embedding_provider()

    # 1. Ensure chat_user role exists
    role = (await db.execute(select(Role).where(Role.name == "chat_user"))).scalar_one_or_none()
    if not role:
        print("ERROR: 'chat_user' role not found. Run 'python -m scripts.seed_roles' first.")
        sys.exit(1)

    # 2. Ensure demo chat user
    user = (await db.execute(select(User).where(User.email == DEMO_USER_EMAIL))).scalar_one_or_none()
    if not user:
        user = User(
            email=DEMO_USER_EMAIL,
            display_name=DEMO_USER_DISPLAY,
            password_hash=hash_password(DEMO_USER_PASSWORD),
        )
        db.add(user)
        await db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        await db.flush()
        print(f"  [+] Created demo user: {DEMO_USER_EMAIL}")
    else:
        # Ensure role is assigned
        existing_role = (
            await db.execute(
                select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
            )
        ).scalar_one_or_none()
        if not existing_role:
            db.add(UserRole(user_id=user.id, role_id=role.id))
            await db.flush()
            print(f"  [+] Assigned chat_user role to existing user: {DEMO_USER_EMAIL}")
        else:
            print(f"  [=] Demo user already exists: {DEMO_USER_EMAIL}")

    # 3. Ensure knowledge source
    ks = (
        await db.execute(select(KnowledgeSource).where(KnowledgeSource.name == DEMO_KS_NAME))
    ).scalar_one_or_none()
    if not ks:
        ks = KnowledgeSource(
            name=DEMO_KS_NAME,
            source_type="web",
            url=DEMO_DOC_URL,
            authority_level=3,
            is_active=True,
            context_type="government_ministries",
        )
        db.add(ks)
        await db.flush()
        print(f"  [+] Created knowledge source: {DEMO_KS_NAME}")
    else:
        print(f"  [=] Knowledge source exists: {DEMO_KS_NAME}")

    # 4. Ensure source document
    sd = (
        await db.execute(
            select(SourceDocument).where(
                SourceDocument.knowledge_source_id == ks.id,
                SourceDocument.url == DEMO_DOC_URL,
            )
        )
    ).scalar_one_or_none()
    if not sd:
        sd = SourceDocument(
            knowledge_source_id=ks.id,
            url=DEMO_DOC_URL,
            title=DEMO_DOC_TITLE,
            document_type="html",
            status="downloaded",
            first_seen_at=now,
            last_seen_at=now,
            downloaded_at=now,
            metadata_json={"demo": True, "note": "Not a real official document"},
        )
        db.add(sd)
        await db.flush()
        print("  [+] Created demo source document.")
    else:
        print("  [=] Demo source document exists.")

    # 5. Ensure parsed document
    full_text = "\n\n".join(text for _, text, _ in DEMO_CHUNKS)
    text_hash = sha256_hex(full_text.encode())
    pd = (
        await db.execute(
            select(ParsedDocument).where(
                ParsedDocument.source_document_id == sd.id,
                ParsedDocument.text_hash == text_hash,
            )
        )
    ).scalar_one_or_none()
    if not pd:
        pd = ParsedDocument(
            source_document_id=sd.id,
            parser_name="demo-seed",
            parser_version="1.0",
            text_content=full_text,
            text_hash=text_hash,
            language="he",
            parse_status="parsed",
        )
        db.add(pd)
        await db.flush()
        print("  [+] Created demo parsed document.")
    else:
        print("  [=] Demo parsed document exists.")

    # 6. Ensure document chunks
    chunks: list[DocumentChunk] = []
    chunk_hashes: list[str] = []
    for idx, text, section in DEMO_CHUNKS:
        chunk_hash = sha256_hex(text.encode())
        chunk = (
            await db.execute(
                select(DocumentChunk).where(
                    DocumentChunk.parsed_document_id == pd.id,
                    DocumentChunk.chunk_index == idx,
                )
            )
        ).scalar_one_or_none()
        if not chunk:
            chunk = DocumentChunk(
                parsed_document_id=pd.id,
                source_document_id=sd.id,
                chunk_index=idx,
                chunk_text=text,
                chunk_hash=chunk_hash,
                section_title=section,
                page_number=1,
                token_estimate=len(text.split()),
            )
            db.add(chunk)
            await db.flush()
            print(f"  [+] Created chunk {idx}: {section}")
        else:
            print(f"  [=] Chunk {idx} exists: {section}")
        chunks.append(chunk)
        chunk_hashes.append(chunk_hash)

    # 7. Ensure index version and embeddings
    iv = (
        await db.execute(
            select(IndexVersion).where(IndexVersion.version_label == DEMO_INDEX_LABEL)
        )
    ).scalar_one_or_none()

    if iv is None:
        # Create new index in 'building' state, embed, then activate
        iv = IndexVersion(
            version_label=DEMO_INDEX_LABEL,
            status="building",
            embedding_model=provider.model_name,
            created_at=now,
        )
        db.add(iv)
        await db.flush()
        print(f"  [+] Created index version: {DEMO_INDEX_LABEL}")

        for chunk, chunk_hash in zip(chunks, chunk_hashes):
            db.add(_embed_chunk(provider, chunk.chunk_text, chunk_hash, chunk, iv.id, now))
        await db.flush()
        print(f"  [+] Generated {len(chunks)} fake-local embeddings.")

        iv.status = "active"
        iv.activated_at = now
        await db.flush()
        print(f"  [+] Activated index: {DEMO_INDEX_LABEL}")

    elif iv.status == "building":
        # Generate missing embeddings and activate
        added = 0
        for chunk, chunk_hash in zip(chunks, chunk_hashes):
            exists = (
                await db.execute(
                    select(ChunkEmbedding).where(
                        ChunkEmbedding.document_chunk_id == chunk.id,
                        ChunkEmbedding.index_version_id == iv.id,
                    )
                )
            ).scalar_one_or_none()
            if not exists:
                db.add(_embed_chunk(provider, chunk.chunk_text, chunk_hash, chunk, iv.id, now))
                added += 1
        if added:
            await db.flush()
            print(f"  [+] Generated {added} missing embeddings.")
        iv.status = "active"
        iv.activated_at = now
        await db.flush()
        print(f"  [+] Activated index: {DEMO_INDEX_LABEL}")

    else:
        # Index is 'active' (or other state) — ensure embeddings exist
        print(f"  [=] Index '{DEMO_INDEX_LABEL}' already has status '{iv.status}'.")
        added = 0
        for chunk, chunk_hash in zip(chunks, chunk_hashes):
            exists = (
                await db.execute(
                    select(ChunkEmbedding).where(
                        ChunkEmbedding.document_chunk_id == chunk.id,
                        ChunkEmbedding.index_version_id == iv.id,
                    )
                )
            ).scalar_one_or_none()
            if not exists:
                db.add(_embed_chunk(provider, chunk.chunk_text, chunk_hash, chunk, iv.id, now))
                added += 1
        if added:
            await db.flush()
            print(f"  [+] Added {added} missing embeddings to existing index.")
        else:
            print("  [=] All embeddings already present.")

    await db.commit()


async def main() -> None:
    print("ChatHR demo seed — starting...")
    engine = create_async_engine(settings.async_database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            await seed(db)
    finally:
        await engine.dispose()

    print()
    print("Demo seed complete.")
    print(f"  Login:    {DEMO_USER_EMAIL} / {DEMO_USER_PASSWORD}")
    print("  Context:  government_ministries")
    print("  Question: מה הכללים לגבי חופשת מחלה?")
    print()
    print("NOTE: Responses use fake-local LLM — answer text is a placeholder.")
    print("      Source cards should appear with the demo knowledge source.")


if __name__ == "__main__":
    asyncio.run(main())
