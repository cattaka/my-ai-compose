from __future__ import annotations
import asyncio, json, os
from typing import List, Literal, Optional, Dict, Any
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from app.services.llm import get_llm
from app.core.config import settings

router = APIRouter(prefix="/v1/chat", tags=["chat"])

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
    model = req.model or settings.DEFAULT_MODEL
    llm = get_llm(model=model, temperature=req.temperature)
    lc_msgs = to_lc_messages(req.messages)

    if req.stream:
        async def gen():
            head = {"id": "chatcmpl-" + os.urandom(8).hex(), "object": "chat.completion.chunk",
                    "created": int(asyncio.get_event_loop().time()), "model": model,
                    "choices": [{"index": 0, "delta": {"role": "assistant"}}]}
            yield await sse_chunk(head)
            async for chunk in llm.astream(lc_msgs):
                delta_text = getattr(chunk, "content", "") or ""
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
    out = await llm.ainvoke(lc_msgs)
    return JSONResponse(completion_obj(out.content, model))