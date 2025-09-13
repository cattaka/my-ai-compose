from __future__ import annotations
import httpx, asyncio, json
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from app.core.config import settings

router = APIRouter(prefix="/api", tags=["relay"])

@router.get("/tags")
async def relay_tags():
    async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL) as client:
        r = await client.get("/api/tags")
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))

@router.get("/version")
async def relay_version():
    async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL) as client:
        r = await client.get("/api/version")
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))

@router.get("/ps")
async def relay_ps():
    async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL) as client:
        r = await client.get("/api/ps")
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))

@router.post("/chat")
async def relay_chat(request: Request):
    body = await request.body()
    headers = {"Content-Type": "application/json"}

    async def gen():
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=60) as client:
            async with client.stream("POST", "/api/chat", content=body, headers=headers) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    yield f"data: {json.dumps({'error': text.decode('utf-8','ignore')})}\n\n"
                    return
                try:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
                        await asyncio.sleep(0)
                except (httpx.ReadError, httpx.StreamClosed):
                    return
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})