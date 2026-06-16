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

    # Embedding provider — fake-local for MVP/dev/tests only
    # Real providers must pass through the LLM Gateway and privacy guard (future work)
    embedding_provider: str = "fake-local"
    embedding_dimension: int = 16
    embedding_model: str = "fake-local-v1"

    @property
    def async_database_url(self) -> str:
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
