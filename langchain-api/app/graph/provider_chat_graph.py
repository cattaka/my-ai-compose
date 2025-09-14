from __future__ import annotations
from typing import TypedDict, List, Dict, Any, Literal
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from app.services.llm import call_llm
from app.graph.type import ChatState

# ---- サブグラフ構築ヘルパ ----
from langgraph.graph import StateGraph as _StateGraph

async def call_llm_node(state: ChatState) -> ChatState:
    answer = await call_llm(
        provider=state["provider"],
        model=state["model"],
        messages_lc=state["lc_messages"],
        temperature=state.get("temperature"),
        stream=state.get("stream", False),
    )
    state["answer"] = answer
    return state
