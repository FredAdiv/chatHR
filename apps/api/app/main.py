from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin_audit_logs import router as admin_audit_logs_router
from app.api.admin_embeddings import router as admin_embeddings_router
from app.api.admin_feedback import router as admin_feedback_router
from app.api.admin_llm_gateway import router as admin_llm_gateway_router
from app.api.admin_faq import router as admin_faq_router
from app.api.admin_retrieval import router as admin_retrieval_router
from app.api.admin_index_versions import router as admin_index_versions_router
from app.api.admin_ingestion import router as admin_ingestion_router
from app.api.admin_parsing import router as admin_parsing_router
from app.api.admin_knowledge_sources import router as admin_knowledge_sources_router
from app.api.admin_knowledge_upload import router as admin_knowledge_upload_router
from app.api.admin_knowledge_process import router as admin_knowledge_process_router
from app.api.admin_knowledge_index import router as admin_knowledge_index_router
from app.api.admin_users import router as admin_users_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.dev import router as dev_router
from app.api.knowledge_chunks import router as knowledge_chunks_router
from app.core.config import settings

app = FastAPI(
    title="ChatHR API",
    description="Secure AI chat for HR employees in Israeli government and civil service.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_users_router)
app.include_router(admin_faq_router)
app.include_router(admin_knowledge_sources_router)
app.include_router(admin_knowledge_upload_router)
app.include_router(admin_knowledge_process_router)
app.include_router(admin_knowledge_index_router)
app.include_router(admin_index_versions_router)
app.include_router(admin_ingestion_router)
app.include_router(admin_parsing_router)
app.include_router(admin_embeddings_router)
app.include_router(admin_retrieval_router)
app.include_router(admin_llm_gateway_router)
app.include_router(chat_router)
app.include_router(knowledge_chunks_router)
app.include_router(admin_feedback_router)
app.include_router(admin_audit_logs_router)
# DEV-ONLY router — remove or gate behind feature flag before production
app.include_router(dev_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "chathr-api"}


@app.get("/ready")
async def ready():
    checks: dict[str, str] = {}

    try:
        import asyncpg
        conn = await asyncpg.connect(settings.database_url, timeout=3)
        await conn.execute("SELECT 1")
        await conn.close()
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "error"

    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
    }
