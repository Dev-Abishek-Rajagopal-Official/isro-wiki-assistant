"""Helpers shared by the graph nodes."""

from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.config import get_stream_writer


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d (%A)")


def emit(event_type: str, node: str, **payload) -> None:
    """Progress event for the frontend + event log (LangGraph 'custom' stream)."""
    try:
        writer = get_stream_writer()
    except Exception:  # noqa: BLE001  (node called outside a streaming run, e.g. unit tests)
        return
    writer({"event_type": event_type, "node": node, **payload})


def history_text(messages: list, max_turns: int = 6, max_chars: int = 600) -> str:
    """Previous turns only (the current question is passed separately)."""
    past = messages[:-1] if messages and isinstance(messages[-1], HumanMessage) else messages
    lines = []
    for m in past[-max_turns:]:
        role = "User" if isinstance(m, HumanMessage) else "Assistant" if isinstance(m, AIMessage) else m.type
        text = m.content if isinstance(m.content, str) else str(m.content)
        lines.append(f"{role}: {text[:max_chars]}")
    return "\n".join(lines) or "(no earlier turns)"
