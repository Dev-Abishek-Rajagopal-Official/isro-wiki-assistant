"""
LangGraph wiring:

    START -> router --(next_agent)--> rag_agent | launch_agent | wikidata_agent | celestrak_agent
               ^                                        |
               +----------------------------------------+   (every sub-agent returns to the router)
             router --(next_agent == final_agent)--> final_agent -> END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .agents.final import final_agent
from .agents.router import route_from_router, router
from .agents.subagent import make_subagent
from .state import SUB_AGENTS, AgentState


def build_graph(agent_tools: dict[str, dict], checkpointer=None):
    g = StateGraph(AgentState)
    g.add_node("router", router)
    for agent in SUB_AGENTS:
        g.add_node(agent, make_subagent(agent, agent_tools[agent]))
        g.add_edge(agent, "router")
    g.add_node("final_agent", final_agent)

    g.add_edge(START, "router")
    g.add_conditional_edges("router", route_from_router,
                            {**{a: a for a in SUB_AGENTS}, "final_agent": "final_agent"})
    g.add_edge("final_agent", END)
    return g.compile(checkpointer=checkpointer)
