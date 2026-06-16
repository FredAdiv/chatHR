from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://chathr_user:CHANGE_ME@postgres:5432/chathr"
    redis_url: str = "redis://redis:6379"

    # JWT — local MVP auth only, not production SSO
    jwt_secret_key: str = "CHANGE_ME_USE_A_LONG_RANDOM_SECRET"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # MinIO object storage
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "CHANGE_ME"
    minio_secret_key: str = "CHANGE_ME"
    minio_bucket_documents: str = "chathr-documents"
    minio_secure: bool = False

    # Embedding provider
    # fake-local: deterministic SHA-256 hash vectors, no network, dev/tests only
    # openrouter: real semantic embeddings via OpenRouter API
    embedding_provider: str = "fake-local"
    embedding_dimension: int = 16           # used by fake-local only
    embedding_model: str = "fake-local-v1"  # used by fake-local only
    openrouter_embedding_model: str = "openai/text-embedding-3-small"
    # Set to false in production to prevent activating a fake-local index
    embedding_fake_local_allowed: bool = True

    # LLM Gateway — all model calls must go through the gateway with privacy guard
    # fake-local: no external calls, deterministic, safe for tests/dev
    # openrouter: requires OPENROUTER_API_KEY; not active unless explicitly selected
    llm_provider: str = "fake-local"
    openrouter_api_key: str = ""
    default_chat_model: str = "anthropic/claude-haiku-4-5-20251001"
    fallback_chat_model: str = "openai/gpt-4o-mini"
    llm_request_timeout_seconds: int = 30

    @property
    def async_database_url(self) -> str:
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
