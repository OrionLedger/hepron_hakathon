"""
Centralised configuration using Pydantic BaseSettings.
All configuration comes from environment variables or .env file.
Never hardcode values in service code — always import from here.
"""
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────
    DATABASE_URL: str

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_PASSWORD: str = ""

    # ── Kafka ─────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka1:9092,kafka2:9092,kafka3:9092"
    KAFKA_SCHEMA_REGISTRY_URL: str = "http://schema-registry:8081"

    # ── JWT ───────────────────────────────────────────────────
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_HOURS: int = 8

    # ── Service ───────────────────────────────────────────────
    SERVICE_NAME: str = "cds-service"
    LOG_LEVEL: str = "INFO"

    # ── Observability ─────────────────────────────────────────
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://jaeger:4317"

    # ── Email ─────────────────────────────────────────────────
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = True

    # ── MinIO ─────────────────────────────────────────────────
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin_secret"
    MINIO_SECURE: bool = False

    # ── Internal Service URLs ─────────────────────────────────
    IDENTITY_SERVICE_URL: str = "http://identity-service:8000"

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return v

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
