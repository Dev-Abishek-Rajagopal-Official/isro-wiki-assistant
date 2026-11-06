"""
ORM models.

    users ─< conversations ─< threads ─< runs ─< llm_calls
                                          └──< agent_events   (owned by the orchestrator; FK added in migration)
    threads.id is the LangGraph thread_id: AgentState snapshots live in the checkpoint tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now(), nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)  # stored lowercase
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversations: Mapped[list[Conversation]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    title_source: Mapped[str | None] = mapped_column(String(20))       # "generated" | "user"
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="conversations")
    threads: Mapped[list[Thread]] = relationship(back_populates="conversation", cascade="all, delete-orphan",
                                                 order_by="Thread.created_at")


class Thread(TimestampMixin, Base):
    __tablename__ = "threads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"),
                                                       index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped[Conversation] = relationship(back_populates="threads")
    runs: Mapped[list[Run]] = relationship(back_populates="thread", cascade="all, delete-orphan",
                                           order_by="Run.started_at")


class Run(Base):
    """One user question processed by the agent graph (the orchestrator's run_id)."""
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), index=True,
                                                 nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    input_type: Mapped[str] = mapped_column(String(10), default="text", nullable=False)   # text | voice
    transcript: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12), default="running", nullable=False)   # running|succeeded|failed|cancelled
    answer: Mapped[str | None] = mapped_column(Text)
    agents_used: Mapped[list | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seconds: Mapped[float | None] = mapped_column(Float)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    thread: Mapped[Thread] = relationship(back_populates="runs")

    __table_args__ = (Index("runs_user_started_idx", "user_id", "started_at"),)


class LlmCall(Base):
    """One LLM API call with the usage reported by Azure (per run, or e.g. a conversation title)."""
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    node: Mapped[str | None] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    seconds: Mapped[float | None] = mapped_column(Float)
    ratelimit_remaining_requests: Mapped[int | None] = mapped_column(Integer)
    ratelimit_remaining_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("llm_calls_user_created_idx", "user_id", "created_at"),)
