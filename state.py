from typing import TypedDict


class PortfolioState(TypedDict):
    # Inputs
    repo_name: str              # e.g. "vr33ni/agent-morning-briefing"
    portfolio_repo: str         # e.g. "vr33ni/vr33ni.github.io"

    # Data gathered by nodes
    repo_info: dict             # README, languages, description, etc.
    summary_html: str           # Generated portfolio card HTML (EN)
    summary_html_es: str        # Generated portfolio card HTML (ES)
    summary_html_de: str        # Generated portfolio card HTML (DE)
    updated_files: list         # List of {path, content, sha} for each language file
    updated_file: str           # Full updated portfolio HTML (kept for compatibility)
    file_sha: str               # SHA of current file (kept for compatibility)

    # Output
    pr_url: str                 # URL of the created PR
