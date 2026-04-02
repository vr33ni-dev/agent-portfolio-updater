import os
from github import Github
from state import PortfolioState

# All language versions of the portfolio page to update
PORTFOLIO_FILES = ["work.html", "work.es.html", "work.de.html"]

# Marker comment where new projects get inserted
# Add this comment to your portfolio HTML where you want projects to appear:
#   <!-- NEW_PROJECTS_HERE -->
MARKER = "<!-- NEW_PROJECTS_HERE -->"


def update_portfolio(state: PortfolioState) -> dict:
    """Read current portfolio HTML files and insert the new project card into each."""
    g = Github(os.getenv("GITHUB_TOKEN"))
    repo = g.get_repo(state["portfolio_repo"])

    lang_map = {
        "work.html": state["summary_html"],
        "work.es.html": state["summary_html_es"],
        "work.de.html": state["summary_html_de"],
    }

    updated_files = []

    for portfolio_file in PORTFOLIO_FILES:
        file = repo.get_contents(portfolio_file)
        current_html = file.decoded_content.decode("utf-8")
        card_html = lang_map[portfolio_file]

        if MARKER in current_html:
            updated_html = current_html.replace(
                MARKER,
                f"{MARKER}\n\n{card_html}\n",
            )
        else:
            print(
                f"⚠️  Marker '{MARKER}' not found in {portfolio_file}."
                f"\n   Add <!-- NEW_PROJECTS_HERE --> where you want cards inserted."
                f"\n   Skipping {portfolio_file}."
            )
            continue

        updated_files.append({
            "path": portfolio_file,
            "content": updated_html,
            "sha": file.sha,
        })

    return {
        "updated_files": updated_files,
        "updated_file": updated_files[0]["content"] if updated_files else "",
        "file_sha": updated_files[0]["sha"] if updated_files else "",
    }
