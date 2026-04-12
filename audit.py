"""
audit.py — Check if existing portfolio project cards are still up to date.

Reads all portfolio HTML files, then for each card:
  - Fixes stale/transferred GitHub links (no LLM)
  - Normalizes Tailwind CSS classes (no LLM)
  - Corrects card order in ES/DE to match EN (no LLM)
  - Updates tech stack subtitle if languages/topics have changed (LLM, one call per card)
  - Rewrites description paragraph + bullets if the README has drifted (LLM, one call per card)

All fixes are applied in one pass and committed as a single PR.

Usage:
    python audit.py
"""

import os
import re
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from github import Github, Auth
from langchain_anthropic import ChatAnthropic
from update_portfolio import _extract_repo_urls, PORTFOLIO_FILES, MARKER
from create_pr import PR_REVIEWER

# ===== CONFIGURE THIS =====
PORTFOLIO_REPO = "vr33ni/portfolio"
PORTFOLIO_FILE = "work.html"
# ==========================

# Pre-compiled pattern for the tech stack subtitle paragraph
TECH_P = re.compile(r'<p class="text-sm text-gray-500[^"]*"[^>]*>\s*(.*?)\s*</p>', re.DOTALL)


def _card_to_text(card_html: str) -> str:
    """Extract readable description text (paragraph + bullets) from a card for console display."""
    lines = []
    p_match = re.search(r'<p class="mb-4"[^>]*>(.*?)</p>', card_html, re.DOTALL)
    if p_match:
        lines.append(re.sub(r'<[^>]+>', '', p_match.group(1)).strip())
    for li in re.findall(r'<li[^>]*>(.*?)</li>', card_html, re.DOTALL):
        lines.append('  • ' + re.sub(r'<[^>]+>', '', li).strip())
    return '\n'.join(lines) or card_html


# ── Utility ─────────────────────────────────────────────────────────────────

def extract_repo_links(html: str) -> list[str]:
    """Extract unique GitHub repo paths (owner/name) from portfolio HTML."""
    all_links = re.findall(r'https://github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+', html)
    seen = set()
    repos = []
    for link in all_links:
        parts = link.rstrip("/").split("/")
        if len(parts) == 5 and not parts[4].endswith(".github.io"):
            repo_path = f"{parts[3]}/{parts[4]}"
            if repo_path not in seen:
                seen.add(repo_path)
                repos.append(repo_path)
    return repos


# ── Session open / close ─────────────────────────────────────────────────────

def _open_fix_session(g: Github):
    """Fetch all portfolio files and find open audit PR.
    Returns (portfolio, fetched, read_ref, open_audit_pr).
    fetched maps filename → {"html": str, "sha": str}."""
    portfolio = g.get_repo(PORTFOLIO_REPO)
    open_audit_pr = None
    read_ref = portfolio.default_branch
    for pr in portfolio.get_pulls(state="open"):
        if pr.head.ref.startswith("audit/"):
            open_audit_pr = pr
            read_ref = pr.head.ref
            print(f"ℹ️  Using open audit PR branch: {read_ref}\n")
            break
    fetched = {}
    for filename in PORTFOLIO_FILES:
        f = portfolio.get_contents(filename, ref=read_ref)
        fetched[filename] = {"html": f.decoded_content.decode("utf-8"), "sha": f.sha}
    return portfolio, fetched, read_ref, open_audit_pr


def _close_fix_session(portfolio, fetched: dict, changed_files: list, read_ref: str,
                       open_audit_pr, branch_prefix: str, commit_msg: str,
                       pr_title: str, pr_body: str):
    """Commit changed files to an audit branch and open or update a PR."""
    if not changed_files:
        return None

    default_branch = portfolio.default_branch
    if open_audit_pr:
        branch = read_ref
    else:
        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        branch = f"audit/{branch_prefix}-{timestamp}"
        base_sha = portfolio.get_git_ref(f"heads/{default_branch}").object.sha
        portfolio.create_git_ref(ref=f"refs/heads/{branch}", sha=base_sha)

    for filename in changed_files:
        f = portfolio.get_contents(filename, ref=branch)
        portfolio.update_file(
            path=filename,
            message=commit_msg,
            content=fetched[filename]["html"],
            sha=f.sha,
            branch=branch,
        )

    if open_audit_pr:
        open_audit_pr.edit(title=pr_title, body=pr_body)
        return open_audit_pr.html_url

    pr = portfolio.create_pull(
        title=pr_title,
        body=pr_body,
        head=branch,
        base=default_branch,
    )
    try:
        pr.create_review_request(reviewers=[PR_REVIEWER])
    except Exception as e:
        print(f"⚠️  Could not add reviewer: {e}")
    return pr.html_url


# ── Per-aspect fix helpers (modify fetched in-place) ────────────────────────

def _fix_links_inplace(g: Github, fetched: dict) -> list[str]:
    """Replace transferred/stale GitHub repo URLs. Returns list of changed filenames."""
    repo_paths = extract_repo_links(fetched["work.html"]["html"])
    changed = []
    for repo_path in repo_paths:
        original_url = f"https://github.com/{repo_path}"
        try:
            repo = g.get_repo(repo_path)
            canonical_url = repo.html_url.rstrip("/")
        except Exception:
            continue
        if original_url.rstrip("/") == canonical_url:
            continue
        print(f"    🔗 {original_url} → {canonical_url}")
        for filename in PORTFOLIO_FILES:
            old = fetched[filename]["html"]
            new = old.replace(original_url + "/", canonical_url + "/").replace(original_url, canonical_url)
            if new != old:
                fetched[filename]["html"] = new
                if filename not in changed:
                    changed.append(filename)
    if not changed:
        print("    ✅ All links are current")
    return changed


def _fix_styling_inplace(fetched: dict) -> list[str]:
    """Normalize Tailwind CSS classes to match the card template. Returns changed filenames."""
    PATCHES = [
        (re.compile(r'<div class="bg-white[^"]*"'),
         '<div class="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6"'),
        (re.compile(r'<h2 class="[^"]*"'),
         '<h2 class="text-xl font-semibold mb-2"'),
        (re.compile(r'<p class="text-sm text-gray-[^"]*"'),
         '<p class="text-sm text-gray-500 dark:text-gray-400 mb-2"'),
        (re.compile(r'<ul class="[^"]*"'),
         '<ul class="list-disc list-inside text-sm mb-4 space-y-1"'),
    ]
    changed = []
    for filename in PORTFOLIO_FILES:
        old = fetched[filename]["html"]
        # Apply patches only within card chunks, not the whole file
        chunks = re.split(r'(?=<div class="bg-white)', old)
        new_chunks = [chunks[0]]  # preamble untouched
        for chunk in chunks[1:]:
            patched = chunk
            for pattern, replacement in PATCHES:
                patched = pattern.sub(replacement, patched)
            new_chunks.append(patched)
        new = "".join(new_chunks)
        if new != old:
            fetched[filename]["html"] = new
            changed.append(filename)
            print(f"    🎨 Styling fixed in {filename}")
    if not changed:
        print("    ✅ Styling is consistent")
    return changed


def _fix_order_inplace(fetched: dict) -> list[str]:
    """Reorder cards in ES/DE to match EN. Returns list of changed filenames."""
    en_html = fetched["work.html"]["html"]
    en_parts = re.split(r'(?=<div class="bg-white)', en_html)
    en_order = []
    for chunk in en_parts:
        urls = re.findall(r'href="(https://github\.com/[^"]+)"', chunk)
        for u in urls:
            if len(u.rstrip("/").split("/")) == 5:
                en_order.append((u.rstrip("/"), chunk))
                break

    changed = []
    for filename in ["work.es.html", "work.de.html"]:
        html = fetched[filename]["html"]
        card_split = re.split(r'(?=<div class="bg-white)', html)
        preamble = card_split[0]
        chunks = card_split[1:]

        chunk_by_url = {}
        for chunk in chunks:
            urls = re.findall(r'href="(https://github\.com/[^"]+)"', chunk)
            for u in urls:
                if len(u.rstrip("/").split("/")) == 5:
                    chunk_by_url[u.rstrip("/")] = chunk
                    break

        reordered = [preamble]
        for en_url, _ in en_order:
            chunk = chunk_by_url.get(en_url)
            if chunk is None:
                en_name = en_url.split("/")[-1]
                for k, v in chunk_by_url.items():
                    if k.split("/")[-1] == en_name:
                        chunk = v
                        break
            if chunk:
                reordered.append(chunk)

        matched_names = {en_url.split("/")[-1] for en_url, _ in en_order}
        for u, chunk in chunk_by_url.items():
            if u.split("/")[-1] not in matched_names:
                reordered.append(chunk)

        new_html = "".join(reordered)
        if new_html != html:
            fetched[filename]["html"] = new_html
            changed.append(filename)
            print(f"    🔀 Reordered {filename}")
        else:
            print(f"    ✅ {filename} already in correct order")
    return changed


def _fix_card_content_inplace(g: Github, llm: ChatAnthropic, fetched: dict) -> list[str]:
    """Check tech stack and description per card. Prints one FRESH/STALE per card.
    Only prompts for review on STALE cards. Returns list of changed filenames."""
    en_html = fetched["work.html"]["html"]
    repo_paths = extract_repo_links(en_html)
    changed = []

    for repo_path in repo_paths:
        try:
            repo = g.get_repo(repo_path)
            languages = list(repo.get_languages().keys())
            topics = repo.get_topics()
            try:
                readme = repo.get_readme().decoded_content.decode("utf-8")
            except Exception:
                readme = ""
        except Exception:
            print(f"    ⚠️  Could not fetch {repo_path} — skipping")
            continue

        card_url = repo.html_url
        en_parts = re.split(r'(?=<div class="bg-white)', en_html)
        en_card = next((p for p in en_parts if card_url in p or card_url.rstrip("/") in p), None)
        if not en_card:
            continue

        # ── Tech stack verdict ───────────────────────────────────────────
        new_tech = None
        tech_match = TECH_P.search(en_card)
        current_tech = tech_match.group(1).strip() if tech_match else None
        if current_tech:
            tech_verdict = llm.invoke(
                f'Portfolio card for "{repo.name}" has tech stack line: {current_tech}\n'
                f'GitHub reports for THIS repo — Languages: {", ".join(languages)}, Topics: {", ".join(topics)}\n\n'
                f'The card may intentionally cover a full-stack project that spans multiple repos or includes '
                f'backend services, databases, deployment tools, or other infrastructure not reflected in this '
                f'repo\'s language stats.\n\n'
                f'Rules:\n'
                f'- Only suggest a change if the current line contains something genuinely wrong or if a key '
                f'technology from GitHub\'s data is clearly missing.\n'
                f'- Do NOT remove technologies just because they don\'t appear in this repo\'s language stats.\n'
                f'- If the line looks reasonable given the card context, reply KEEP.\n'
                f'- If a change is needed, reply with the corrected string only '
                f'(format: "Tech · Stack · Here", 3-5 most important technologies, keep technical names in English).'
            ).content.strip()
            if not tech_verdict.upper().startswith("KEEP"):
                new_tech = tech_verdict

        # ── Description verdict ──────────────────────────────────────────
        needs_desc = False
        if readme:
            desc_verdict = llm.invoke(
                f'Portfolio card for "{repo.name}":\n{en_card}\n\n'
                f'README (first 1500 chars):\n{readme[:1500]}\n\n'
                f'Does the card description contradict or omit something that is factually present in the README?\n\n'
                f'Rules:\n'
                f'- Reply KEEP unless the README shows the codebase has genuinely changed in a way that '
                f'makes the card description factually wrong (e.g. a described feature was removed, the '
                f'core purpose changed, or a key new capability is completely absent from the card).\n'
                f'- Wording differences, missing minor details, or stylistic improvements are NOT a reason to update.\n'
                f'- If the README broadly matches what the card says, reply KEEP.\n'
                f'- Default to KEEP when in doubt.\n'
                f'Reply with just KEEP or UPDATE.'
            ).content.strip().upper()
            needs_desc = not desc_verdict.startswith("KEEP")

        # ── Print one status line per card ───────────────────────────────
        if new_tech is None and not needs_desc:
            print(f"    FRESH  {repo.name}")
            continue

        print(f"    STALE  {repo.name}")

        # ── Review tech stack ────────────────────────────────────────────
        if new_tech is not None:
            print(f"       Tech stack:")
            print(f"         Current:  {current_tech}")
            print(f"         Proposed: {new_tech}")
            choice = input("         Accept? [y/n/edit] ").strip().lower()
            if choice == "n":
                new_tech = None
            elif choice == "edit":
                edited = input("         Enter your version: ").strip()
                new_tech = edited if edited else None

        if new_tech is not None:
            for filename in PORTFOLIO_FILES:
                old = fetched[filename]["html"]
                file_parts = re.split(r'(?=<div class="bg-white)', old)
                new_parts = []
                for part in file_parts:
                    if card_url in part or card_url.rstrip("/") in part:
                        new_parts.append(TECH_P.sub(
                            lambda m, t=new_tech: m.group(0).replace(m.group(1), t),
                            part, count=1,
                        ))
                    else:
                        new_parts.append(part)
                new = "".join(new_parts)
                if new != old:
                    fetched[filename]["html"] = new
                    if filename not in changed:
                        changed.append(filename)

        # ── Review description ───────────────────────────────────────────
        if needs_desc:
            en_file_parts = re.split(r'(?=<div class="bg-white)', fetched["work.html"]["html"])
            en_card_idx = next(
                (i for i, p in enumerate(en_file_parts) if card_url in p or card_url.rstrip("/") in p),
                None,
            )
            if en_card_idx is None:
                continue
            en_new_card = llm.invoke(
                f'Rewrite ONLY the description paragraph and bullet list for this portfolio card.\n\n'
                f'Current card:\n{en_file_parts[en_card_idx]}\n\n'
                f'README (first 1500 chars):\n{readme[:1500]}\n\n'
                f'Rules:\n'
                f'- Keep the project name heading, tech subtitle, and GitHub link EXACTLY as-is.\n'
                f'- Replace only the <p class="mb-4">...</p> and <ul ...>...</ul> sections.\n'
                f'- Write in English.\n'
                f'- Return the FULL card HTML. No markdown, no backticks, no explanation.'
            ).content.strip()

            sep = "─" * 60
            print(f"       Description:")
            print(f"\n{sep}")
            print(_card_to_text(en_new_card))
            print(sep)
            choice = input("         Accept? [y/n/improve] ").strip().lower()
            if choice == "n":
                en_new_card = None
            elif choice == "improve":
                feedback = input("         What to change: ").strip()
                en_new_card = llm.invoke(
                    f'Improve this portfolio card based on the user\'s feedback.\n\n'
                    f'Card:\n{en_new_card}\n\n'
                    f'Feedback: {feedback}\n\n'
                    f'Return the FULL updated card HTML only. No markdown, no backticks.'
                ).content.strip()
                print(f"\n{sep}")
                print(_card_to_text(en_new_card))
                print(sep)

            if en_new_card is not None:
                en_file_parts[en_card_idx] = en_new_card + "\n"
                new_en = "".join(en_file_parts)
                if new_en != fetched["work.html"]["html"]:
                    fetched["work.html"]["html"] = new_en
                    if "work.html" not in changed:
                        changed.append("work.html")

                for _lang, filename, lang_instruction in [
                    ("es", "work.es.html", "Write in Spanish. Keep technical terms in English."),
                    ("de", "work.de.html", "Write in German. Keep technical terms in English."),
                ]:
                    old = fetched[filename]["html"]
                    file_parts = re.split(r'(?=<div class="bg-white)', old)
                    card_idx = next(
                        (i for i, p in enumerate(file_parts) if card_url in p or card_url.rstrip("/") in p),
                        None,
                    )
                    if card_idx is None:
                        continue
                    new_card = llm.invoke(
                        f'Rewrite ONLY the description paragraph and bullet list for this portfolio card.\n\n'
                        f'Current card:\n{file_parts[card_idx]}\n\n'
                        f'README (first 1500 chars):\n{readme[:1500]}\n\n'
                        f'Rules:\n'
                        f'- Keep the project name heading, tech subtitle, and GitHub link EXACTLY as-is.\n'
                        f'- Replace only the <p class="mb-4">...</p> and <ul ...>...</ul> sections.\n'
                        f'- {lang_instruction}\n'
                        f'- Return the FULL card HTML. No markdown, no backticks, no explanation.'
                    ).content.strip()
                    file_parts[card_idx] = new_card + "\n"
                    new = "".join(file_parts)
                    if new != old:
                        fetched[filename]["html"] = new
                        if filename not in changed:
                            changed.append(filename)

    return changed


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    g = Github(auth=Auth.Token(os.getenv("GITHUB_TOKEN")))
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        temperature=0,
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )

    portfolio, fetched, read_ref, open_audit_pr = _open_fix_session(g)
    all_changed = set()

    print("🔗 Checking links...")
    all_changed.update(_fix_links_inplace(g, fetched))

    print("\n🎨 Checking styling...")
    all_changed.update(_fix_styling_inplace(fetched))

    print("\n🔀 Checking card order...")
    all_changed.update(_fix_order_inplace(fetched))

    print("\n⚙️  Checking card content (tech stack + description)...")
    all_changed.update(_fix_card_content_inplace(g, llm, fetched))

    if not all_changed:
        print("\n✅ All cards are up to date. Nothing to commit.")
        return

    changed_list = sorted(all_changed)
    print(f"\n{len(changed_list)} file(s) updated: {', '.join(changed_list)}")
    confirm = input("Push changes to PR? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    pr_url = _close_fix_session(
        portfolio=portfolio,
        fetched=fetched,
        changed_files=changed_list,
        read_ref=read_ref,
        open_audit_pr=open_audit_pr,
        branch_prefix="update-cards",
        commit_msg=(
            "chore: audit pass — update stale portfolio cards\n\n"
            "- fix stale/transferred GitHub links\n"
            "- normalize Tailwind CSS classes within cards\n"
            "- reorder ES/DE cards to match EN\n"
            "- update tech stack subtitles where languages/topics changed\n"
            "- refresh description paragraphs where README has drifted"
        ),
        pr_title="Update portfolio cards",
        pr_body=(
            "Automated audit pass — applied the following fixes as needed:\n\n"
            "- Corrected transferred/stale repo URLs\n"
            "- Normalized Tailwind CSS class strings\n"
            "- Reordered ES/DE cards to match EN\n"
            "- Updated tech stack subtitles\n"
            "- Refreshed description paragraphs and bullets"
        ),
    )
    print(f"\n✅ PR: {pr_url}")


if __name__ == "__main__":
    main()
