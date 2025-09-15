from __future__ import annotations
import json
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
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionDeveloperMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionAssistantMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionFunctionMessageParam
)

async def call_llm(provider: str, model: str, messages_lc: List[BaseMessage], temperature: float | None, stream: bool) -> str:
    answer = ""
    if provider == "openai":
        converted_messages = convert_messages_to_chat_completion_param(messages_lc)
        if stream:
            answer = await _call_openai_async(model=model, messages_lc=converted_messages, temperature=temperature)
        else:
            answer = await _call_openai_sync(model=model, messages_lc=converted_messages, output_structure=None, temperature=temperature)
    elif provider == "ollama":
        if stream:
            answer = await _call_ollama_async(model=model, messages_lc=messages_lc, temperature=temperature)
        else:
            out = await _call_ollama_sync(model=model, messages_lc=messages_lc, output_structure=None, temperature=temperature)
            answer = getattr(out, "content", "")
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    return answer

# output_type を指定した場合はstreamはFalse固定
async def call_llm_with_output_type(provider: str, model: str, messages_lc: List[BaseMessage], output_structure: type, temperature: float | None):
    if provider == "openai":
        converted_messages = convert_messages_to_chat_completion_param(messages_lc)
        answer = await _call_openai_sync(model=model, messages_lc=converted_messages, output_structure=output_structure, temperature=temperature)
    elif provider == "ollama":
        answer = await _call_ollama_sync(model=model, messages_lc=messages_lc, output_structure=output_structure, temperature=temperature)
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    return answer

async def _call_openai_sync(model: str, messages_lc: List[ChatCompletionMessageParam], output_structure: type = None, temperature: float | None = None) -> str:
    data = await openai_complete(
        model=model,
        messages=messages_lc,
        output_structure=output_structure,
        temperature=temperature,
    )
    answer = ""
    try:
        answer = data.choices[0].message.content
        if output_structure:
            answer = output_structure.model_validate_json(answer)
        else:
            answer = {"content": answer}
    except Exception:
        answer = ""
    return answer

async def _call_openai_async(model: str, messages_lc: List[ChatCompletionMessageParam], temperature: float | None = None) -> str:
    writer = get_stream_writer()
    full = ""
    res = await openai_stream(model=model, messages=messages_lc, temperature=temperature)
    async for chunk in res:
        delta = chunk.choices[0].delta.content
        # full += delta
        writer({
            "event_name": "token",
            "provider": "openai",
            "model": model,
            "delta": delta,
            "partial": full,
        })
    return full

async def _call_ollama_sync(model: str, messages_lc: List[BaseMessage], output_structure: type = None, temperature: float | None = None):
    out = await ollama_complete(
        model=model,
        messages_lc=messages_lc,
        output_structure=output_structure,
        temperature=temperature,
    )
    return out

async def _call_ollama_async(model: str, messages_lc: List[BaseMessage], temperature: float | None = None) -> str:
    writer = get_stream_writer()
    partial = ""
    async for chunk in ollama_stream(
        model=model,
        messages_lc=messages_lc,
        output_structure=None,
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

def convert_messages_to_chat_completion_param(src: List[BaseMessage]) -> List[ChatCompletionMessageParam]:
    ret: List[ChatCompletionMessageParam] = []
    # ChatCompletionDeveloperMessageParam,
    # ChatCompletionSystemMessageParam,
    # ChatCompletionUserMessageParam,
    # ChatCompletionAssistantMessageParam,
    # ChatCompletionToolMessageParam,
    # ChatCompletionFunctionMessageParam,

    for msg in src:
        role = msg.type
        if role == "system":
            ret.append(ChatCompletionSystemMessageParam(role="system", content=msg.content))
        elif role == "human":
            ret.append(ChatCompletionUserMessageParam(role="user", content=msg.content))
        elif role == "ai":
            ret.append(ChatCompletionAssistantMessageParam(role="assistant", content=msg.content))
        elif role == "tool":
            ret.append(ChatCompletionToolMessageParam(role="tool", content=msg.content))
        elif role == "function":
            ret.append(ChatCompletionFunctionMessageParam(role="function", content=msg.content))
        else:
            ret.append(ChatCompletionUserMessageParam(role="user", content=msg.content))
    return ret
