"""Application settings, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LLMProviderName = Literal["offline", "anthropic", "openai", "gemini", "ollama"]
STTBackendName = Literal["sidecar", "faster_whisper", "openai_whisper"]
DiarizerBackendName = Literal["spectral", "pyannote"]
EmbeddingBackendName = Literal["hashing", "openai"]
StorageBackendName = Literal["local", "s3"]
DEV_JWT_SECRET = "dev-insecure-change-me-please-32-bytes-minimum"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- app ---
    app_name: str = "MeetMind"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = True
    api_prefix: str = "/api/v1"
    frontend_url: str = "http://localhost:20700"
    public_api_url: str = "http://localhost:20701"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:20700"]
    )

    # --- security ---
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    media_token_ttl_minutes: int = 120
    refresh_cookie_name: str = "mm_refresh"
    refresh_cookie_secure: bool = False
    # "none" is needed when the SPA and the API live on different sites (requires Secure).
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # --- rate limiting ---
    rate_limit_enabled: bool = True
    rate_limit_default_per_minute: int = 240
    rate_limit_auth_per_minute: int = 20
    rate_limit_upload_per_minute: int = 20
    trust_proxy_headers: bool = False  # honour X-Forwarded-For only behind a trusted reverse proxy

    # --- database / queue ---
    database_url: str = "sqlite+pysqlite:///./meetmind.db"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    redis_url: str | None = None
    task_always_eager: bool = False

    # --- storage ---
    storage_backend: StorageBackendName = "local"
    local_storage_path: str = "./data/storage"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "meetmind-audio"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"
    max_upload_mb: int = 500

    # --- audio / speech ---
    ffmpeg_binary: str = "ffmpeg"
    target_sample_rate: int = 16000
    stt_backend: STTBackendName = "sidecar"
    diarizer_backend: DiarizerBackendName = "spectral"
    whisper_model_size: str = "base"
    whisper_device: str = "auto"
    whisper_compute_type: str = "int8"
    hf_token: str | None = None
    max_speakers: int = 6
    diarizer_threshold: float = 2.2

    # --- LLM ---
    llm_provider: LLMProviderName = "offline"
    llm_model: str | None = None
    llm_max_tokens: int = 16000
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    llm_timeout_s: float = 120.0
    llm_fallback_offline: bool = True  # degrade to the offline engine if the LLM provider fails
    long_meeting_threshold_s: float = 3600.0
    map_chunk_s: float = 600.0

    # --- embeddings / RAG ---
    embedding_backend: EmbeddingBackendName = "hashing"
    embedding_dim: int = 384
    openai_embedding_model: str = "text-embedding-3-small"
    rag_top_k: int = 6
    chunk_target_words: int = 60

    # --- integrations ---
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:20701/api/v1/auth/google/callback"
    google_auth_base: str = "https://accounts.google.com"
    google_token_url: str = "https://oauth2.googleapis.com/token"  # noqa: S105
    google_userinfo_url: str = "https://openidconnect.googleapis.com/v1/userinfo"
    google_calendar_base: str = "https://www.googleapis.com/calendar/v3"
    slack_allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["hooks.slack.com"]
    )

    # --- cost model (USD) ---
    cost_stt_per_minute: dict[str, float] = Field(
        default_factory=lambda: {
            "sidecar": 0.0,
            "faster_whisper": 0.0004,  # amortised self-hosted GPU estimate
            "openai_whisper": 0.006,
        }
    )
    reference_stt_per_minute: float = 0.006  # hosted Whisper API, used for projections
    reference_llm_input_per_mtok: float = 4.0  # claude-opus-5-5 list price
    reference_llm_output_per_mtok: float = 20.0
    llm_prices_per_mtok: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {
            "claude-opus-5-5": (4.0, 20.0),
            "claude-sonnet-5-5": (2.0, 10.0),
            "claude-haiku-5-5": (0.10, 0.50),
            "gpt-4o-mini": (0.15, 0.60),
            "gpt-4o": (2.5, 10.0),
            "gemini-2.0-flash": (0.10, 0.40),
        }
    )

    # --- pipeline robustness ---
    pipeline_stale_after_s: float = (
        3600.0  # a 'processing' meeting with no heartbeat for this long is reclaimable
    )
    share_link_default_days: int = 30

    # --- demo ---
    seed_demo: bool = False

    @field_validator("cors_origins", "slack_allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            if value.strip().startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_database_url(cls, value: object) -> object:
        """Hosted Postgres providers hand out ``postgres://``/``postgresql://`` URLs; use psycopg 3."""
        if isinstance(value, str):
            for prefix in ("postgres://", "postgresql://"):
                if value.startswith(prefix):
                    return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment == "production" and self.jwt_secret == DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET must be set in production")
        if len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        required = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
        }
        if self.llm_provider in required and not required[self.llm_provider]:
            raise ValueError(f"LLM_PROVIDER={self.llm_provider} requires its API key to be set")
        if self.storage_backend == "s3" and not (self.s3_access_key and self.s3_secret_key):
            raise ValueError("STORAGE_BACKEND=s3 requires S3_ACCESS_KEY and S3_SECRET_KEY")
        if self.refresh_cookie_samesite == "none" and not self.refresh_cookie_secure:
            raise ValueError("REFRESH_COOKIE_SAMESITE=none requires REFRESH_COOKIE_SECURE=true")
        if self.environment == "production" and "*" in self.cors_origins:
            raise ValueError("Wildcard CORS origins are not allowed in production")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
