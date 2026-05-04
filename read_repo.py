import os
from concurrent.futures import ThreadPoolExecutor
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


def _fetch_one_repo(g: Github, repo_name: str) -> dict:
    """Fetch all relevant data for a single repo."""
    repo = g.get_repo(repo_name)
    try:
        readme = repo.get_readme().decoded_content.decode("utf-8")
    except Exception:
        readme = ""
    subdir_readmes = _fetch_subdir_readmes(repo)
    code_context = _fetch_code_context(repo)
    return {
        "repo": repo,
        "name": repo.name,
        "url": repo.html_url,
        "original_url": f"https://github.com/{repo_name}",
        "description": repo.description or "",
        "languages": [k for k in repo.get_languages().keys() if not k.islower()],
        "topics": repo.get_topics(),
        "readme": readme,
        "subdir_readmes": subdir_readmes,
        "code_context": code_context,
        "stars": repo.stargazers_count,
        "created_at": repo.created_at,
    }


def read_repo(state: PortfolioState) -> dict:
    """Fetch repo info from GitHub: README, languages, topics, subdir READMEs.
    Supports multiple repos for a single card (frontend + backend)."""
    g = Github(os.getenv("GITHUB_TOKEN"))
    repo_names = state.get("repo_names") or [state["repo_name"]]

    with ThreadPoolExecutor(max_workers=len(repo_names)) as executor:
        repos_data = list(executor.map(lambda n: _fetch_one_repo(g, n), repo_names))

    if len(repos_data) == 1:
        rd = repos_data[0]
        repo_info = {
            "name": rd["name"],
            "full_name": repo_names[0],
            "description": rd["description"],
            "url": rd["url"],
            "urls": [rd["url"]],
            "names": [rd["name"]],
            "original_url": rd["original_url"],
            "languages": rd["languages"],
            "topics": rd["topics"],
            "readme": rd["readme"] + ("\n\n" + rd["subdir_readmes"] if rd["subdir_readmes"] else ""),
            "code_context": rd["code_context"],
            "stars": rd["stars"],
            "created_at": rd["created_at"].strftime("%B %Y"),
        }
        return {"repo_info": repo_info}

    # Multi-repo: aggregate across all repos
    all_languages = list(dict.fromkeys(lang for rd in repos_data for lang in rd["languages"]))
    all_topics = list(dict.fromkeys(t for rd in repos_data for t in rd["topics"]))

    readme_parts = []
    for rd in repos_data:
        if rd["readme"]:
            readme_parts.append(f"[{rd['name']}]\n{rd['readme'][:1500]}")
        if rd["subdir_readmes"]:
            readme_parts.append(rd["subdir_readmes"][:500])

    code_parts = []
    for rd in repos_data:
        if rd["code_context"]:
            code_parts.append(f"[{rd['name']}]\n{rd['code_context'][:800]}")

    descriptions = "; ".join(rd["description"] for rd in repos_data if rd["description"])
    primary = repos_data[0]

    repo_info = {
        "name": primary["name"],
        "full_name": repo_names[0],
        "description": descriptions,
        "url": primary["url"],
        "urls": [rd["url"] for rd in repos_data],
        "names": [rd["name"] for rd in repos_data],
        "original_url": primary["original_url"],
        "languages": all_languages,
        "topics": all_topics,
        "readme": "\n\n".join(readme_parts),
        "code_context": "\n\n".join(code_parts),
        "stars": primary["stars"],
        "created_at": primary["created_at"].strftime("%B %Y"),
    }
    return {"repo_info": repo_info}
