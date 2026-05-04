import sys
import uuid
from dotenv import load_dotenv

load_dotenv()

from graph import build_graph
from review import review_and_confirm


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <repo_name> [<repo_name2> ...]")
        print("Example: python main.py vr33ni/my-frontend vr33ni/my-backend")
        sys.exit(1)

    repo_names = sys.argv[1:]
    repo_name = repo_names[0]

    # ===== CONFIGURE THIS =====
    PORTFOLIO_REPO = "vr33ni/portfolio"  # Your GitHub Pages repo
    # ==========================

    agent = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    initial_state = {
        "repo_name": repo_name,
        "repo_names": repo_names,
        "portfolio_repo": PORTFOLIO_REPO,
        "repo_info": {},
        "summary_html": "",
        "summary_html_es": "",
        "summary_html_de": "",
        "critique_feedback": "",
        "critique_retries": 0,
        "updated_files": [],
        "updated_file": "",
        "file_sha": "",
        "pr_url": "",
    }

    if len(repo_names) == 1:
        print(f"🔍 Reading repo: {repo_name}")
    else:
        print(f"🔍 Reading repos: {', '.join(repo_names)}")
    print(f"📝 Will update: {PORTFOLIO_REPO}")
    print()

    # Run until the interrupt (after critique, before update_portfolio)
    agent.invoke(initial_state, config)

    if not review_and_confirm(agent, config, repo_name):
        sys.exit(0)

    # Resume graph from update_portfolio onwards
    result = agent.invoke(None, config)
    print(f"\n🎉 Done! Review your PR at:\n{result['pr_url']}")


if __name__ == "__main__":
    main()
