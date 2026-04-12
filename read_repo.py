import os
from github import Github
from state import PortfolioState

# Subdirectories to look for additional READMEs (in priority order)
SUBDIR_README_CANDIDATES = ["client", "frontend", "app", "web", "src"]

# Key config/manifest files that reveal capabilities (PWA, ML, deps, etc.)
CODE_CONTEXT_FILES = [
    "package.json", "manifest.json", "sw.js", "service-worker.js",
    "requirements.txt", "pyproject.toml", "go.mod", "Cargo.toml",
]


def _fetch_subdir_readmes(repo) -> str:
    """Fetch READMEs from known frontend/client subdirectories if they exist."""
    extras = []
    for subdir in SUBDIR_README_CANDIDATES:
        try:
            contents = repo.get_contents(subdir)
            for item in contents:
                if item.name.upper().startswith("README"):
                    text = item.decoded_content.decode("utf-8")
                    extras.append(f"--- README from /{subdir} ---\n{text[:1000]}")
                    break  # one per subdir is enough
        except Exception:
            continue
    return "\n\n".join(extras)


def _fetch_code_context(repo) -> str:
    """Fetch key config/manifest files to surface capabilities like PWA, ML, deps."""
    snippets = []
    for filename in CODE_CONTEXT_FILES:
        try:
            f = repo.get_contents(filename)
            text = f.decoded_content.decode("utf-8")
            snippets.append(f"--- {filename} ---\n{text[:500]}")
        except Exception:
            continue
    # Also search one level of subdirectories for the same files
    try:
        root_items = repo.get_contents("")
        for item in root_items:
            if item.type == "dir":
                for filename in CODE_CONTEXT_FILES:
                    try:
                        f = repo.get_contents(f"{item.name}/{filename}")
                        text = f.decoded_content.decode("utf-8")
                        snippets.append(f"--- {item.name}/{filename} ---\n{text[:500]}")
                    except Exception:
                        continue
    except Exception:
        pass
    return "\n\n".join(snippets)


def read_repo(state: PortfolioState) -> dict:
    """Fetch repo info from GitHub: README, languages, topics, subdir READMEs."""
    g = Github(os.getenv("GITHUB_TOKEN"))
    repo = g.get_repo(state["repo_name"])

    # Get root README content
    try:
        readme = repo.get_readme()
        readme_content = readme.decoded_content.decode("utf-8")
    except Exception:
        readme_content = "No README found."

    # Supplement with subdir READMEs for monorepos / multi-package repos
    subdir_readmes = _fetch_subdir_readmes(repo)
    if subdir_readmes:
        readme_content = readme_content + "\n\n" + subdir_readmes

    # Fetch key config files to surface capabilities (PWA, ML, deps, etc.)
    code_context = _fetch_code_context(repo)

    # Get languages used
    languages = list(repo.get_languages().keys())

    # Get repo metadata
    repo_info = {
        "name": repo.name,
        "full_name": repo.full_name,
        "description": repo.description or "No description provided.",
        "url": repo.html_url,
        "original_url": f"https://github.com/{state['repo_name']}",
        "languages": languages,
        "topics": repo.get_topics(),
        "readme": readme_content,
        "code_context": code_context,
        "stars": repo.stargazers_count,
        "created_at": repo.created_at.strftime("%B %Y"),
    }

    return {"repo_info": repo_info}
