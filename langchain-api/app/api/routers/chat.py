from __future__ import annotations
import asyncio, json, os
from typing import List, Literal, Optional, Dict, Any
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from app.core.config import settings
from app.services.providers import (
    resolve_provider,
    openai_complete,
    openai_stream,
    ollama_complete,
    ollama_stream,
)
from app.services.llm import get_llm  # 既存（グラフ/非ストリーム Ollama 用）

router = APIRouter(prefix="/v1/chat", tags=["chat"])

Role = Literal["system", "user", "assistant", "tool", "function"]

class ChatMessage(BaseModel):
    role: Role
    content: str

class ChatRequest(BaseModel):
    model: Optional[str] = None
    provider: Optional[str] = None  # "openai" | "ollama" 明示切替
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 1.0
    max_tokens: Optional[int] = None
    stream: Optional[bool] = True

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

def completion_obj(content: str, model: str) -> Dict[str, Any]:
    return {
        "id": "chatcmpl-" + os.urandom(8).hex(),
        "object": "chat.completion",
        "created": int(asyncio.get_event_loop().time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
    }

async def sse_chunk(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

@router.post("/completions")
async def chat_completions(req: ChatRequest, request: Request):
    provider, pure_model = resolve_provider(req.model, req.provider)

    # 非ストリーミング: LangGraph (現状 Ollama のみ) + Provider 分岐
    if not req.stream:
        if provider == "openai":
            if not settings.OPENAI_API_KEY:
                raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set")
            # OpenAI 直
            openai_msgs = [m.model_dump() for m in req.messages]
            data = await openai_complete(model=pure_model, messages=openai_msgs, temperature=req.temperature)
            return JSONResponse(data)
        else:
            # LangGraph (単純チャット) → Ollama
            from app.graph.chat_graph import run_simple_chat
            raw_messages = [m.model_dump() for m in req.messages]
            answer = run_simple_chat(model=pure_model, messages=raw_messages)
            return JSONResponse(completion_obj(answer, pure_model))

    # ストリーミング
    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set")
        openai_msgs = [m.model_dump() for m in req.messages]

        async def gen_openai():
            async for ev in openai_stream(pure_model, openai_msgs, req.temperature):
                yield await sse_chunk(ev)
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen_openai(), media_type="text/event-stream")

    # Ollama ストリーミング (既存)
    lc_msgs = to_lc_messages(req.messages)
    async def gen_ollama():
        head = {"id": "chatcmpl-" + os.urandom(8).hex(), "object": "chat.completion.chunk",
                "created": int(asyncio.get_event_loop().time()), "model": pure_model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}}]}
        yield await sse_chunk(head)
        async for chunk in ollama_stream(pure_model, lc_msgs, req.temperature):
            delta_text = getattr(chunk, "content", "") or ""
            if delta_text:
                payload = {
                    "id": head["id"],
                    "object": "chat.completion.chunk",
                    "created": head["created"],
                    "model": pure_model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": delta_text},
                        "finish_reason": None
                    }]
                }
                yield await sse_chunk(payload)
            await asyncio.sleep(0)
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen_ollama(), media_type="text/event-stream")