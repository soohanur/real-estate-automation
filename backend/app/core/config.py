"""
Backend Configuration
Centralized settings management with environment variables and smart URL detection
"""
from typing import Optional, List
from pydantic_settings import BaseSettings
from pydantic import PostgresDsn, validator
from pathlib import Path
from .environment import EnvironmentConfig


class Settings(BaseSettings):
    """Application settings with environment variable support and smart URL detection."""
    
    # Application
    APP_NAME: str = "Automation Platform API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"  # development, staging, production
    
    # Domain Configuration (for production)
    DOMAIN_NAME: Optional[str] = None  # e.g., "your-domain.com" or VPS IP
    USE_HTTPS: bool = False  # Set to True in production with SSL
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 2
    
    # Security
    SECRET_KEY: str = "CHANGE_THIS_IN_PRODUCTION_USE_openssl_rand_hex_32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ADMIN_SECRET_KEY: str = "admin123"  # Change this in production!
    
    # CORS - Can be set explicitly or auto-generated
    BACKEND_CORS_ORIGINS: Optional[str] = None
    
    @validator("BACKEND_CORS_ORIGINS", pre=True, always=True)
    def assemble_cors_origins(cls, v, values):
        if v and isinstance(v, str) and v.strip():
            # Use explicitly provided CORS origins
            return v
        elif isinstance(v, list):
            return ",".join(v)
        else:
            # Auto-generate based on environment
            origins = EnvironmentConfig.get_cors_origins()
            return ",".join(origins)
    
    @property
    def cors_origins(self) -> List[str]:
        """Get CORS origins as a list"""
        if not self.BACKEND_CORS_ORIGINS:
            return EnvironmentConfig.get_cors_origins()
        return [i.strip() for i in self.BACKEND_CORS_ORIGINS.split(",") if i.strip()]
    
    @property
    def backend_url(self) -> str:
        """Get full backend URL"""
        return EnvironmentConfig.get_backend_url()
    
    @property
    def frontend_url(self) -> str:
        """Get frontend URL"""
        return EnvironmentConfig.get_frontend_url()
    
    @property
    def websocket_url(self) -> str:
        """Get WebSocket URL"""
        return EnvironmentConfig.get_websocket_url()
    
    @property
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.ENVIRONMENT.lower() in ["production", "prod"] or not self.DEBUG
    
    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "automation_user"
    POSTGRES_PASSWORD: str = "automation_password"
    POSTGRES_DB: str = "automation_db"
    DATABASE_URL: Optional[str] = None
    
    @validator("DATABASE_URL", pre=True)
    def assemble_db_connection(cls, v, values):
        if isinstance(v, str):
            return v
        return f"postgresql+asyncpg://{values.get('POSTGRES_USER')}:{values.get('POSTGRES_PASSWORD')}@{values.get('POSTGRES_SERVER')}/{values.get('POSTGRES_DB')}"
    
    # Redis (Job Queue & Cache)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_URL: Optional[str] = None

    # Gmail OAuth (web flow). Used by /api/v1/auth/google/* to obtain
    # a refresh token for the shared sender mailbox, then by the
    # gmail_sender service to send queued email_messages via Gmail API.
    GOOGLE_OAUTH_CLIENT_ID: Optional[str] = None
    GOOGLE_OAUTH_CLIENT_SECRET: Optional[str] = None
    GOOGLE_OAUTH_REDIRECT_URI: Optional[str] = None
    GMAIL_SENDER: Optional[str] = None

    # Partner API (server-to-server). The SHA-256 hex hash of the secret key
    # given to the external partner (e.g. sons-bidding). The raw key is never
    # stored — only this hash. Mint with scripts/mint_partner_key.py.
    PARTNER_API_KEY_HASH: Optional[str] = None

    @validator("REDIS_URL", pre=True)
    def assemble_redis_connection(cls, v, values):
        if isinstance(v, str):
            return v
        password_part = f":{values.get('REDIS_PASSWORD')}@" if values.get('REDIS_PASSWORD') else ""
        return f"redis://{password_part}{values.get('REDIS_HOST')}:{values.get('REDIS_PORT')}/{values.get('REDIS_DB')}"
    
    # Celery
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None
    
    @validator("CELERY_BROKER_URL", pre=True)
    def set_celery_broker(cls, v, values):
        return v or values.get("REDIS_URL")
    
    @validator("CELERY_RESULT_BACKEND", pre=True)
    def set_celery_backend(cls, v, values):
        return v or values.get("REDIS_URL")
    
    # File Storage
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent  # Project root
    
    LOG_DIR: Path = BASE_DIR / "logs"  # Application logs
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024  # 100MB
    
    # Automation Settings
    MAX_CONCURRENT_JOBS: int = 3  # Limit concurrent Chrome instances (memory optimization)
    # Kept for any code path that still reads this value, but Celery no
    # longer enforces a wall-clock kill (see celery_app.py). Setting to 0
    # would break consumers that expect a positive int — large sentinel.
    JOB_TIMEOUT: int = 3600 * 24 * 365  # 1 year — effectively unlimited
    RETRY_MAX_ATTEMPTS: int = 3
    RETRY_DELAY: int = 60  # seconds
    
    # Chrome Settings - SHARED Profiles (Memory Optimized)
    # All tools share chrome_profiles/ at root to save 300-400MB per tool
    CHROME_PROFILES_DIR: Path = BASE_DIR / "chrome_profiles"  # Shared across all tools
    CHROME_PROFILE_PATH: str = str(BASE_DIR / "chrome_profiles" / "default")
    CHROME_PROFILE_NAME: str = "Default"
    HEADLESS_MODE: bool = False  # Set to False to see browser (for debugging)
    MAX_WORKERS: int = 3  # Per job; total limited by MAX_CONCURRENT_JOBS
    
    # Monitoring
    SENTRY_DSN: Optional[str] = None
    ENABLE_METRICS: bool = True
    
    # Email Notifications (optional)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    NOTIFICATION_EMAIL: Optional[str] = None
    
    class Config:
        case_sensitive = True
        extra = "ignore"
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()

# Create required directories
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
settings.CHROME_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
