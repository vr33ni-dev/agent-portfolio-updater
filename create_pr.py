import os
from datetime import datetime
from github import Github
from state import PortfolioState


def create_pr(state: PortfolioState) -> dict:
    """Create a branch, commit the updated portfolio files, and open a PR."""
    g = Github(os.getenv("GITHUB_TOKEN"))
    repo = g.get_repo(state["portfolio_repo"])

    # Create a branch name from the project being added
    project_name = state["repo_info"]["name"]
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    branch_name = f"add-project/{project_name}-{timestamp}"

    # Get the default branch's latest commit SHA
    default_branch = repo.default_branch
    base_ref = repo.get_git_ref(f"heads/{default_branch}")
    base_sha = base_ref.object.sha

    # Create the new branch
    repo.create_git_ref(
        ref=f"refs/heads/{branch_name}",
        sha=base_sha,
    )

    # Commit each updated language file to the new branch
    for file_entry in state["updated_files"]:
        repo.update_file(
            path=file_entry["path"],
            message=f"Add {project_name} to portfolio ({file_entry['path']})",
            content=file_entry["content"],
            sha=file_entry["sha"],
            branch=branch_name,
        )

    # Create the PR
    pr = repo.create_pull(
        title=f"Add {project_name} to portfolio",
        body=(
            f"Automated PR to add **{project_name}** to the portfolio.\n\n"
            f"## Generated Summary\n"
            f"Review the project card below and edit if needed before merging.\n\n"
            f"---\n"
            f"Repo: {state['repo_info']['url']}\n"
            f"Languages: {', '.join(state['repo_info']['languages'])}\n"
        ),
        head=branch_name,
        base=default_branch,
    )

    print(f"\n✅ PR created: {pr.html_url}")
    return {"pr_url": pr.html_url}
