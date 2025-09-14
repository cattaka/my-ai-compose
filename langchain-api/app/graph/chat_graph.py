import os
from typing import TypedDict, List, Any
from langgraph.graph import StateGraph
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from app.services.llm import get_llm
from app.graph.provider_chat_graph import build_provider_subgraph
from typing import AsyncGenerator
from app.graph.type import ChatState
from app.graph.provider_chat_graph import prepare_node

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
