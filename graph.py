from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from state import PortfolioState
import read_repo, generate_summary, update_portfolio, create_pr, critique


def build_graph():
    graph = StateGraph(PortfolioState)

    graph.add_node("read_repo", read_repo.read_repo)
    graph.add_node("generate_summary", generate_summary.generate_summary)
    graph.add_node("critique", critique.critique)
    graph.add_node("update_portfolio", update_portfolio.update_portfolio)
    graph.add_node("create_pr", create_pr.create_pr)

    # Flow: read → generate → critique → (retry or proceed)
    graph.add_edge(START, "read_repo")
    graph.add_edge("read_repo", "generate_summary")
    graph.add_edge("generate_summary", "critique")
    graph.add_conditional_edges("critique", critique.should_retry)
    graph.add_edge("update_portfolio", "create_pr")
    graph.add_edge("create_pr", END)

    # Pause before update_portfolio so user can review the generated card
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer, interrupt_before=["update_portfolio"])
