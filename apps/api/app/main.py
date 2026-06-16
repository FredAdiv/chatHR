from fastapi import FastAPI
from app.core.config import settings

app = FastAPI(
    title="ChatHR API",
    description="Secure AI chat for HR employees in Israeli government and civil service.",
    version="0.1.0",
)


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
    except Exception as e:
        checks["postgres"] = f"error: {type(e).__name__}"

    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {type(e).__name__}"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
    }
