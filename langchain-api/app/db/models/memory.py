from __future__ import annotations
from sqlalchemy import String, Integer, DateTime, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class Memory(Base):
    __tablename__ = "memories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    content: Mapped[str] = mapped_column()
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parents = relationship(
        "MemoryRelation",
        foreign_keys="MemoryRelation.child_id",
        cascade="all, delete-orphan",
        back_populates="child",
    )
    children = relationship(
        "MemoryRelation",
        foreign_keys="MemoryRelation.parent_id",
        cascade="all, delete-orphan",
        back_populates="parent",
    )

class MemoryRelation(Base):
    __tablename__ = "memory_relations"
    parent_id: Mapped[int] = mapped_column(ForeignKey("memories.id"), primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("memories.id"), primary_key=True)
    relation: Mapped[str] = mapped_column(String(50))

    parent = relationship("Memory", foreign_keys=[parent_id], back_populates="children")
    child = relationship("Memory", foreign_keys=[child_id], back_populates="parents")