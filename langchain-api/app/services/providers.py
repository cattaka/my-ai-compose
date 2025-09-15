from __future__ import annotations
import json
import httpx
from typing import AsyncGenerator, List, Dict, Any

from langchain_ollama import ChatOllama
from app.core.config import settings
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

# 判定ユーティリティ
def resolve_provider(model: str | None, explicit: str | None) -> tuple[str, str]:
    """
    戻り: (provider, pure_model_name)
    model プレフィックス "openai:" / "ollama:" を剥がす。
    """
    if explicit:
        if model and ":" in model:
            model = model.split(":", 1)[1]
        return explicit, (model or "")
    if model and ":" in model:
        p, m = model.split(":", 1)
        if p in ("openai", "ollama"):
            return p, m
    # デフォルト
    if model is None:
        model = settings.DEFAULT_MODEL.split(":", 1)[-1]
    default_provider = settings.DEFAULT_PROVIDER
    # DEFAULT_MODEL にプレフィックスが付いていたら上書き
    if ":" in settings.DEFAULT_MODEL:
        default_provider = settings.DEFAULT_MODEL.split(":", 1)[0]
    return default_provider, model

# OpenAI 呼び出し（非ストリーム）
async def openai_complete(model: str, messages: List[ChatCompletionMessageParam], output_structure: type = None, temperature: float | None = None):
    client = OpenAI(
        api_key=settings.OPENAI_API_KEY
    )

    if output_structure:
        response = client.chat.completions.parse(
            model=model,
            messages=messages,
            temperature=1, # The error sayed Only the default (1) value is supported.
            response_format=output_structure
        )
    else:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=1, # The error sayed Only the default (1) value is supported.
            stream=False
        )
    return response

# OpenAI ストリーミング (SSE 風)
async def openai_stream(model: str, messages: List[ChatCompletionMessageParam], temperature: float | None) -> AsyncGenerator[Dict[str, Any], None]:
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    async with httpx.AsyncClient(base_url=settings.OPENAI_BASE_URL, timeout=None) as client:
        async with client.stream("POST", "/chat/completions", json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                yield json.loads(data)

# Ollama 直接 (非ストリーム)
async def ollama_complete(model: str, messages_lc, output_structure: type = None, temperature: float | None = None):
    llm = get_llm(model=model, output_structure=output_structure, temperature=temperature)
    out = await llm.ainvoke(messages_lc)
    return out

# Ollama ストリーム
async def ollama_stream(model: str, messages_lc, output_structure: type = None, temperature: float | None = None):
    llm = get_llm(model=model, output_structure=output_structure, temperature=temperature)
    async for chunk in llm.astream(messages_lc):
        yield chunk

def get_llm(model: str | None = None, output_structure: type = None, **overrides):
    llm = ChatOllama(
        model=model or settings.DEFAULT_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        **overrides
    )
    if output_structure:
        llm = llm.with_structured_output(output_structure)
    return llm
