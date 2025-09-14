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

async def call_llm(provider: str, model: str, messages_lc: List[BaseMessage], temperature: float | None, stream: bool):
    if provider == "openai":
        return await _call_openai(model=model, messages_lc=messages_lc, temperature=temperature, stream=stream)
    elif provider == "ollama":
        return await _call_ollama(model=model, messages_lc=messages_lc, temperature=temperature, stream=stream)
    else:
        raise ValueError(f"Unsupported provider: {provider}")

async def _call_openai(model: str, messages_lc: List[BaseMessage], temperature: float | None, stream: bool):
    answer = ""
    if stream:
        answer = await _call_openai_async(model=model, messages_lc=messages_lc, temperature=temperature)
    else:
        answer = await _call_openai_sync(model=model, messages_lc=messages_lc, temperature=temperature)
    return answer

async def _call_openai_sync(model: str, messages_lc: List[BaseMessage], temperature: float | None) -> str:
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
    return answer

async def _call_openai_async(model: str, messages_lc: List[BaseMessage], temperature: float | None) -> str:
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

async def _call_ollama(model: str, messages_lc: List[BaseMessage], temperature: float | None, stream: bool) -> str:
    answer = ""
    if stream:
        answer = await _call_ollama_async(model=model, messages_lc=messages_lc, temperature=temperature)
    else:
        answer = await _call_ollama_sync(model=model, messages_lc=messages_lc, temperature=temperature)
    return answer

async def _call_ollama_sync(model: str, messages_lc: List[BaseMessage], temperature: float | None) -> str:
    out = await ollama_complete(
        model=model,
        messages_lc=messages_lc,
        temperature=temperature,
    )
    return getattr(out, "content", "")

async def _call_ollama_async(model: str, messages_lc: List[BaseMessage], temperature: float | None) -> str:
    writer = get_stream_writer()
    partial = ""
    async for chunk in ollama_stream(
        model=model,
        messages_lc=messages_lc,
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
