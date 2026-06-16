"""Admin LLM Gateway API — health check and debug test-generate.

All endpoints require system_admin.
Not for regular chat users — admin/debug only.
Privacy guard runs on all test-generate requests.
No real OpenRouter calls in MVP (fake-local provider).
Matched sensitive text is never returned in responses.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.config import settings
from app.core.roles import RoleName
from app.db.models.user import User
from app.db.session import get_db
from app.services.llm_gateway.gateway import generate_with_gateway
from app.services.llm_gateway.protocol import LLMMessage, PrivacyGuardBlockedError

router = APIRouter(prefix="/admin/llm-gateway", tags=["llm-gateway"])

_GATEWAY_ROLES = [RoleName.SYSTEM_ADMIN]


# ── Request / Response models ─────────────────────────────────────────────────

class HealthResponse(BaseModel):
    provider_configured: str
    default_model: str
    fallback_model_configured: bool
    privacy_guard_enabled: bool
    openrouter_configured: bool


class TestGenerateRequest(BaseModel):
    message: str = Field(..., min_length=1)
    purpose: str = Field(default="debug")
    model: str | None = None


class TestGenerateResponse(BaseModel):
    content: str
    model: str
    provider: str
    used_fallback: bool


class FindingSummaryItem(BaseModel):
    type: str
    severity: str
    # matched_text intentionally absent — never expose raw sensitive text in API


# ── GET /admin/llm-gateway/health ─────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def gateway_health(
    _current_user: User = Depends(require_any_role(_GATEWAY_ROLES)),
):
    """LLM Gateway configuration summary.

    Reports whether OpenRouter is configured (boolean only — key is never returned).
    No DB query performed.
    """
    openrouter_configured = bool(
        settings.openrouter_api_key and settings.openrouter_api_key != "CHANGE_ME"
    )
    return HealthResponse(
        provider_configured=settings.llm_provider,
        default_model=settings.default_chat_model,
        fallback_model_configured=bool(settings.fallback_chat_model),
        privacy_guard_enabled=True,
        openrouter_configured=openrouter_configured,
    )


# ── POST /admin/llm-gateway/test-generate ────────────────────────────────────

@router.post("/test-generate", response_model=TestGenerateResponse)
async def test_generate(
    body: TestGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role(_GATEWAY_ROLES)),
):
    """Admin/debug: send a single message through the full gateway pipeline.

    Uses the configured provider (fake-local in MVP — no real OpenRouter calls).
    Privacy guard runs — high-severity PII returns 422 with a safe summary.
    Matched sensitive text is never included in the 422 response.
    Full message content is never stored.
    """
    messages = [LLMMessage(role="user", content=body.message)]

    try:
        response = await generate_with_gateway(
            messages=messages,
            purpose=body.purpose,
            model=body.model,
            user_id=current_user.id,
            db=db,
        )
        await db.commit()
    except PrivacyGuardBlockedError as exc:
        # Return 422 with safe findings — matched_text is NOT included
        from app.services.privacy.guard import check_text
        result = check_text(body.message)
        safe_findings = [
            FindingSummaryItem(type=f.type, severity=f.severity).model_dump()
            for f in result.findings
        ]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "privacy_guard_blocked",
                "reason": str(exc),
                "findings": safe_findings,
            },
        ) from exc

    return TestGenerateResponse(
        content=response.content,
        model=response.model,
        provider=response.provider,
        used_fallback=response.used_fallback,
    )
