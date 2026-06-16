from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://chathr_user:CHANGE_ME@postgres:5432/chathr"
    redis_url: str = "redis://redis:6379"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
