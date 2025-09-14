from __future__ import annotations
from typing import TypedDict, List, Dict, Any, Literal
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from app.services.llm import call_llm
from app.graph.type import ChatState
from pydantic import BaseModel

# ---- サブグラフ構築ヘルパ ----
from langgraph.graph import StateGraph as _StateGraph

async def call_llm_node(state: ChatState) -> ChatState:
    messages_lc = state.get("lc_messages", [])
    word_meanings = state.get("word_meanings", [])
    if len(word_meanings) > 0:
        messages_lc = messages_lc + [SystemMessage(content=(
            "既知の単語定義:\n"
            + "\n".join(f"- {w['title']}: {w['content']}" for w in word_meanings)
        ))]

    answer = await call_llm(
        provider=state["provider"],
        model=state["model"],
        messages_lc=messages_lc,
        temperature=state.get("temperature"),
        stream=state.get("stream", False),
    )
    state["answer"] = answer
    return state
