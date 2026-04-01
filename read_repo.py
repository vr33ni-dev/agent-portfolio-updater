import os
from github import Github
from state import PortfolioState


def read_repo(state: PortfolioState) -> dict:
    """Fetch repo info from GitHub: README, languages, description, topics."""
    g = Github(os.getenv("GITHUB_TOKEN"))
    repo = g.get_repo(state["repo_name"])

    # Get README content
    try:
        readme = repo.get_readme()
        readme_content = readme.decoded_content.decode("utf-8")
    except Exception:
        readme_content = "No README found."

    # Get languages used
    languages = list(repo.get_languages().keys())

    # Get repo metadata
    repo_info = {
        "name": repo.name,
        "full_name": repo.full_name,
        "description": repo.description or "No description provided.",
        "url": repo.html_url,
        "languages": languages,
        "topics": repo.get_topics(),
        "readme": readme_content,
        "stars": repo.stargazers_count,
        "created_at": repo.created_at.strftime("%B %Y"),
    }

    return {"repo_info": repo_info}
