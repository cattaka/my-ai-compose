from __future__ import annotations
import os

class Settings:
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "llama3.1")
    ALLOW_ORIGINS: str = os.getenv("ALLOW_ORIGINS", "*")

settings = Settings()