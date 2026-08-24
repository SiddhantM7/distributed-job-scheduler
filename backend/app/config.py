from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://jobscheduler:jobscheduler@postgres:5432/jobscheduler"

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Worker
    WORKER_HEARTBEAT_TIMEOUT_SECONDS: int = 60
    WORKER_HEARTBEAT_INTERVAL_SECONDS: int = 10
    WORKER_POLL_INTERVAL_SECONDS: float = 1.0

    # Scheduler
    SCHEDULER_INTERVAL_SECONDS: float = 1.0

    # LLM (NVIDIA NIM / OpenAI-compatible API)
    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    LLM_MODEL: str = "deepseek-ai/deepseek-v4-flash-0731"
    LLM_PROVIDER: str = "nvidia"

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}


settings = Settings()
