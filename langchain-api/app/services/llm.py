from __future__ import annotations
from langchain_ollama.chat_models import ChatOllama
from app.core.config import settings

def get_llm(model: str | None = None, **overrides):
    return ChatOllama(
        model=model or settings.DEFAULT_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        **overrides
    )