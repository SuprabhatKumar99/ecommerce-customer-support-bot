from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "Ecommerce Customer Support AI"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: str = "postgresql+asyncpg://support_admin:support_secure_password@localhost:5432/ecommerce_support"
    DATABASE_URL_SYNC: str = "postgresql://support_admin:support_secure_password@localhost:5432/ecommerce_support"
    GEMINI_API_KEY: str = "test-api-key"
    GEMINI_MODEL: str = "gemini-3-flash-preview"
    HF_MODEL: str = "Qwen/Qwen3.8-27B"
    HF_TOKEN: str = "test-api-key"
    EMBEDDING_MODEL: str = "models/gemini-embedding-001"
    EMBEDDING_DIMENSION: int = 768
    SECRET_KEY: str = "insecure-default-key-for-dev-only"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
