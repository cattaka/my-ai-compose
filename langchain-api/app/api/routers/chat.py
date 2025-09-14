from __future__ import annotations
import asyncio, json, os
from typing import List, Literal, Optional, Dict, Any
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from app.core.config import settings
from app.services.providers import resolve_provider  # ルータ外表示用 (model name 統一のため)
from app.graph.chat_graph import (
    run_chat_graph,
    stream_chat_graph,
)

router = APIRouter(prefix="/v1/chat", tags=["chat"])

Role = Literal["system", "user", "assistant", "tool", "function"]

class ChatMessage(BaseModel):
    role: Role
    content: str

class ChatRequest(BaseModel):
    model: Optional[str] = None
    provider: Optional[str] = None   # 明示切替 (任意)
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 1.0
    max_tokens: Optional[int] = None
    stream: Optional[bool] = True

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
    # 非ストリーミング: Graph が実際の OpenAI/Ollama 呼び出しまで担当
    if not req.stream:
        out = await run_chat_graph(req.model, [m.model_dump() for m in req.messages], req.temperature)
        model_used = f"{out['provider']}:{out['model']}"
        return JSONResponse(completion_obj(out.get("answer", ""), model_used))

    # ストリーミング: Graph で準備→ provider 毎の chunk を SSE
    async def gen():
        async for ev in stream_chat_graph(req.model, [m.model_dump() for m in req.messages], req.temperature):
            # ev は provider 毎の chunk 形式を簡易統一 (既存 OpenAI 互換を期待)
            if "choices" in ev:  # OpenAI / Ollama 風
                yield await sse_chunk(ev)
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")