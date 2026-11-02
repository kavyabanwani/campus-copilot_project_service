import os
import sys
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PLACEHOLDER_KEYS = {
    "change-this-to-a-long-random-string-later",
    "replace-with-your-own-random-string",
    "replace-with-your-secret-key",
    "",
}


class Settings(BaseSettings):
    # Secret key used to sign JWT tokens
    SECRET_KEY: str = "change-this-to-a-long-random-string-later"

    # JWT settings
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720

    # Database
    DATABASE_URL: str = "sqlite:///./campus_copilot.db"

    # Groq API settings
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    # Local embeddings and vector store
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    VECTOR_STORE_PATH: str = "./vector_store"

    # Optional campus events API
    CAMPUS_EVENTS_API_URL: str = ""
    CAMPUS_EVENTS_API_KEY: str = ""

    # Allowed frontend origins
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5183,http://127.0.0.1:5183,"
        "https://campus-copilot-frontend-groq.vercel.app,"
        "https://campus-copilot.vercel.app"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    def validate_security(self) -> None:
        """Reject default placeholder secrets."""
        if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
            return

        if self.SECRET_KEY.strip() in DEFAULT_PLACEHOLDER_KEYS:
            raise RuntimeError(
                "Insecure configuration: SECRET_KEY cannot be "
                "left as the default placeholder. Set a secure "
                "random string in your .env file."
            )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
settings.validate_security()