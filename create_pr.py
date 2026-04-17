import os
from datetime import datetime
from github import Github
from state import PortfolioState

# GitHub username to request review from
PR_REVIEWER = "vr33ni"


def create_pr(state: PortfolioState) -> dict:
    """Create a branch, commit the updated portfolio files, and open a PR.
    If an open PR already exists for this project, push to its branch instead."""
    g = Github(os.getenv("GITHUB_TOKEN"))
    repo = g.get_repo(state["portfolio_repo"])

    project_name = state["repo_info"]["name"]
    default_branch = repo.default_branch

    # Check for an existing open PR for this project
    existing_pr = None
    existing_branch = None
    for pr in repo.get_pulls(state="open"):
        if pr.head.ref.startswith(f"add-project/{project_name}"):
            existing_pr = pr
            existing_branch = pr.head.ref
            break

    if existing_branch:
        # Push new commits to the existing branch
        branch_name = existing_branch
        print(f"  🔄 Updating existing PR branch: {branch_name}")
    else:
        # Create a new branch
        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        branch_name = f"add-project/{project_name}-{timestamp}"
        base_ref = repo.get_git_ref(f"heads/{default_branch}")
        base_sha = base_ref.object.sha
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)

    # Commit each updated language file to the branch
    for file_entry in state["updated_files"]:
        # Get the current SHA of the file on this branch (may differ from default branch)
        try:
            current_file = repo.get_contents(file_entry["path"], ref=branch_name)
            file_sha = current_file.sha
        except Exception:
            file_sha = file_entry["sha"]

        repo.update_file(
            path=file_entry["path"],
            message=f"{'Update' if existing_branch else 'Add'} {project_name} in portfolio ({file_entry['path']})",
            content=file_entry["content"],
            sha=file_sha,
            branch=branch_name,
        )

    if existing_pr:
        # Update the PR title/body to reflect the refresh
        existing_pr.edit(
            title=f"Update {project_name} in portfolio",
            body=(
                f"Automated PR to update **{project_name}** in the portfolio.\n\n"
                f"Repo: {state['repo_info']['url']}\n"
                f"Languages: {', '.join(state['repo_info']['languages'])}\n"
            ),
        )
        print(f"\n✅ PR updated: {existing_pr.html_url}")
        return {"pr_url": existing_pr.html_url}

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

    try:
        pr.create_review_request(reviewers=[PR_REVIEWER])
    except Exception as e:
        if "review cannot be requested from pull request author" not in str(e).lower():
            print(f"⚠️  Could not add reviewer: {e}")

    print(f"\n✅ PR created: {pr.html_url}")
    return {"pr_url": pr.html_url}
