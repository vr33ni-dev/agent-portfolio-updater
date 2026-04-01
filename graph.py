from langgraph.graph import StateGraph, START, END
from state import PortfolioState
from nodes import read_repo, generate_summary, update_portfolio, create_pr


def build_graph():
    graph = StateGraph(PortfolioState)

    graph.add_node("read_repo", read_repo)
    graph.add_node("generate_summary", generate_summary)
    graph.add_node("update_portfolio", update_portfolio)
    graph.add_node("create_pr", create_pr)

    # Linear flow: read → generate → update → PR
    graph.add_edge(START, "read_repo")
    graph.add_edge("read_repo", "generate_summary")
    graph.add_edge("generate_summary", "update_portfolio")
    graph.add_edge("update_portfolio", "create_pr")
    graph.add_edge("create_pr", END)

    return graph.compile()
