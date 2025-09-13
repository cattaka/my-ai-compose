from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routers import (
    chat_router,
    relay_router,
    health_router,
    models_router,
)

app = FastAPI(title="OpenAI-compatible LangChain Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.ALLOW_ORIGINS] if settings.ALLOW_ORIGINS != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health_router)
app.include_router(models_router)
app.include_router(chat_router)
app.include_router(relay_router)
