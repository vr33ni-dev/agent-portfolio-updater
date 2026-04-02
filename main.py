import sys
from dotenv import load_dotenv

load_dotenv()

from graph import build_graph


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <repo_name>")
        print("Example: python main.py vr33ni/agent-morning-briefing")
        sys.exit(1)

    repo_name = sys.argv[1]

    # ===== CONFIGURE THIS =====
    PORTFOLIO_REPO = "vr33ni/portfolio"  # Your GitHub Pages repo
    # ==========================

    agent = build_graph()

    initial_state = {
        "repo_name": repo_name,
        "portfolio_repo": PORTFOLIO_REPO,
        "repo_info": {},
        "summary_html": "",
        "updated_files": [],
        "updated_file": "",
        "file_sha": "",
        "pr_url": "",
    }

    print(f"🔍 Reading repo: {repo_name}")
    print(f"📝 Will update: {PORTFOLIO_REPO}")
    print()

    result = agent.invoke(initial_state)

    print(f"\n🎉 Done! Review your PR at:\n{result['pr_url']}")


if __name__ == "__main__":
    main()
