from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str  # postgresql+asyncpg://...
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # Redis / Task Queue
    REDIS_URL: str = "redis://localhost:6379"

    # OpenAI
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-4.1-mini"

    # Soniox
    SONIOX_API_KEY: str

    # PDFMonkey
    PDFMONKEY_API_KEY: str
    PDFMONKEY_TEMPLATE_ID: str

    # WhatsApp Bridge
    BRIDGE_URL: str = "https://constructor-production.up.railway.app"
    WEBHOOK_SECRET: str  # Shared secret between Bridge and Agent

    # Admin API
    ADMIN_API_KEY: str  # Bearer token for /admin/* endpoints

    # Rate Limiting
    RATE_LIMIT_MAX_MESSAGES: int = 20
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # Caching
    SITE_CACHE_TTL_SECONDS: int = 300  # 5 min

    # Google Sheets (optional export layer)
    GOOGLE_SHEETS_CREDENTIALS_JSON: str = ""
    CENTRAL_REGISTRY_SHEET_ID: str = "1qNca0mVtydjhGTEv6H21BxXC8-ElzSCBuu2APZSMqhw"

    # Agent
    AGENT_MAX_ITERATIONS: int = 3
    STT_TIMEOUT_SECONDS: int = 60

    # Observability
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_PROJECT: str = "bob-agent-prod"
    SENTRY_DSN: str = ""
    LOG_LEVEL: str = "INFO"

    # Security
    MAX_REQUEST_BODY_BYTES: int = 1_048_576  # 1 MB
    MAX_DESCRIPTION_LENGTH: int = 500

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
