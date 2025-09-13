from __future__ import annotations
import httpx
from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(tags=["models"])

@router.get("/v1/models")
async def list_models():
    try:
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=10) as client:
            r = await client.get("/api/tags")
            r.raise_for_status()
            data = r.json()
        models = []
        for item in data.get("models", []):
            name = item.get("name", "")
            if name:
                models.append({"id": name, "object": "model", "created": 0, "owned_by": "ollama"})
        if not models:
            models = [{"id": settings.DEFAULT_MODEL, "object": "model", "created": 0, "owned_by": "ollama"}]
        return {"object": "list", "data": models}
    except Exception:
        return {"object": "list", "data": [{"id": settings.DEFAULT_MODEL, "object": "model", "created": 0, "owned_by": "ollama"}]}