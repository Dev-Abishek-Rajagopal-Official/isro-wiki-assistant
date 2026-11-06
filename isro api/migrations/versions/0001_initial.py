"""Initial schema: users, conversations, threads, runs, llm_calls; link agent_events to runs.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

# Same DDL as orchestrator/events.py (CREATE IF NOT EXISTS, so either side may create it first).
AGENT_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS agent_events (
    id BIGSERIAL PRIMARY KEY, thread_id TEXT NOT NULL, run_id UUID NOT NULL, seq INTEGER NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(), node TEXT, event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb, UNIQUE (run_id, seq))"""


def _timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "users",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        *_timestamps())
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "conversations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200)),
        sa.Column("title_source", sa.String(20)),
        sa.Column("archived", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_activity_at", sa.DateTime(timezone=True)),
        *_timestamps())
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "threads",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("conversation_id", uuid, sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200)),
        sa.Column("archived", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        *_timestamps())
    op.create_index("ix_threads_conversation_id", "threads", ["conversation_id"])
    op.create_index("ix_threads_user_id", "threads", ["user_id"])

    op.create_table(
        "runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("thread_id", uuid, sa.ForeignKey("threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("input_type", sa.String(10), nullable=False, server_default="text"),
        sa.Column("transcript", postgresql.JSONB),
        sa.Column("status", sa.String(12), nullable=False, server_default="running"),
        sa.Column("answer", sa.Text),
        sa.Column("agents_used", postgresql.JSONB),
        sa.Column("error", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("seconds", sa.Float),
        *[sa.Column(c, sa.Integer, nullable=False, server_default="0")
          for c in ("llm_calls", "input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")])
    op.create_index("ix_runs_thread_id", "runs", ["thread_id"])
    op.create_index("runs_user_started_idx", "runs", ["user_id", "started_at"])

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id", uuid, sa.ForeignKey("runs.id", ondelete="CASCADE")),
        sa.Column("thread_id", uuid),
        sa.Column("conversation_id", uuid),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node", sa.String(40)),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        *[sa.Column(c, sa.Integer, nullable=False, server_default="0")
          for c in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")],
        sa.Column("seconds", sa.Float),
        sa.Column("ratelimit_remaining_requests", sa.Integer),
        sa.Column("ratelimit_remaining_tokens", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    for col in ("run_id", "thread_id", "conversation_id"):
        op.create_index(f"ix_llm_calls_{col}", "llm_calls", [col])
    op.create_index("llm_calls_user_created_idx", "llm_calls", ["user_id", "created_at"])

    # Orchestrator event log: ensure it exists, then link it to runs. NOT VALID keeps events written
    # before the API existed (development runs) while enforcing the link for every new row.
    op.execute(AGENT_EVENTS_DDL)
    op.execute("CREATE INDEX IF NOT EXISTS agent_events_thread_idx ON agent_events (thread_id, id)")
    op.execute("ALTER TABLE agent_events ADD CONSTRAINT agent_events_run_fk FOREIGN KEY (run_id) "
               "REFERENCES runs (id) ON DELETE CASCADE NOT VALID")


def downgrade() -> None:
    op.execute("ALTER TABLE agent_events DROP CONSTRAINT IF EXISTS agent_events_run_fk")
    for table in ("llm_calls", "runs", "threads", "conversations", "users"):
        op.drop_table(table)
