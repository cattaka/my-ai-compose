from __future__ import annotations
from langchain_ollama.chat_models import ChatOllama
from app.core.config import settings
from typing import List
from langgraph.config import get_stream_writer
from langchain_core.messages import BaseMessage
from app.services.providers import (
    openai_complete,
    openai_stream,
    ollama_complete,
    ollama_stream,
)

async def call_llm(provider: str, model: str, messages_lc: List[BaseMessage], temperature: float | None, stream: bool) -> str:
    answer = ""
    if provider == "openai":
        if stream:
            answer = await _call_openai_async(model=model, messages_lc=messages_lc, output_structure=None, temperature=temperature)
        else:
            out = await _call_openai_sync(model=model, messages_lc=messages_lc, output_structure=None, temperature=temperature)
            answer = getattr(out, "content", "")
    elif provider == "ollama":
        if stream:
            answer = await _call_ollama_async(model=model, messages_lc=messages_lc, output_structure=None, temperature=temperature)
        else:
            out = await _call_ollama_sync(model=model, messages_lc=messages_lc, output_structure=None, temperature=temperature)
            answer = getattr(out, "content", "")
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    return answer

# output_type を指定した場合はstreamはFalse固定
async def call_llm_with_output_type(provider: str, model: str, messages_lc: List[BaseMessage], output_structure: type, temperature: float | None):
    if provider == "openai":
        answer = await _call_openai_sync(model=model, messages_lc=messages_lc, output_structure=output_structure, temperature=temperature)
    elif provider == "ollama":
        answer = await _call_ollama_sync(model=model, messages_lc=messages_lc, output_structure=output_structure, temperature=temperature)
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    return answer

async def _call_openai_sync(model: str, messages_lc: List[BaseMessage], output_structure: type = None, temperature: float | None = None) -> str:
    # TODO: output_structure 未対応
    data = await openai_complete(
        model=model,
        messages=messages_lc,
        temperature=temperature,
    )
    answer = ""
    try:
        ch = data.get("choices", [])
        if ch:
            answer = ch[0]["message"]["content"]
    except Exception:
        answer = ""
    return {"content": answer}

async def _call_openai_async(model: str, messages_lc: List[BaseMessage], output_structure: type = None, temperature: float | None = None) -> str:
    # TODO: output_structure 未対応
    writer = get_stream_writer()
    partial = ""
    async for ev in openai_stream(
        model=model,
        messages=messages_lc,
        temperature=temperature,
    ):
        choices = ev.get("choices", [])
        if not choices:
            continue
        delta = choices[0].get("delta", {}).get("content")
        if not delta:
            continue
        partial += delta
        # event_name 追加
        writer({
            "event_name": "token",
            "provider": "openai",
            "model": model,
            "delta": delta,
            "partial": partial,
        })
    return partial

async def _call_ollama_sync(model: str, messages_lc: List[BaseMessage], output_structure: type = None, temperature: float | None = None) -> str:
    out = await ollama_complete(
        model=model,
        messages_lc=messages_lc,
        output_structure=output_structure,
        temperature=temperature,
    )
    return out

async def _call_ollama_async(model: str, messages_lc: List[BaseMessage], output_structure: type = None, temperature: float | None = None) -> str:
    writer = get_stream_writer()
    partial = ""
    async for chunk in ollama_stream(
        model=model,
        messages_lc=messages_lc,
        output_structure=output_structure,
        temperature=temperature,
    ):
        delta = getattr(chunk, "content", "")
        if not delta:
            continue
        partial += delta
        writer({
            "event_name": "token",
            "provider": "ollama",
            "model": model,
            "delta": delta,
            "partial": partial,
        })
    return partial
