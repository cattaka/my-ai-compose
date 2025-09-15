from __future__ import annotations
from sqlalchemy import (
    String, Integer, DateTime, func, ForeignKey, Index, Boolean, select
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    memory_simplicity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    deleted_at: Mapped["DateTime | None"] = mapped_column(  # 追加
        DateTime(timezone=True), nullable=True, index=True
    )

    # 子 = 自分を親とする関係
    children = relationship(
        "MemoryRelation",
        foreign_keys="MemoryRelation.parent_id",
        cascade="all, delete-orphan",
        back_populates="parent",
    )
    # 親 = 自分を子とする関係
    parents = relationship(
        "MemoryRelation",
        foreign_keys="MemoryRelation.child_id",
        cascade="all, delete-orphan",
        back_populates="child",
    )

    __table_args__ = (
        Index("ix_memories_memory_simplicity", "memory_simplicity"),
    )


class MemoryRelation(Base):
    __tablename__ = "memory_relations"

    parent_id: Mapped[int] = mapped_column(ForeignKey("memories.id"), primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("memories.id"), primary_key=True)
    relation: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    parent = relationship("Memory", foreign_keys=[parent_id], back_populates="children")
    child = relationship("Memory", foreign_keys=[child_id], back_populates="parents")

async def select_active_memorys_by_memory_simplicity(session: AsyncSession, memory_simplicity: int) -> list[str]:
    stmt = select(Memory.title, Memory.memory_simplicity).where(Memory.memory_simplicity <= memory_simplicity).where(Memory.deleted_at == None)
    stmt = stmt.distinct().order_by(Memory.title)

    result = await session.execute(stmt)
    return result.all()

async def select_active_memories(session: AsyncSession, titles: list[str], memory_simplicity: int) -> list[Memory]:
    if not titles:
        return []
    stmt = (
        select(Memory.title, Memory.content)
        .where(Memory.title.in_(titles))
        .where(Memory.memory_simplicity <= memory_simplicity)
        .where(Memory.deleted_at == None)
    )
    rows = await session.execute(stmt)
    return rows.all()

async def upsert_memory(session: AsyncSession, title: str, content: str, parent_titles: list[str], source_url: str | None = None, memory_simplicity: int = 0) -> Memory:
    # titleでメモリを検索
    stmt = select(Memory).where(Memory.title == title)
    memory = (await session.execute(stmt)).scalars().first()
    if memory:
        # 既存のメモリがあれば更新
        memory.content = content
        memory.source_url = source_url
        memory.memory_simplicity = memory_simplicity
        memory.deleted_at = None  # 論理削除されていた場合は復活させる
    else:
        # 新しいメモリを作成
        memory = Memory(
            title=title,
            content=content,
            source_url=source_url,
            memory_simplicity=memory_simplicity
        )
        session.add(memory)
        await session.flush()  # IDを取得するためにflush

    if parent_titles:
        for parent_title in parent_titles:
            # 親メモリをタイトルで検索
            parent_memory = session.query(Memory).filter(Memory.title == parent_title).first()
            if parent_memory:
                # 親子関係が存在しない場合のみ追加
                existing_relation = session.query(MemoryRelation).filter(
                    MemoryRelation.parent_id == parent_memory.id,
                    MemoryRelation.child_id == memory.id
                ).first()
                if not existing_relation:
                    relation = MemoryRelation(
                        parent_id=parent_memory.id,
                        child_id=memory.id,
                        relation="related"  # 必要に応じて関係の種類を変更
                    )
                    session.add(relation)
    return memory

async def mark_memory_as_deleted(session: AsyncSession, title: str) -> bool:
    stmt = select(Memory).where(Memory.title == title, Memory.deleted_at == None)
    memory = (await session.execute(stmt)).scalars().first()
    if memory:
        memory.deleted_at = func.now()
        return True
    return False
