from __future__ import annotations
from typing import TypedDict, List, Dict, Any, Literal
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from app.services.providers import (
    resolve_provider,
    openai_complete,
    openai_stream,
    ollama_complete,
    ollama_stream,
)

class ChatState(TypedDict, total=False):
    model: str
    provider: str
    raw_messages: List[Dict[str, str]]
    lc_messages: List[BaseMessage]
    temperature: float
    stream: bool
    answer: str
    partial_answer: str
    error: str

def _to_lc_messages(raw: List[Dict[str, str]]) -> List[BaseMessage]:
    out: List[BaseMessage] = []
    for m in raw:
        r = m.get("role")
        c = m.get("content", "")
        if r == "system":
            out.append(SystemMessage(content=c))
        elif r == "user":
            out.append(HumanMessage(content=c))
        elif r == "assistant":
            out.append(AIMessage(content=c))
        else:
            out.append(HumanMessage(content=c))
    return out

def prepare_node(state: ChatState) -> ChatState:
    provider, pure = resolve_provider(state.get("model"), state.get("provider"))
    state["provider"] = provider
    state["model"] = pure
    state.setdefault("partial_answer", "")
    if provider == "ollama":
        state["lc_messages"] = _to_lc_messages(state["raw_messages"])
    return state

def route_provider(state: ChatState) -> Literal[
    "openai_call_node",
    "ollama_call_node",
    "openai_stream_node",
    "ollama_stream_node"
]:
    if state.get("stream"):
        return "openai_stream_node" if state["provider"] == "openai" else "ollama_stream_node"
    return "openai_call_node" if state["provider"] == "openai" else "ollama_call_node"

# ---- サブグラフ構築ヘルパ ----
from langgraph.graph import StateGraph as _StateGraph

def build_provider_subgraph(stream: bool):
    """
    stream=True なら *stream_node を、False なら *call_node を内部に持つサブグラフを返す。
    親グラフに add_node すると 1 ノードとして扱える。
    """
    sg = _StateGraph(ChatState)

    # 内部ノード定義を再利用 (既存関数 openai_call_node 等をそのまま使う)
    if stream:
        sg.add_node("openai_stream_node", openai_stream_node)
        sg.add_node("ollama_stream_node", ollama_stream_node)
    else:
        sg.add_node("openai_call_node", openai_call_node)
        sg.add_node("ollama_call_node", ollama_call_node)

    def _route(state: ChatState):
        if state["provider"] == "openai":
            return "openai_stream_node" if stream else "openai_call_node"
        return "ollama_stream_node" if stream else "ollama_call_node"

    sg.set_entry_point("router_entry")
    # ルータ用ダミーノード
    def router_entry(state: ChatState) -> ChatState:
        return state
    sg.add_node("router_entry", router_entry)

    if stream:
        sg.add_conditional_edges(
            "router_entry",
            _route,
            {
                "openai_stream_node": "openai_stream_node",
                "ollama_stream_node": "ollama_stream_node",
            },
        )
        sg.add_edge("openai_stream_node", "__end__")
        sg.add_edge("ollama_stream_node", "__end__")
    else:
        sg.add_conditional_edges(
            "router_entry",
            _route,
            {
                "openai_call_node": "openai_call_node",
                "ollama_call_node": "ollama_call_node",
            },
        )
        sg.add_edge("openai_call_node", "__end__")
        sg.add_edge("ollama_call_node", "__end__")

    return sg.compile()

# ---- 親グラフ ----
_graph = None
def get_chat_graph():
    global _graph
    if _graph:
        return _graph
    g = StateGraph(ChatState)
    g.add_node("prepare_node", prepare_node)

    # サブグラフを 2 種類（call / stream）として親に登録
    g.add_node("provider_exec_call", build_provider_subgraph(stream=False))
    g.add_node("provider_exec_stream", build_provider_subgraph(stream=True))
    g.add_node("finalize_node", finalize_node)

    g.set_entry_point("prepare_node")

    def route_stream(state: ChatState):
        return "provider_exec_stream" if state.get("stream") else "provider_exec_call"

    g.add_conditional_edges(
        "prepare_node",
        route_stream,
        {
            "provider_exec_call": "provider_exec_call",
            "provider_exec_stream": "provider_exec_stream",
        },
    )
    g.add_edge("provider_exec_call", "finalize_node")
    g.add_edge("provider_exec_stream", "finalize_node")
    g.add_edge("finalize_node", "__end__")
    _graph = g.compile()
    return _graph

# ---- 非ストリーミング ----
async def openai_call_node(state: ChatState) -> ChatState:
    data = await openai_complete(
        model=state["model"],
        messages=state["raw_messages"],
        temperature=state.get("temperature"),
    )
    try:
        ch = data.get("choices", [])
        if ch:
            state["answer"] = ch[0]["message"]["content"]
    except Exception:
        state["answer"] = ""
    return state

async def ollama_call_node(state: ChatState) -> ChatState:
    out = await ollama_complete(
        model=state["model"],
        messages_lc=state["lc_messages"],
        temperature=state.get("temperature"),
    )
    state["answer"] = getattr(out, "content", "")
    return state

# ---- ストリーミング (writer 方式) ----
async def openai_stream_node(state: ChatState) -> ChatState:
    writer = get_stream_writer()
    partial = ""
    async for ev in openai_stream(
        model=state["model"],
        messages=state["raw_messages"],
        temperature=state.get("temperature"),
    ):
        choices = ev.get("choices", [])
        if not choices:
            continue
        delta = choices[0].get("delta", {}).get("content")
        if not delta:
            continue
        partial += delta
        state["partial_answer"] = partial
        # event_name 追加
        writer({
            "event_name": "token",
            "provider": state["provider"],
            "model": state["model"],
            "delta": delta,
            "partial": partial,
        })
    state["answer"] = partial
    return state

async def ollama_stream_node(state: ChatState) -> ChatState:
    writer = get_stream_writer()
    partial = ""
    async for chunk in ollama_stream(
        model=state["model"],
        messages_lc=state["lc_messages"],
        temperature=state.get("temperature"),
    ):
        delta = getattr(chunk, "content", "")
        if not delta:
            continue
        partial += delta
        state["partial_answer"] = partial
        writer({
            "event_name": "token",
            "provider": state["provider"],
            "model": state["model"],
            "delta": delta,
            "partial": partial,
        })
    state["answer"] = partial
    return state

def finalize_node(state: ChatState) -> ChatState:
    return state

# ---- Backward compatible wrapper functions (add) ----
import os, asyncio, time
from typing import AsyncGenerator

async def run_chat_graph(model: str | None, messages: list[dict], temperature: float | None):
    """
    Non-stream wrapper used by /v1/chat/completions.
    Returns final state dict (answer, provider, model).
    """
    graph = get_chat_graph()
    init_state = {
        "model": model,
        "raw_messages": messages,
        "temperature": temperature or 0.7,
        "stream": False,
    }
    out = await graph.ainvoke(init_state)
    return out  # contains provider, model, answer

async def stream_chat_graph(model: str | None, messages: list[dict], temperature: float | None) -> AsyncGenerator[dict, None]:
    """
    Stream wrapper yielding OpenAI-like chunk dicts:
      {"id": "...", "object":"chat.completion.chunk","choices":[{"delta":{"content":"..."},"index":0,"finish_reason":None}]}
    Final chunk sets finish_reason= "stop".
    """
    graph = get_chat_graph()
    init_state = {
        "model": model,
        "raw_messages": messages,
        "temperature": temperature or 0.7,
        "stream": True,
    }
    accumulated = ""
    chunk_id = "chatcmpl-" + os.urandom(8).hex()

    async for ev in graph.astream(init_state, stream_mode="updates"):
        updates = ev.get("updates")
        if not updates:
            continue
        for diff in updates:
            # provider / model を diff に含めない設計なので保持用に拾う
            # (必要ならノード内で provider / model も yield するよう拡張可)
            if "partial_answer" in diff:
                full = diff["partial_answer"]
                delta = full[len(accumulated):]
                if not delta:
                    continue
                accumulated = full
                yield {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "choices": [{
                        "index": 0,
                        "delta": {"content": delta},
                        "finish_reason": None
                    }],
                }
            if "answer" in diff:
                # Final completion marker
                yield {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }],
                }