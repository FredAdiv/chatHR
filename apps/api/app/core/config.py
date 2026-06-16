from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://chathr_user:CHANGE_ME@postgres:5432/chathr"
    redis_url: str = "redis://redis:6379"

    # JWT — local MVP auth only, not production SSO
    jwt_secret_key: str = "CHANGE_ME_USE_A_LONG_RANDOM_SECRET"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    @property
    def async_database_url(self) -> str:
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
