import os
from github import Github
from state import PortfolioState

# Path to the portfolio page in the Jekyll repo
# Change this if your projects are on a different page
PORTFOLIO_FILE = "index.html"

# Marker comment where new projects get inserted
# Add this comment to your portfolio HTML where you want projects to appear:
#   <!-- NEW_PROJECTS_HERE -->
MARKER = "<!-- NEW_PROJECTS_HERE -->"


def update_portfolio(state: PortfolioState) -> dict:
    """Read current portfolio HTML and insert the new project card."""
    g = Github(os.getenv("GITHUB_TOKEN"))
    repo = g.get_repo(state["portfolio_repo"])

    # Get current portfolio file
    file = repo.get_contents(PORTFOLIO_FILE)
    current_html = file.decoded_content.decode("utf-8")
    file_sha = file.sha

    # Insert new project card after the marker
    if MARKER in current_html:
        updated_html = current_html.replace(
            MARKER,
            f"{MARKER}\n\n{state['summary_html']}\n",
        )
    else:
        # If no marker found, warn but still prepare the content
        print(
            f"⚠️  Marker '{MARKER}' not found in {PORTFOLIO_FILE}."
            f"\n   Add it to your HTML where you want projects inserted."
            f"\n   The project card was generated but couldn't be placed."
        )
        updated_html = current_html

    return {
        "updated_file": updated_html,
        "file_sha": file_sha,
    }
