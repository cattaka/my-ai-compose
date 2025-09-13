from __future__ import annotations
from typing import TypedDict, List, Any
from langgraph.graph import StateGraph
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from app.services.llm import get_llm

class ChatState(TypedDict, total=False):
    model: str
    messages: List[dict]          # OpenAI 形式 ({role, content})
    lc_messages: List[BaseMessage]
    answer: str

def to_lc_messages(raw: List[dict]) -> List[BaseMessage]:
    out: List[BaseMessage] = []
    for m in raw:
        role = m.get("role")
        content = m.get("content", "")
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out

def prepare_node(state: ChatState) -> ChatState:
    # 既存 lc_messages が無ければ生成
    if "lc_messages" not in state:
        state["lc_messages"] = to_lc_messages(state["messages"])
    return state

def llm_node(state: ChatState) -> ChatState:
    llm = get_llm(model=state["model"])
    out = llm.invoke(state["lc_messages"])
    state["answer"] = out.content if hasattr(out, "content") else str(out)
    return state

# 単純グラフをビルド
_graph = None
def build_graph():
    global _graph
    if _graph is not None:
        return _graph
    g = StateGraph(ChatState)
    g.add_node("prepare_node", prepare_node)
    g.add_node("llm_node", llm_node)
    g.set_entry_point("prepare_node")
    g.add_edge("prepare_node", "llm_node")
    g.add_edge("llm_node", "__end__")
    _graph = g.compile()
    return _graph

def run_simple_chat(model: str, messages: List[dict]) -> str:
    graph = build_graph()
    final: ChatState = graph.invoke({"model": model, "messages": messages})
    return final.get("answer", "")