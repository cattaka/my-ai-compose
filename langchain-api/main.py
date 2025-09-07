from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Literal

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from langchain_community.llms import Ollama
from langchain_ollama.chat_models import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "llama3.1")
ALLOW_ORIGINS = os.getenv("ALLOW_ORIGINS", "*")

llm = ChatOllama(model=DEFAULT_MODEL, base_url=OLLAMA_BASE_URL)

app = FastAPI(title="OpenAI-compatible LangChain Gateway (to Ollama)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOW_ORIGINS] if ALLOW_ORIGINS != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Role = Literal["system", "user", "assistant", "tool", "function"]

class ChatMessage(BaseModel):
    role: Role
    content: str

class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 1.0
    max_tokens: Optional[int] = None
    stream: Optional[bool] = True

class ChatChoiceDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None

class ChatChoiceMessage(BaseModel):
    role: str
    content: str

def to_lc_messages(msgs: List[ChatMessage]) -> List[BaseMessage]:
    out: List[BaseMessage] = []
    for m in msgs:
        if m.role == "system":
            out.append(SystemMessage(content=m.content))
        elif m.role == "user":
            out.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            out.append(AIMessage(content=m.content))
        else:
            out.append(HumanMessage(content=m.content))
    return out

async def sse_chunk(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

def completion_obj(content: str) -> Dict[str, Any]:
    return {
        "id": "chatcmpl-" + os.urandom(8).hex(),
        "object": "chat.completion",
        "created": int(asyncio.get_event_loop().time()),
        "model": DEFAULT_MODEL,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
    }

@app.get("/v1/models")
async def list_models():
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=10) as client:
            r = await client.get("/api/tags")
            r.raise_for_status()
            data = r.json()
        models = []
        for item in data.get("models", []):
            name = item.get("name", "")
            if name:
                models.append({"id": name, "object": "model", "created": 0, "owned_by": "ollama"})
        if not models:
            models = [{"id": DEFAULT_MODEL, "object": "model", "created": 0, "owned_by": "ollama"}]
        return {"object": "list", "data": models}
    except Exception:
        return {"object": "list", "data": [{"id": DEFAULT_MODEL, "object": "model", "created": 0, "owned_by": "ollama"}]}

@app.get("/v1/health")
async def health():
    return {"status": "ok"}

@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, request: Request):
    model = req.model or DEFAULT_MODEL
    local_llm = ChatOllama(model=model, base_url=OLLAMA_BASE_URL, temperature=req.temperature)
    lc_msgs = to_lc_messages(req.messages)

    if req.stream:
        async def gen():
            head = {"id": "chatcmpl-" + os.urandom(8).hex(), "object": "chat.completion.chunk",
                    "created": int(asyncio.get_event_loop().time()), "model": model,
                    "choices": [{"index": 0, "delta": {"role": "assistant"}}]}
            yield await sse_chunk(head)
            async for chunk in local_llm.astream(lc_msgs):
                delta_text = getattr(chunk, "content", None) or ""
                if delta_text:
                    payload = {
                        "id": head["id"],
                        "object": "chat.completion.chunk",
                        "created": head["created"],
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": delta_text},
                            "finish_reason": None
                        }]
                    }
                    yield await sse_chunk(payload)
                await asyncio.sleep(0)
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    out = await local_llm.ainvoke(lc_msgs)
    return JSONResponse(completion_obj(out.content))

@app.get("/api/tags")
async def relay_tags():
    async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL) as client:
        r = await client.get("/api/tags")
        return Response(content=r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))

@app.get("/api/version")
async def relay_version():
    async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL) as client:
        r = await client.get("/api/version")
        return Response(content=r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))

@app.get("/api/ps")
async def relay_ps():
    async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL) as client:
        r = await client.get("/api/ps")
        return Response(content=r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))

@app.post("/api/chat")
async def relay(request: Request):
    body = await request.body()
    headers = {"Content-Type": "application/json"}
    async def gen():
        async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=60) as client:
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
                             headers={"Cache-Control": "no-cache","Connection": "keep-alive","X-Accel-Buffering": "no"})
