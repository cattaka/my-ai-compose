from __future__ import annotations
from typing import TypedDict, List, Dict, Any, Optional, Literal
from langgraph.graph import StateGraph
from langgraph.config import get_stream_writer  # 使うなら (今は未使用)
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.graph.type import ChatState

# --- DB Models ---
from app.db.models.memory import Memory  # id, title, content, memory_simplicity,...

# --- LLM (任意: プロジェクト既存の provider 解決を流用してもよい) ---
# ここでは抽象インターフェースだけ定義し、実装は後で差し替え
async def llm_call(prompt: str) -> str:
    """
    TODO: 実際には ChatOpenAI 等を呼ぶ。
    """
    return "TODO: implement LLM call\n" + prompt[:200]

# ============= ノード実装 =============

async def fetch_wellknown_words_node(state: ChatState, session: AsyncSession) -> ChatState:
    """
    memory_simplicity <= 0 の語彙を title リストで取得して state["wellknown_words"] に格納
    オプション: state に limit / offset / distinct フラグがあれば反映
    """
    limit: int | None = state.get("wellknown_limit")          # 例: 上限件数
    offset: int = state.get("wellknown_offset", 0)
    use_distinct: bool = state.get("wellknown_distinct", False)

    stmt = select(Memory.title).where(Memory.memory_simplicity <= 0)

    if use_distinct:
        # 重複を避けたい場合
        stmt = stmt.distinct().order_by(Memory.title)
    else:
        # 安定順序 (ID 昇順)
        stmt = stmt.order_by(Memory.id)

    if offset:
        stmt = stmt.offset(offset)
    if limit:
        stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    titles = result.scalars().all()

    state["wellknown_words"] = titles
    state.setdefault("word_meanings", [])
    state.setdefault("requested_words", [])
    state.setdefault("notes", [])
    state.setdefault("memory_simplicity", state.get("memory_simplicity", 0))
    state.setdefault("max_memory_simplicity", 1000)
    return state


async def ask_word_meanings_node(state: ChatState) -> ChatState:
    """
    ユーザ入力中の未知語抽出。今は簡易実装:
    wellknown_words に含まれない単語を requested_words にする。
    """
    text = state.get("lc_messages", "")
    tokens = list({t for t in text.replace("\n", " ").split(" ") if t})
    known = set(state.get("wellknown_words", []))
    # 既に意味取得済みは除外
    already = {w["title"] for w in state.get("word_meanings", [])}
    req = [t for t in tokens if t not in known and t not in already]
    state["requested_words"] = req[:32]  # 過剰防止 (任意)
    return state


async def fetch_word_meanings_node(state: ChatState, session: AsyncSession) -> ChatState:
    """
    requested_words の中で DB にある単語の意味を取得 (current memory_simplicity の閾値まで)
    """
    if not state.get("requested_words"):
        return state
    threshold = state.get("memory_simplicity", 0)
    req = state["requested_words"]
    if not req:
        return state
    stmt = (
        select(Memory.title, Memory.content)
        .where(Memory.title.in_(req))
        .where(Memory.memory_simplicity <= threshold)
    )
    rows = await session.execute(stmt)
    found = [{"title": r[0], "content": r[1]} for r in rows.all()]
    # 既存とマージ
    existing = {m["title"]: m for m in state.get("word_meanings", [])}
    for m in found:
        existing[m["title"]] = m
    state["word_meanings"] = list(existing.values())
    return state


async def ask_more_word_meanings_node(state: ChatState) -> ChatState:
    """
    単語の意味を付加した上で回答を試みる。
    LLM に投げて 'require_more_memory' を判定 (簡易ルール)。
    """
    lc_messages = state.get("lc_messages", "")
    word_defs = "\n".join(f"- {w['title']}: {w['content']}" for w in state.get("word_meanings", []))
    prompt = f"""ユーザ入力:
{lc_messages}

既知の単語定義:
{word_defs or '(なし)'}
上記を踏まえて簡潔に回答せよ。追加の外部知識が必要なら 'NEED_MORE' を末尾に付ける。
"""
    raw = await llm_call(prompt)
    need_more = raw.strip().endswith("NEED_MORE")
    answer = raw.replace("NEED_MORE", "").rstrip()
    state["answer"] = answer
    state["require_more_memory"] = need_more
    return state


async def ask_updated_memories_node(state: ChatState) -> ChatState:
    """
    回答過程で学習すべき新出単語 / 知識を抽出。
    簡易: requested_words のうち未登録 = updated_words。
    updated_memories は今回は空の雛形。
    """
    known_titles = {w["title"] for w in state.get("word_meanings", [])}
    new_words = [
        {"title": w, "content": ""}  # content は後で LLM で補完する想定
        for w in state.get("requested_words", [])
        if w not in known_titles
    ]
    state["updated_words"] = new_words
    state["updated_memories"] = []  # 拡張用
    return state


async def save_updated_memories_node(state: ChatState, session: AsyncSession) -> ChatState:
    """
    updated_words / updated_memories を DB に upsert (簡易: INSERT IGNORE 的挙動)
    """
    from sqlalchemy import select
    if state.get("updated_words"):
        # 既存タイトル取得
        titles = [w["title"] for w in state["updated_words"] if w["title"]]
        if titles:
            existing_stmt = select(Memory.title).where(Memory.title.in_(titles))
            existing_rows = await session.execute(existing_stmt)
            existing = set(existing_rows.scalars())
        else:
            existing = set()
        for w in state["updated_words"]:
            if not w["title"] or w["title"] in existing:
                continue
            m = Memory(
                title=w["title"],
                content=w.get("content") or "",
                memory_simplicity=0,  # 単語は 0
            )
            session.add(m)
    # updated_memories (simplicity=500)
    if state.get("updated_memories"):
        titles500 = [m["title"] for m in state["updated_memories"] if m.get("title")]
        existing_stmt2 = select(Memory.title).where(Memory.title.in_(titles500))
        existing_rows2 = await session.execute(existing_stmt2)
        existing2 = set(existing_rows2.scalars())
        for m500 in state["updated_memories"]:
            if not m500.get("title") or m500["title"] in existing2:
                continue
            m = Memory(
                title=m500["title"],
                content=m500.get("content") or "",
                memory_simplicity=500,
            )
            session.add(m)
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        state["error"] = f"commit failed: {e}"
    return state


def finalize_node(state: ChatState) -> ChatState:
    """
    最終出力整形 (必要なら)
    """
    return state


# ============= フロー制御 =============

def should_increase_level(state: ChatState) -> Literal[
    "loop_again",
    "proceed_update",
]:
    if state.get("require_more_memory"):
        # まだ上げられるならループ
        cur = state.get("memory_simplicity", 0)
        max_level = state.get("max_memory_simplicity", 1000)
        if cur < max_level:
            # 次のループへ
            return "loop_again"
    return "proceed_update"


# ============= グラフ構築 =============

def build_memory_graph():
    g = StateGraph(ChatState)

    # ノード登録 (DB セッションが必要なものはラップ)
    # ラップ: LangGraph は引数 state のみを渡すため session をクロージャで注入するファクトリを用意
    def with_session(fn):
        async def wrapper(state: ChatState, *, session: AsyncSession):
            return await fn(state, session)
        return wrapper

    # session 受け取りのため run(time) 側で config / context に渡す想定。
    # ここでは signature を (state, session=...) に揃えるため簡易アダプタ。
    async def fetch_wellknown_words_node_adapt(state: ChatState, session: AsyncSession):
        return await fetch_wellknown_words_node(state, session)

    async def fetch_word_meanings_node_adapt(state: ChatState, session: AsyncSession):
        return await fetch_word_meanings_node(state, session)

    async def save_updated_memories_node_adapt(state: ChatState, session: AsyncSession):
        return await save_updated_memories_node(state, session)

    # 直接 state だけのノード
    g.add_node("fetch_wellknown_words_node", fetch_wellknown_words_node_adapt)
    g.add_node("ask_word_meanings_node", ask_word_meanings_node)
    g.add_node("fetch_word_meanings_node", fetch_word_meanings_node_adapt)
    g.add_node("ask_more_word_meanings_node", ask_more_word_meanings_node)
    g.add_node("ask_updated_memories_node", ask_updated_memories_node)
    g.add_node("save_updated_memories_node", save_updated_memories_node_adapt)
    g.add_node("finalize_node", finalize_node)

    g.set_entry_point("fetch_wellknown_words_node")
    g.add_edge("fetch_wellknown_words_node", "ask_word_meanings_node")
    g.add_edge("ask_word_meanings_node", "fetch_word_meanings_node")
    g.add_edge("fetch_word_meanings_node", "ask_more_word_meanings_node")

    # 条件分岐: 追加知識必要ならレベル上げて再度 ask_word_meanings_node へ
    def loop_or_update(state: ChatState):
        result = should_increase_level(state)
        return result

    g.add_conditional_edges(
        "ask_more_word_meanings_node",
        loop_or_update,
        {
            "loop_again": "ask_word_meanings_node",
            "proceed_update": "ask_updated_memories_node",
        },
    )
    g.add_edge("ask_updated_memories_node", "save_updated_memories_node")
    g.add_edge("save_updated_memories_node", "finalize_node")
    g.add_edge("finalize_node", "__end__")

    return g.compile()


# シングルトン取得
_memory_graph = None
def get_memory_graph():
    global _memory_graph
    if _memory_graph:
        return _memory_graph
    _memory_graph = build_memory_graph()
    return _memory_graph

# --- 利用例メモ (実装者向け) ---
"""
async def run_memory_flow(lc_messages: str, session: AsyncSession):
    graph = get_memory_graph()
    init: ChatState = {
        "lc_messages": lc_messages,
        "memory_simplicity": 0,
    }
    # ainvoke で session を渡したい場合は run/config に context 注入が必要。
    # 現行の簡易形では各ノードに session を引数接続する middleware が必要になる。
    # ここでは擬似コード:
    result = await graph.ainvoke(init, config={"configurable": {"session": session}})
    return result
"""
