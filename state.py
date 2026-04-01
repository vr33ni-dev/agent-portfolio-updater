from typing import TypedDict


class PortfolioState(TypedDict):
    # Inputs
    repo_name: str              # e.g. "vreeni/agent-morning-briefing"
    portfolio_repo: str         # e.g. "vreeni/vreeni.github.io"

    # Data gathered by nodes
    repo_info: dict             # README, languages, description, etc.
    summary_html: str           # Generated portfolio card HTML
    updated_file: str           # Full updated portfolio HTML
    file_sha: str               # SHA of current file (needed for GitHub API update)

    # Output
    pr_url: str                 # URL of the created PR
