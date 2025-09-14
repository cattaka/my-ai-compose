from typing import TypedDict, List, Dict, Any
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage

class ChatState(TypedDict, total=False):
    # 内部
    model: str
    provider: str
    raw_messages: List[Dict[str, str]]
    temperature: float
    stream: bool
    partial_answer: str
    error: str
    # 入力
    lc_messages: List[BaseMessage]
    # 制御
    memory_simplicity: int                # 0 -> 500 -> 1000
    max_memory_simplicity: int            # 上限 (既定 1000)
    # 取得済み
    wellknown_words: List[str]            # simplicity <= 0 の単語
    requested_words: List[str]            # 意味要求が必要な単語
    word_meanings: List[Dict[str, str]]   # {title, content}
    # 応答生成
    answer: str
    require_more_memory: bool
    # 更新候補
    updated_words: List[Dict[str, str]]   # {title, content}
    updated_memories: List[Dict[str, Any]]  # {title, content, parents:[memory_id]}
    # 出力補助
    notes: List[str]
