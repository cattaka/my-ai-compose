from __future__ import annotations
from sqlalchemy import (
    String, Integer, DateTime, func, ForeignKey, Index
)
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