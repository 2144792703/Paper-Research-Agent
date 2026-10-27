from langgraph.graph import StateGraph, START, END

from graph.nodes import supervisor_node, worker_search, worker_summarize_one, worker_summarize, critic_node, followup_node, worker_select
from graph.state import SupervisorState

from logger import logger

def route(state: SupervisorState):
    logger.info("route")
    return state['next']

def after_critic(state: SupervisorState):
    logger.info("after_critic")
    if state['critique'].strip() == "通过" or state['revision_count'] >= state['critique_times']:
        return "finish"
    return "supervisor"

graph = StateGraph(SupervisorState)
graph.add_node("supervisor", supervisor_node)
graph.add_node("search", worker_search)
graph.add_node("select", worker_select)
graph.add_node("summarize_one",worker_summarize_one)
graph.add_node("summarize", worker_summarize)
graph.add_node("critic", critic_node)
graph.add_node("followup", followup_node)

graph.add_edge(START, "supervisor")
graph.add_edge('search', 'select')
graph.add_edge('select', 'summarize_one')
graph.add_edge('summarize_one', 'supervisor')
graph.add_edge('summarize', 'supervisor')

graph.add_conditional_edges(
    "supervisor",
    route,
    {
        "search": "search",
        "summarize": "summarize",
        "critic": "critic",
    }
)
graph.add_conditional_edges(
    "critic",
    after_critic,
    {
        "supervisor": "supervisor",
        "finish": 'followup',
    }
)

graph.add_edge("followup", END)

graph = graph.compile()