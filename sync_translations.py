"""
sync_translations.py — Ensure ES/DE portfolio pages have all sections present in EN.

EN (*.html) is the baseline. For each section found in EN that is missing from
*.es.html or *.de.html, this script translates it and lets you review
interactively before committing and opening a PR.

Usage:
    python sync_translations.py

    # Limit to specific pages:
    python sync_translations.py --pages index.html about.html

Environment variables required:
    GITHUB_TOKEN       -- GitHub personal access token
    ANTHROPIC_API_KEY  -- Anthropic API key
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime

from dotenv import load_dotenv
from github import Github, Auth
from langchain_anthropic import ChatAnthropic

load_dotenv()

PORTFOLIO_REPO = "vr33ni/portfolio"
PR_REVIEWER = "vr33ni"
LANGS = ("es", "de")

# Pages that don't need translation (error pages, redirects, etc.)
SKIP_PAGES = {"404.html"}


# ── Section splitting ─────────────────────────────────────────────────────────

def _split_sections(html: str) -> list[str]:
    """Split HTML into independently translatable chunks.

    Uses card-boundary split for work pages, <section>/<article> breaks
    for other pages. sections[0] is always the preamble.
    """
    if '<div class="bg-white' in html:
        return re.split(r'(?=<div class="bg-white)', html)
    parts = re.split(r'(?=<(?:section|article)\b[^>]*>)', html, flags=re.IGNORECASE)
    if len(parts) > 1:
        return parts
    return [html]


def _section_anchor(section: str) -> str | None:
    """Stable identity for a section: first GitHub URL, element id, or heading text."""
    urls = re.findall(r'https://github\.com/[^\s"\'<>]+', section)
    if urls:
        return urls[0].rstrip("/")
    # Prefer the id attribute — language-neutral and stable across translations
    id_match = re.search(r'<(?:section|article|div)[^>]+\bid=["\']([^"\']+)["\']', section, re.IGNORECASE)
    if id_match:
        return id_match.group(1).strip().lower()
    h = re.search(r'<h[1-4][^>]*>(.*?)</h[1-4]>', section, re.DOTALL | re.IGNORECASE)
    if h:
        text = re.sub(r'<[^>]+>', '', h.group(1)).strip().lower()
        if text:
            return text
    return None


def _visible_text(html: str) -> str:
    return re.sub(r'<[^>]+>', '', html).strip()


# ── Translation ───────────────────────────────────────────────────────────────

def _translate(llm: ChatAnthropic, section: str, lang: str) -> str:
    lang_label = {"es": "Spanish", "de": "German"}[lang]
    # Cap section size to avoid oversized requests during API load spikes
    section_trimmed = section[:8000] if len(section) > 8000 else section
    prompt = (
        f'Translate the visible text in the following HTML into {lang_label}.\n\n'
        f'Rules:\n'
        f'- Preserve ALL HTML tags, attributes, class names, href and src values EXACTLY.\n'
        f'- Keep technical terms, tool names, and proper nouns in English '
        f'(e.g. "Python", "FastAPI", "GitHub", "Docker").\n'
        f'- Return only the HTML. No markdown, no backticks, no explanation.\n\n'
        f'{section_trimmed}'
    )
    for attempt in range(6):
        try:
            result = llm.invoke(prompt).content.strip()
            return re.sub(r'^```[a-zA-Z]*\n?', '', result).rstrip('`').strip()
        except Exception as e:
            if "overloaded" in str(e).lower() and attempt < 5:
                wait = 30 * (attempt + 1)
                print(f"  API overloaded, retrying in {wait}s... (attempt {attempt + 1}/5)")
                time.sleep(wait)
            else:
                raise


# ── Per-file sync (interactive) ───────────────────────────────────────────────

def _lang_filename(en_filename: str, lang: str) -> str:
    base, ext = en_filename.rsplit(".", 1)
    return f"{base}.{lang}.{ext}"


def _sync_file(llm: ChatAnthropic, portfolio, en_filename: str, ref: str) -> dict[str, str]:
    """Return {lang_filename: full_updated_html} for files that need changes.
    Prompts interactively for each missing section."""
    try:
        en_html = portfolio.get_contents(en_filename, ref=ref).decoded_content.decode()
    except Exception as e:
        print(f"  Could not read {en_filename}: {e}")
        return {}

    en_sections = _split_sections(en_html)
    en_anchors = {_section_anchor(s): i for i, s in enumerate(en_sections) if _section_anchor(s)}

    updates: dict[str, str] = {}

    for lang in LANGS:
        lang_file = _lang_filename(en_filename, lang)
        lang_label = {"es": "Spanish", "de": "German"}[lang]

        try:
            lang_html = portfolio.get_contents(lang_file, ref=ref).decoded_content.decode()
            lang_sections = _split_sections(lang_html)
            lang_anchors = {_section_anchor(s) for s in lang_sections if _section_anchor(s)}
        except Exception:
            print(f"\n  {lang_file} does not exist yet -- will create it")
            lang_sections = list(en_sections)
            lang_anchors = set()

        missing = [
            (anchor, idx)
            for anchor, idx in en_anchors.items()
            if anchor not in lang_anchors
        ]

        if not missing:
            print(f"  {lang_file} -- in sync, nothing to add")
            continue

        print(f"\n  {lang_file} -- {len(missing)} section(s) missing")

        working = list(lang_sections)
        any_accepted = False

        for anchor, en_idx in missing:
            en_section = en_sections[en_idx]
            print(f"\n    Missing section: {anchor}")

            translated = _translate(llm, en_section, lang)

            sep = "-" * 60
            print(f"\n{sep}")
            print(_visible_text(translated))
            print(sep)

            choice = input(f"    Add to {lang_file}? [y/n/improve] ").strip().lower()

            if choice == "n":
                continue
            if choice == "improve":
                feedback = input("    What to change: ").strip()
                translated = llm.invoke(
                    f'Improve this {lang_label} HTML translation based on the feedback.\n\n'
                    f'Translation:\n{translated}\n\n'
                    f'Feedback: {feedback}\n\n'
                    f'Return only the updated HTML. No markdown, no backticks.'
                ).content.strip()
                translated = re.sub(r'^```[a-zA-Z]*\n?', '', translated).rstrip('`').strip()
                print(f"\n{sep}")
                print(_visible_text(translated))
                print(sep)

            insert_at = min(en_idx, len(working))
            working.insert(insert_at, translated + "\n")
            any_accepted = True

        if any_accepted:
            updates[lang_file] = "".join(working)

    return updates


# ── Commit & PR ───────────────────────────────────────────────────────────────

def _commit_and_pr(portfolio, all_updates: dict[str, str]) -> str | None:
    if not all_updates:
        return None

    default_branch = portfolio.default_branch
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    branch = f"translations/sync-{timestamp}"
    base_sha = portfolio.get_git_ref(f"heads/{default_branch}").object.sha
    portfolio.create_git_ref(ref=f"refs/heads/{branch}", sha=base_sha)

    for filename, new_html in all_updates.items():
        try:
            f = portfolio.get_contents(filename, ref=branch)
            portfolio.update_file(
                path=filename,
                message=f"translations: add missing sections to {filename}",
                content=new_html,
                sha=f.sha,
                branch=branch,
            )
        except Exception:
            portfolio.create_file(
                path=filename,
                message=f"translations: create {filename}",
                content=new_html,
                branch=branch,
            )

    files_list = "\n".join(f"- `{f}`" for f in all_updates)
    pr = portfolio.create_pull(
        title=f"translations: sync missing sections",
        body=(
            f"Adds sections present in EN but missing from translated pages.\n\n"
            f"**Files updated:**\n{files_list}\n\n"
            f"Translations were reviewed interactively before this PR was created."
        ),
        head=branch,
        base=default_branch,
    )
    try:
        pr.create_review_request(reviewers=[PR_REVIEWER])
    except Exception as e:
        print(f"  Could not add reviewer: {e}")

    return pr.html_url


# ── Page discovery ────────────────────────────────────────────────────────────

def _discover_en_pages(portfolio, ref: str) -> list[str]:
    """Return all *.html files in the repo root that have no language suffix."""
    contents = portfolio.get_contents("", ref=ref)
    return [
        f.name for f in contents
        if f.name.endswith(".html")
        and not re.search(r'\.(es|de)\.html$', f.name)
    ]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sync missing sections from EN pages into ES/DE translations."
    )
    parser.add_argument(
        "--pages", nargs="*",
        help="EN pages to check (e.g. work.html index.html). Defaults to all.",
    )
    args = parser.parse_args()

    g = Github(auth=Auth.Token(os.environ["GITHUB_TOKEN"]))
    llm = ChatAnthropic(
        model="claude-haiku-4-5",
        temperature=0,
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )
    portfolio = g.get_repo(PORTFOLIO_REPO)
    ref = portfolio.default_branch

    en_pages = args.pages or _discover_en_pages(portfolio, ref)
    en_pages = [
        p for p in en_pages
        if not re.search(r'\.(es|de)\.html$', p) and p not in SKIP_PAGES
    ]

    if not en_pages:
        print("No EN pages found.")
        sys.exit(0)

    print(f"Checking: {', '.join(en_pages)}\n")

    all_updates: dict[str, str] = {}
    for page in en_pages:
        print(f"\n--- {page} ---")
        updates = _sync_file(llm, portfolio, page, ref)
        all_updates.update(updates)

    if not all_updates:
        print("\nAll translated pages are in sync.")
        return

    print(f"\nOpening PR for: {list(all_updates.keys())}")
    pr_url = _commit_and_pr(portfolio, all_updates)
    print(f"PR: {pr_url}")


if __name__ == "__main__":
    main()
