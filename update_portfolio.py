import os
import re
from github import Github
from state import PortfolioState

# All language versions of the portfolio page to update
PORTFOLIO_FILES = ["work.html", "work.es.html", "work.de.html"]

# Marker comment where new projects get inserted
MARKER = "<!-- NEW_PROJECTS_HERE -->"


def _normalize_url(url: str) -> str:
    return url.rstrip("/").lower()


def _replace_or_insert(current_html: str, card_html: str, repo_url: str, marker: str) -> tuple[str, str]:
    """
    If the repo URL already exists in the page, replace the entire card block.
    Otherwise insert after the marker.
    Returns (updated_html, action) where action is 'updated' or 'added'.
    """
    # Check if any variant of the URL appears in the HTML
    url_present = repo_url in current_html or repo_url.rstrip("/") in current_html
    if url_present:
        # Split on card boundaries and replace the chunk containing the repo URL
        parts = re.split(r'(?=<div class="bg-white)', current_html)
        new_parts = []
        replaced = False
        for part in parts:
            if not replaced and (repo_url in part or repo_url.rstrip("/") in part):
                new_parts.append(card_html + "\n")
                replaced = True
            else:
                new_parts.append(part)
        if replaced:
            return "".join(new_parts), "updated"
        # Split didn't isolate the card — fall through to insert
    if marker in current_html:
        updated_html = current_html.replace(marker, f"{marker}\n\n{card_html}\n", 1)
        return updated_html, "added"
    return current_html, "skipped"


def _extract_repo_urls(html: str) -> list[str]:
    """Return ordered list of GitHub repo URLs found in card blocks."""
    parts = re.split(r'(?=<div class="bg-white)', html)
    urls = []
    for part in parts:
        matches = re.findall(r'href="(https://github\.com/[^"]+)"', part)
        for m in matches:
            # Only full repo URLs (not .github.io etc.)
            segs = m.rstrip("/").split("/")
            if len(segs) == 5:
                urls.append(m.rstrip("/"))
                break
    return urls


def _insert_at_position(current_html: str, card_html: str, repo_url: str, reference_urls: list[str], marker: str) -> str:
    """Insert card_html in the same relative position as repo_url appears in reference_urls.
    Falls back to inserting after the marker if position cannot be determined."""
    try:
        pos = reference_urls.index(repo_url.rstrip("/"))
    except ValueError:
        # Try without trailing slash variants
        stripped = [u.rstrip("/") for u in reference_urls]
        try:
            pos = stripped.index(repo_url.rstrip("/"))
        except ValueError:
            pos = -1

    if pos > 0:
        # Find the URL of the card that should come before ours
        predecessor_url = reference_urls[pos - 1]
        parts = re.split(r'(?=<div class="bg-white)', current_html)
        new_parts = []
        inserted = False
        for part in parts:
            new_parts.append(part)
            if not inserted and (predecessor_url in part or predecessor_url.rstrip("/") in part):
                new_parts.append(card_html + "\n")
                inserted = True
        if inserted:
            return "".join(new_parts)

    # Fallback: insert after marker
    if marker in current_html:
        return current_html.replace(marker, f"{marker}\n\n{card_html}\n", 1)
    return current_html


def update_portfolio(state: PortfolioState) -> dict:
    """Read current portfolio HTML files and insert or update the project card in each."""
    g = Github(os.getenv("GITHUB_TOKEN"))
    repo = g.get_repo(state["portfolio_repo"])

    lang_map = {
        "work.html": state["summary_html"],
        "work.es.html": state["summary_html_es"],
        "work.de.html": state["summary_html_de"],
    }

    repo_url = state["repo_info"]["url"]
    original_url = state["repo_info"].get("original_url", "")
    updated_files = []

    # Fetch all files first so we can use EN as position reference
    fetched = {}
    for portfolio_file in PORTFOLIO_FILES:
        f = repo.get_contents(portfolio_file)
        fetched[portfolio_file] = {"html": f.decoded_content.decode("utf-8"), "sha": f.sha}

    # Extract ordered card URLs from EN file as position reference
    en_url_order = _extract_repo_urls(fetched["work.html"]["html"])

    for portfolio_file in PORTFOLIO_FILES:
        current_html = fetched[portfolio_file]["html"]
        card_html = lang_map[portfolio_file]

        # Try canonical URL first; fall back to original URL in case of repo transfer
        updated_html, action = _replace_or_insert(current_html, card_html, repo_url, MARKER)
        if action == "added" and original_url and original_url.rstrip("/") != repo_url.rstrip("/"):
            updated_html2, action2 = _replace_or_insert(current_html, card_html, original_url, MARKER)
            if action2 == "updated":
                updated_html, action = updated_html2, action2

        # If still "added" (genuinely new or missing from this language file),
        # insert at the correct position based on EN order
        if action == "added" and portfolio_file != "work.html":
            updated_html = _insert_at_position(current_html, card_html, repo_url, en_url_order, MARKER)

        if action == "skipped":
            print(
                f"⚠️  Marker '{MARKER}' not found in {portfolio_file} and no existing card detected."
                f"\n   Add <!-- NEW_PROJECTS_HERE --> where you want cards inserted."
                f"\n   Skipping {portfolio_file}."
            )
            continue

        print(f"{'🔄 Updated' if action == 'updated' else '➕ Added'} card in {portfolio_file}")
        updated_files.append({
            "path": portfolio_file,
            "content": updated_html,
            "sha": fetched[portfolio_file]["sha"],
        })

    return {
        "updated_files": updated_files,
        "updated_file": updated_files[0]["content"] if updated_files else "",
        "file_sha": updated_files[0]["sha"] if updated_files else "",
    }
