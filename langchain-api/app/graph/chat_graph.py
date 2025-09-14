import os
from typing import TypedDict, List, Dict, Any, Literal
from langgraph.graph import StateGraph
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from typing import AsyncGenerator
from app.graph.self_maintenance_memories_graph import ask_more_word_meanings_node, ask_word_meanings_node, fetch_wellknown_words_node, fetch_word_meanings_node
from langchain_core.runnables import RunnableLambda, RunnableConfig
from app.graph.type import ChatState
from app.graph.provider_chat_graph import call_llm_node
from app.services.providers import (
    resolve_provider,
)

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

# ---- 親グラフ ----
_graph = None
def get_chat_graph():
    global _graph
    if _graph:
        return _graph
    g = StateGraph(ChatState)
    g.add_node("prepare_node", RunnableLambda(prepare_node))
    g.add_node("fetch_wellknown_words_node", RunnableLambda(fetch_wellknown_words_node))
    g.add_node("ask_word_meanings_node", ask_word_meanings_node)
    g.add_node("fetch_word_meanings_node", RunnableLambda(fetch_word_meanings_node))
    g.add_node("ask_more_word_meanings_node", ask_more_word_meanings_node)
    g.add_node("call_llm_node", call_llm_node)
    g.add_node("finalize_node", finalize_node)

    g.set_entry_point("prepare_node")

    g.add_edge("prepare_node", "fetch_wellknown_words_node")
    g.add_edge("fetch_wellknown_words_node", "ask_word_meanings_node")
    g.add_edge("ask_word_meanings_node", "fetch_word_meanings_node")
    g.add_edge("fetch_word_meanings_node", "ask_more_word_meanings_node")
    g.add_edge("ask_more_word_meanings_node", "call_llm_node")
    g.add_edge("call_llm_node", "finalize_node")
    g.add_edge("finalize_node", "__end__")
    _graph = g.compile()
    return _graph

def finalize_node(state: ChatState) -> ChatState:
    return state

# ---- Backward compatible wrapper functions (add) ----
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
