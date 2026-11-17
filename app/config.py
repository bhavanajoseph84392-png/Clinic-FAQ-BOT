import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


class Settings(BaseModel):
    DATABASE_URL: str = _require_env("DATABASE_URL")
    MIGRATION_DATABASE_URL: str = _require_env("MIGRATION_DATABASE_URL")
    SECRET_KEY: str = _require_env("SECRET_KEY")
    
    # AI Configuration (Gemini)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    ANSWER_MODEL: str = os.getenv("ANSWER_MODEL", "gemini-2.5-flash")
    CHECK_MODEL: str = os.getenv("CHECK_MODEL", "gemini-2.5-flash")
    EMBED_MODEL: str = os.getenv("EMBED_MODEL", "text-embedding-004")
    
    # Email Configuration
    EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "resend")
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    MAIL_FROM: str = os.getenv("MAIL_FROM", "onboarding@resend.dev")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    
    # Thresholds & Limits
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")
    LESSON_THRESHOLD: float = float(os.getenv("LESSON_THRESHOLD", "0.85"))
    KNOWLEDGE_THRESHOLD: float = float(os.getenv("KNOWLEDGE_THRESHOLD", "0.55"))
    DAILY_AI_BUDGET_PER_CLINIC: int = int(os.getenv("DAILY_AI_BUDGET_PER_CLINIC", "500"))

settings = Settings()
