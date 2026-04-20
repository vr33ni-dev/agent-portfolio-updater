"""
audit.py — Interactive three-phase portfolio audit.

Phase 1 — English Baseline & Repo Check:
  - Fixes stale/transferred GitHub links (no LLM)
  - Updates tech stack subtitle + description if repos have changed (LLM)

Phase 2 — HTML Structure Consistency:
  - Normalizes Tailwind CSS classes across all language files (no LLM)
  - Corrects card order in ES/DE to match EN (no LLM)
  - Detects HTML elements present in EN cards but missing from translations (no LLM)
  - Removes blocks that are commented-out in EN but present in translations (no LLM)

Phase 3 — Translation Content Review:
  - Detects sections missing from ES/DE translations and offers to add them (LLM)

All phases are interactive: each issue can be accepted, rejected, improved, or skipped.
At the end, all accumulated changes are committed as a single PR.

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
from read_repo import _fetch_code_context, _fetch_subdir_readmes

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


def _card_repo_paths(chunk: str) -> list[str]:
    """Return list of 'owner/name' repo paths found in a card chunk."""
    return extract_repo_links(chunk)


def _card_label(chunk: str) -> str:
    """Extract the card title from the <h2> tag, falling back to first repo name."""
    m = re.search(r'<h2[^>]*>(.*?)</h2>', chunk, re.DOTALL)
    if m:
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()
    urls = re.findall(r'https://github\.com/[a-zA-Z0-9_.-]+/([a-zA-Z0-9_.-]+)', chunk)
    return urls[0] if urls else "card"


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
        if "review cannot be requested from pull request author" not in str(e).lower():
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
    """Check tech stack and description per card (not per repo).
    A card may link to multiple repos (e.g. frontend + backend) — all are fetched and
    their data is aggregated before running verdicts.
    Prints one FRESH/STALE line per card. Returns list of changed filenames."""
    en_html = fetched["work.html"]["html"]
    en_parts = re.split(r'(?=<div class="bg-white)', en_html)
    changed = []

    for en_card in en_parts:
        card_paths = _card_repo_paths(en_card)
        if not card_paths:
            continue

        label = _card_label(en_card)

        # ── Fetch all repos linked from this card (in parallel) ────────────
        def _fetch_one(repo_path):
            try:
                repo = g.get_repo(repo_path)
                languages = list(repo.get_languages().keys())
                topics = repo.get_topics()
                repo_description = repo.description or ""
                try:
                    readme = repo.get_readme().decoded_content.decode("utf-8")
                except Exception:
                    readme = ""
                subdir_readmes = _fetch_subdir_readmes(repo)
                code_context = _fetch_code_context(repo)
                return {
                    "repo": repo,
                    "languages": languages,
                    "topics": topics,
                    "repo_description": repo_description,
                    "readme": readme,
                    "subdir_readmes": subdir_readmes,
                    "code_context": code_context,
                }
            except Exception:
                print(f"    ⚠️  Could not fetch {repo_path} — skipping")
                return None

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor() as executor:
            repos_data = [r for r in executor.map(_fetch_one, card_paths) if r is not None]

        if not repos_data:
            continue

        # ── Aggregate context across all repos ───────────────────────────
        all_languages = []
        all_topics = []
        readme_parts = []
        code_parts = []
        for rd in repos_data:
            all_languages.extend(rd["languages"])
            all_topics.extend(rd["topics"])
            if rd["readme"]:
                readme_parts.append(f"[{rd['repo'].name}]\n{rd['readme'][:1500]}")
            if rd["subdir_readmes"]:
                readme_parts.append(f"[{rd['repo'].name} subdir READMEs]\n{rd['subdir_readmes'][:500]}")
            if rd["code_context"]:
                code_parts.append(f"[{rd['repo'].name}]\n{rd['code_context'][:800]}")

        languages_str = ", ".join(dict.fromkeys(all_languages))
        topics_str = ", ".join(dict.fromkeys(all_topics))
        readme_str = "\n\n".join(readme_parts)
        code_str = "\n\n".join(code_parts)
        repo_desc_str = "; ".join(
            rd["repo_description"] for rd in repos_data if rd["repo_description"]
        )

        # canonical URLs for matching chunks across all three HTML files
        card_urls = [rd["repo"].html_url.rstrip("/") for rd in repos_data]

        # ── Tech stack verdict ───────────────────────────────────────────
        new_tech = None
        tech_match = TECH_P.search(en_card)
        current_tech = tech_match.group(1).strip() if tech_match else None
        if current_tech:
            tech_verdict = llm.invoke(
                f'Portfolio card "{label}" has tech stack line: {current_tech}\n\n'
                f'GitHub data across all linked repos:\n'
                f'  Languages: {languages_str}\n'
                f'  Topics: {topics_str}\n'
                f'  Descriptions: {repo_desc_str}\n\n'
                f'Code context:\n{code_str[:2000]}\n\n'
                f'This card may cover a full-stack project spanning multiple repos '
                f'(e.g. a Vue.js frontend repo + a Spring Boot backend repo).\n\n'
                f'Rules:\n'
                f'- Only suggest a change if the current line is genuinely wrong or a key '
                f'technology visible in the repos is clearly missing.\n'
                f'- Do NOT remove technologies just because they are absent from one repo\'s language stats.\n'
                f'- If the line looks reasonable, reply KEEP.\n'
                f'- If a change is needed, reply with the corrected string only '
                f'(format: "Tech · Stack · Here", 3-5 most important technologies, '
                f'keep technical names in English).'
            ).content.strip()
            if not tech_verdict.upper().startswith("KEEP"):
                new_tech = tech_verdict

        # ── Description verdict ──────────────────────────────────────────
        needs_desc = False
        if readme_str:
            desc_verdict = llm.invoke(
                f'Portfolio card "{label}":\n{en_card}\n\n'
                f'GitHub repo descriptions: {repo_desc_str}\n\n'
                f'READMEs:\n{readme_str[:3000]}\n\n'
                f'Code context:\n{code_str[:2000]}\n\n'
                f'Compare the card description against all of the above. Reply UPDATE if either:\n'
                f'  (a) The card says something factually incorrect or contradictory '
                f'(e.g. wrong framework, wrong language), OR\n'
                f'  (b) The project has changed significantly and the card no longer reflects it.\n\n'
                f'Reply KEEP if:\n'
                f'  - The card is broadly accurate and consistent with the repos.\n'
                f'  - Differences are only in wording, level of detail, or style.\n'
                f'- Default to KEEP when in doubt.\n'
                f'Reply with just KEEP or UPDATE.'
            ).content.strip().upper()
            needs_desc = not desc_verdict.startswith("KEEP")

        # ── Print one status line per card ───────────────────────────────
        if new_tech is None and not needs_desc:
            print(f"    FRESH  {label}")
            continue

        print(f"    STALE  {label}")

        _orig_new_tech = new_tech  # preserve original LLM proposal for back navigation

        # ── Card-level loop: supports back from description → tech stack ─────
        accepted_tech = None
        accepted_desc = None

        _restart = True
        while _restart:
            _restart = False
            accepted_tech = None
            _review_tech = _orig_new_tech

            # ── Review tech stack ────────────────────────────────────────────
            if _review_tech is not None:
                while True:
                    print(f"       Tech stack:")
                    print(f"         Current:  {current_tech}")
                    print(f"         Proposed: {_review_tech}")
                    choice = input("         Accept? [y/n/edit/back] ").strip().lower()
                    if choice in ("n", "back"):
                        _review_tech = None
                        break
                    elif choice == "edit":
                        feedback = input("         What to change: ").strip()
                        if feedback:
                            raw = llm.invoke(
                                f'You proposed this tech stack for a portfolio card: "{_review_tech}"\n\n'
                                f'The user provided this feedback: {feedback}\n\n'
                                f'GitHub data:\n'
                                f'  Languages: {languages_str}\n'
                                f'  Topics: {topics_str}\n\n'
                                f'Return only the revised tech stack string in the format '
                                f'"Tech · Stack · Here" (3-5 items, technical names in English). '
                                f'No explanation, no markdown, no HTML.'
                            ).content.strip()
                            _review_tech = raw if '<' not in raw else _review_tech
                        continue
                    else:
                        accepted_tech = _review_tech
                        break

            # ── Review description ───────────────────────────────────────────
            if needs_desc:
                en_file_parts = re.split(r'(?=<div class="bg-white)', fetched["work.html"]["html"])
                en_card_idx = next(
                    (i for i, p in enumerate(en_file_parts) if any(u in p for u in card_urls)),
                    None,
                )
                if en_card_idx is None:
                    break

                def _generate_desc(card_chunk, feedback_hint=""):
                    extra = f'\nFeedback to address: {feedback_hint}\n' if feedback_hint else ''
                    return llm.invoke(
                        f'Rewrite ONLY the description paragraph and bullet list for this portfolio card.\n\n'
                        f'Current card:\n{card_chunk}\n\n'
                        f'READMEs:\n{readme_str[:2500]}\n\n'
                        f'Code context:\n{code_str[:1500]}\n\n'
                        f'Rules:\n'
                        f'- Keep the project name heading, tech subtitle, and GitHub link(s) EXACTLY as-is.\n'
                        f'- Replace only the <p class="mb-4">...</p> and <ul ...>...</ul> sections.\n'
                        f'- Description: 2-3 sentences. Bullets: 2-3 items.\n'
                        f'- Write in English.\n'
                        f'- Return the FULL card HTML. No markdown, no backticks, no explanation.'
                        f'{extra}'
                    ).content.strip()

                def _critique_desc(card_chunk):
                    response = llm.invoke(
                        f'You are reviewing a rewritten portfolio project card.\n\n'
                        f'Evaluate against these criteria:\n'
                        f'1. Accuracy — correctly reflects the repo(s) purpose and tech stack\n'
                        f'2. Length — description 2-3 sentences, 2-3 bullet points (not more)\n'
                        f'3. No raw README copy — must be a concise portfolio write-up\n'
                        f'4. Structure — uses correct Tailwind CSS classes\n\n'
                        f'READMEs:\n{readme_str[:2000]}\n\n'
                        f'Code context:\n{code_str[:1000]}\n\n'
                        f'CARD:\n{card_chunk}\n\n'
                        f'Respond with exactly two lines:\n'
                        f'Line 1: APPROVED or REJECTED\n'
                        f'Line 2: If REJECTED, one concise sentence of specific feedback. '
                        f'If APPROVED, write "Looks good."'
                    ).content.strip()
                    lines = response.splitlines()
                    verdict = lines[0].strip().upper()
                    feedback_msg = lines[1].strip() if len(lines) > 1 else ""
                    return verdict, feedback_msg

                en_new_card = _generate_desc(en_file_parts[en_card_idx])
                for _attempt in range(3):
                    verdict, critique_fb = _critique_desc(en_new_card)
                    if verdict == "APPROVED":
                        print(f"       ✅ Critique approved (attempt {_attempt + 1})")
                        break
                    print(f"       🔁 Critique retry {_attempt + 1}/3: {critique_fb}")
                    en_new_card = _generate_desc(en_file_parts[en_card_idx], feedback_hint=critique_fb)

                sep = "─" * 60
                print(f"       Description:")
                back_opt = "/back" if _orig_new_tech is not None else ""
                print(f"\n{sep}")
                print(_card_to_text(en_new_card))
                print(sep)
                while True:
                    choice = input(f"         Accept? [y/n/improve{back_opt}] ").strip().lower()
                    if choice == "back" and _orig_new_tech is not None:
                        _restart = True
                        break
                    elif choice == "n":
                        en_new_card = None
                        break
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
                        continue
                    else:
                        accepted_desc = en_new_card
                        break

                if _restart:
                    continue  # restart card loop from tech stack

        # ── Apply accepted changes ────────────────────────────────────────────
        if accepted_tech is not None:
            for filename in PORTFOLIO_FILES:
                old = fetched[filename]["html"]
                file_parts = re.split(r'(?=<div class="bg-white)', old)
                new_parts = []
                for part in file_parts:
                    if any(u in part for u in card_urls):
                        new_parts.append(TECH_P.sub(
                            lambda m, t=accepted_tech: m.group(0).replace(m.group(1), t),
                            part, count=1,
                        ))
                    else:
                        new_parts.append(part)
                new = "".join(new_parts)
                if new != old:
                    fetched[filename]["html"] = new
                    if filename not in changed:
                        changed.append(filename)

        if accepted_desc is not None:
            en_file_parts = re.split(r'(?=<div class="bg-white)', fetched["work.html"]["html"])
            en_card_idx = next(
                (i for i, p in enumerate(en_file_parts) if any(u in p for u in card_urls)),
                None,
            )
            if en_card_idx is not None:
                en_file_parts[en_card_idx] = accepted_desc + "\n"
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
                        (i for i, p in enumerate(file_parts) if any(u in p for u in card_urls)),
                        None,
                    )
                    if card_idx is None:
                        continue
                    new_card = llm.invoke(
                        f'Rewrite ONLY the description paragraph and bullet list for this portfolio card.\n\n'
                        f'Current card:\n{file_parts[card_idx]}\n\n'
                        f'READMEs:\n{readme_str[:2500]}\n\n'
                        f'Rules:\n'
                        f'- Keep the project name heading, tech subtitle, and GitHub link(s) EXACTLY as-is.\n'
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


# ── Commented-block drift check ──────────────────────────────────────────────

def _element_bounds(html: str, fingerprint: str) -> tuple[int, int] | None:
    """Return (start, end) of the outermost HTML element containing fingerprint."""
    idx = html.find(fingerprint)
    if idx == -1:
        return None
    # Walk backwards to the nearest non-closing, non-comment opening tag
    tag_start = idx
    while tag_start > 0:
        tag_start = html.rfind('<', 0, tag_start)
        if tag_start < 0:
            return None
        snippet = html[tag_start:]
        if not snippet.startswith('</') and not snippet.startswith('<!--'):
            break
    tag_match = re.match(r'<(\w+)', html[tag_start:])
    if not tag_match:
        return None
    tag_name = tag_match.group(1)
    close = f'</{tag_name}>'
    open_pat = re.compile(f'<{tag_name}[\\s>]')
    depth = 1
    pos = html.find('>', tag_start) + 1
    while depth > 0 and pos < len(html):
        next_close = html.find(close, pos)
        m = open_pat.search(html, pos)
        next_open = m.start() if m else -1
        if next_close == -1:
            return None
        if next_open != -1 and next_open < next_close:
            tag_end = html.find('>', next_open)
            if tag_end > 0 and html[tag_end - 1] != '/':
                depth += 1
            pos = next_open + 1
        else:
            depth -= 1
            pos = next_close + len(close)
    return tag_start, pos


def _fix_structure_inplace(fetched: dict) -> list[str]:
    """Detect HTML elements present in active EN cards but absent from matching translated cards.
    HTML comments are stripped before comparison so commented-out EN content is ignored.
    For <a> tags, missing links are identified by href.
    For other structural tags, count differences are resolved by copying positional extras from EN.
    Copies missing elements verbatim before the card's closing </div>.
    Returns list of changed filenames."""
    en_html = fetched["work.html"]["html"]
    en_parts = re.split(r'(?=<div class="bg-white)', en_html)
    changed = []

    _TAGS = ("h2", "h3", "p", "ul", "a")

    for en_card in en_parts:
        card_urls = [
            u.rstrip("/")
            for u in re.findall(r'href="(https://github\.com/[^"]+)"', en_card)
            if len(u.rstrip("/").split("/")) == 5
        ]
        if not card_urls:
            continue

        label = _card_label(en_card)
        en_active = re.sub(r'<!--.*?-->', '', en_card, flags=re.DOTALL)

        for filename in ("work.es.html", "work.de.html"):
            lang_html = fetched[filename]["html"]
            lang_parts = re.split(r'(?=<div class="bg-white)', lang_html)
            card_idx = next(
                (i for i, p in enumerate(lang_parts) if any(u in p for u in card_urls)),
                None,
            )
            if card_idx is None:
                continue

            lang_card = lang_parts[card_idx]
            lang_active = re.sub(r'<!--.*?-->', '', lang_card, flags=re.DOTALL)

            # Collect the exact elements to be copied per tag
            pending: list[tuple[str, str]] = []  # (tag, element_html)
            for tag in _TAGS:
                en_count = len(re.findall(rf'<{tag}[\s>]', en_active, re.IGNORECASE))
                lang_count = len(re.findall(rf'<{tag}[\s>]', lang_active, re.IGNORECASE))
                if en_count <= lang_count:
                    continue
                if tag == "a":
                    en_hrefs = re.findall(r'<a[^>]+href="([^"]+)"', en_active, re.IGNORECASE)
                    lang_hrefs = set(re.findall(r'<a[^>]+href="([^"]+)"', lang_active, re.IGNORECASE))
                    for href in en_hrefs:
                        if href in lang_hrefs:
                            continue
                        m = re.search(
                            rf'(<a[^>]+{re.escape(href)}[^>]*>.*?</a>)',
                            en_active, re.DOTALL | re.IGNORECASE,
                        )
                        if m:
                            pending.append((tag, m.group(1)))
                else:
                    en_els = re.findall(
                        rf'(<{tag}[\s>].*?</{tag}>)', en_active, re.DOTALL | re.IGNORECASE,
                    )
                    for extra in en_els[lang_count:]:
                        pending.append((tag, extra))

            if not pending:
                continue

            # Show what will be copied before asking
            print(f"    ⚠️  {filename} | {label}: EN has {len(pending)} extra element(s):")
            for tag, el_html in pending:
                text = re.sub(r'<[^>]+>', ' ', el_html)
                text = re.sub(r'\s+', ' ', text).strip()
                if tag == "a":
                    _href_m = re.search(r'href="([^"]+)"', el_html)
                    href = _href_m.group(1) if _href_m else ""
                    preview = f"<a>  {text}  →  {href}"
                elif tag == "ul":
                    items = re.findall(r'<li[^>]*>(.*?)</li>', el_html, re.DOTALL | re.IGNORECASE)
                    item_texts = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', i)).strip() for i in items]
                    preview = f"<ul> {' / '.join(item_texts)}"
                else:
                    preview = f"<{tag}> {text[:120]}"
                print(f"         {preview}")
            choice = input("         Copy these into translation? [y/n] ").strip().lower()
            if choice != "y":
                continue

            new_lang_card = lang_card
            for tag, el_html in pending:
                new_lang_card = _insert_before_card_close(new_lang_card, el_html)

            if new_lang_card != lang_card:
                lang_parts[card_idx] = new_lang_card
                fetched[filename]["html"] = "".join(lang_parts)
                if filename not in changed:
                    changed.append(filename)
                print(f"       ✅ Copied into {filename}")

    if not changed:
        print("    ✅ Element structure matches EN")
    return changed


def _insert_before_card_close(card_html: str, element: str) -> str:
    """Insert element HTML before the last </div> in a card chunk."""
    close = "</div>"
    idx = card_html.rfind(close)
    if idx == -1:
        return card_html + "\n  " + element
    return card_html[:idx] + "  " + element + "\n" + card_html[idx:]


# ── Commented-block drift check ──────────────────────────────────────────────

def _fix_commented_blocks_inplace(portfolio, fetched: dict, read_ref: str) -> list[str]:
    """Find blocks that are commented-out in EN but uncommented in translations.
    Offers to remove them. Returns list of changed filenames."""
    try:
        repo_root = portfolio.get_contents("", ref=read_ref)
        all_en_pages = [
            f.name for f in repo_root
            if f.name.endswith(".html")
            and not re.search(r'\.(es|de)\.html$', f.name)
            and f.name not in {"404.html"}
        ]
    except Exception as e:
        print(f"  ⚠️  Could not list repo contents: {e}")
        return []

    changed = []

    for en_filename in all_en_pages:
        if en_filename in fetched:
            en_html = fetched[en_filename]["html"]
        else:
            try:
                f = portfolio.get_contents(en_filename, ref=read_ref)
                en_html = f.decoded_content.decode()
            except Exception:
                continue

        # Find HTML comment blocks that contain actual markup (>100 non-whitespace chars)
        comment_blocks = re.findall(r'<!--(.*?)-->', en_html, re.DOTALL)
        significant = [c for c in comment_blocks if len(c.strip()) > 100 and '<' in c]
        if not significant:
            continue

        base, ext = en_filename.rsplit('.', 1)
        for block in significant:
            # Build fingerprints: Liquid template vars and long href values are unique
            fingerprints = re.findall(r'\{\{[^}]+\}\}', block)
            fingerprints += re.findall(r'href="[^"]{10,}"', block)
            if not fingerprints:
                continue

            for lang in ('es', 'de'):
                lang_file = f"{base}.{lang}.{ext}"
                if lang_file in fetched:
                    lang_html = fetched[lang_file]["html"]
                else:
                    try:
                        lf = portfolio.get_contents(lang_file, ref=read_ref)
                        lang_html = lf.decoded_content.decode()
                        fetched[lang_file] = {"html": lang_html}
                    except Exception:
                        continue

                # Check if fingerprint appears outside comments in the translation
                lang_uncommented = re.sub(r'<!--.*?-->', '', lang_html, flags=re.DOTALL)
                found_fp = next((fp for fp in fingerprints if fp in lang_uncommented), None)
                if found_fp is None:
                    continue

                sep = "-" * 60
                print(f"\n  ⚠️  {lang_file}: block is commented in EN but present in translation")
                en_visible = [l.strip() for l in re.sub(r'<[^>]+>', '', block).splitlines() if l.strip()]
                print(f"  EN (commented out)  {sep}")
                for line in en_visible:
                    print(f"    {line}")

                bounds = _element_bounds(lang_html, found_fp)
                if bounds:
                    lang_visible = [
                        l.strip() for l in
                        re.sub(r'<[^>]+>', '', lang_html[bounds[0]:bounds[1]]).splitlines()
                        if l.strip()
                    ]
                    print(f"  {lang.upper()} (uncommented)  {sep}")
                    for line in lang_visible:
                        print(f"    {line}")
                print(sep)

                choice = input(f"    Remove from {lang_file}? [y/n] ").strip().lower()
                if choice != 'y':
                    continue

                if bounds:
                    start, end = bounds
                    # Also eat the surrounding newline/whitespace
                    while start > 0 and lang_html[start - 1] in ' \t':
                        start -= 1
                    if start > 0 and lang_html[start - 1] == '\n':
                        start -= 1
                    new_html = lang_html[:start] + lang_html[end:]
                    fetched[lang_file]["html"] = new_html
                    if lang_file not in changed:
                        changed.append(lang_file)
                    print(f"    ✅ Removed from {lang_file}")
                else:
                    print("    ⚠️  Could not locate element bounds — skipping automatic removal.")

    if not changed:
        print("    ✅ No commented-out drift found")
    return changed


# ── Phase runners ─────────────────────────────────────────────────────────────

def _phase_header(n: int, title: str) -> None:
    print(f"\n{'═' * 60}")
    print(f"  Phase {n}: {title}")
    print(f"{'═' * 60}")


def _list_en_pages(portfolio, read_ref: str) -> list[str]:
    """Return all EN HTML pages in the portfolio root (excludes 404.html and lang variants)."""
    try:
        items = portfolio.get_contents("", ref=read_ref)
        return [
            f.name for f in items
            if f.name.endswith(".html")
            and not re.search(r'\.(es|de)\.html$', f.name)
            and f.name not in {"404.html"}
        ]
    except Exception as e:
        print(f"  ⚠️  Could not list repo contents: {e}")
        return [PORTFOLIO_FILE]


def run_phase_1(g: Github, llm: ChatAnthropic, portfolio, fetched: dict, read_ref: str) -> list[str]:
    """Phase 1: English baseline & repo check — links and card content."""
    _phase_header(1, "English Baseline & Repo Check")
    changed = []
    print("\n🔗 Checking links...")
    changed += _fix_links_inplace(g, fetched)
    print("\n⚙️  Checking card content (tech stack + description)...")
    changed += _fix_card_content_inplace(g, llm, fetched)
    return changed


def run_phase_2(portfolio, fetched: dict, read_ref: str) -> list[str]:
    """Phase 2: HTML structure consistency — styling, card order, element structure, and commented-block drift."""
    _phase_header(2, "HTML Structure Consistency")
    changed = []
    print("\n🔬 Checking element structure vs EN...")
    changed += _fix_structure_inplace(fetched)
    print("\n🎨 Checking styling...")
    changed += _fix_styling_inplace(fetched)
    print("\n🔀 Checking card order...")
    changed += _fix_order_inplace(fetched)
    print("\n🔍 Checking commented-out block drift in translations...")
    changed += _fix_commented_blocks_inplace(portfolio, fetched, read_ref)
    return changed


def run_phase_3(llm, portfolio, fetched: dict, read_ref: str) -> list[str]:
    """Phase 3: Translation content review — missing or outdated translated sections."""
    from sync_translations import _sync_file, _split_sections, _lang_filename
    _phase_header(3, "Translation Content Review")
    en_pages = _list_en_pages(portfolio, read_ref)
    changed = []

    # ── Section sync ─────────────────────────────────────────────────────────
    for en_file in en_pages:
        print(f"\n  📄 {en_file}")
        updates = _sync_file(llm, portfolio, en_file, read_ref)
        for fname, html in updates.items():
            if fname in fetched:
                fetched[fname]["html"] = html
            else:
                fetched[fname] = {"html": html, "sha": ""}
            if fname not in changed:
                changed.append(fname)

    # ── Collect all drift items up front ─────────────────────────────────────
    print("\n  🔍 Checking translation drift...")
    # Cards flagged for drift: (en_file, lang_file, card_idx, lang_card, lang, critique)
    # card_idx lets us re-read en_card live from fetched so EN edits carry over across languages.
    drift_items = []
    for en_file in en_pages:
        if en_file not in fetched:
            try:
                f = portfolio.get_contents(en_file, ref=read_ref)
                fetched[en_file] = {"html": f.decoded_content.decode("utf-8"), "sha": f.sha}
            except Exception:
                continue  # EN file doesn't exist
        for lang in ("es", "de"):
            lang_file = _lang_filename(en_file, lang)
            if lang_file not in fetched:
                try:
                    f = portfolio.get_contents(lang_file, ref=read_ref)
                    fetched[lang_file] = {"html": f.decoded_content.decode("utf-8"), "sha": f.sha}
                except Exception:
                    continue  # translation file doesn't exist yet
            en_sections = _split_sections(fetched[en_file]["html"])
            lang_sections = _split_sections(fetched[lang_file]["html"])
            for i in range(1, min(len(en_sections), len(lang_sections))):
                en_card = en_sections[i]
                lang_card = lang_sections[i]
                if not re.search(r'\w', en_card) or not re.search(r'\w', lang_card):
                    continue
                critique = _llm_compare_translation(llm, en_card, lang_card, lang)
                if critique:
                    drift_items.append((en_file, lang_file, i, lang_card, lang, critique))

    if not drift_items:
        return changed

    # ── Navigate drift items with back/forward ────────────────────────────────
    idx = 0
    while idx < len(drift_items):
        en_file, lang_file, card_idx, lang_card, lang, critique = drift_items[idx]
        # Re-read en_card fresh so any EN edits from a previous comparison are picked up
        en_card = _split_sections(fetched[en_file]["html"])[card_idx]
        label = _card_label(en_card) or f"card {idx + 1}"
        # Re-evaluate drift only if EN was edited this session (avoids redundant LLM calls)
        if en_file in changed:
            fresh_critique = _llm_compare_translation(llm, en_card, lang_card, lang)
            if fresh_critique is None:
                print(f"\n    ✅  {lang_file} — {label}: drift resolved (EN was updated earlier)")
                idx += 1
                continue
            critique = fresh_critique
        print(f"\n    ⚠️  {lang_file} — {label}: LLM flagged translation drift:")
        print(f"      {critique.strip()}")
        _print_card_summary(en_card, "EN")
        _print_card_summary(lang_card, lang.upper())
        result = _handle_drift_interactive(llm, en_file, lang_file, en_card, lang_card, lang, fetched, changed, card_idx, critique)
        if result == "back" and idx > 0:
            idx -= 1
        else:
            idx += 1

    return changed

# ── Card summary printer ────────────────────────────────────────────────────
def _print_card_summary(card_html: str, label: str) -> None:
    """Print a summary of an HTML section. Extracts work-card fields (h2, tech line,
    description, bullets, GitHub link) when present; falls back to plain text for
    general page sections (e.g. index, about, contact)."""
    ind = "      "
    sep = f"{ind}{'─' * 44}"
    print(sep)
    print(f"{ind}{label}")

    printed_something = False
    printed_title = False

    title_m = re.search(r'<h2[^>]*>(.*?)</h2>', card_html, re.DOTALL)
    if title_m:
        print(f"{ind}  {re.sub(r'<[^>]+>', '', title_m.group(1)).strip()}")
        printed_something = True
        printed_title = True

    tech_m = TECH_P.search(card_html)
    if tech_m:
        print(f"{ind}  Tech:  {tech_m.group(1).strip()}")
        printed_something = True

    desc_m = re.search(r'<p class="mb-4"[^>]*>(.*?)</p>', card_html, re.DOTALL)
    if desc_m:
        desc = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()
        print(f"{ind}  {desc}")
        printed_something = True

    bullets = re.findall(r'<li[^>]*>(.*?)</li>', card_html, re.DOTALL)
    for b in bullets:
        print(f"{ind}  • {re.sub(r'<[^>]+>', '', b).strip()}")
        printed_something = True

    link_m = re.search(r'href="(https://github\.com/[^"]+)"', card_html)
    if link_m:
        print(f"{ind}  {link_m.group(1)}")
        printed_something = True

    # Fallback for non-card sections:
    # - if nothing recognizable printed, show plain text preview
    # - if only a title printed, also show body preview so drift is visible
    if (not printed_something) or (printed_title and not (tech_m or desc_m or bullets or link_m)):
        plain = re.sub(r'<[^>]+>', ' ', card_html)
        plain = re.sub(r'\s+', ' ', plain).strip()
        if title_m:
            title_text = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
            if title_text:
                # Remove only the first title occurrence from preview body.
                plain = re.sub(re.escape(title_text), '', plain, count=1).strip(" :-\u2014\u2013")
        if not plain:
            plain = re.sub(r'<[^>]+>', ' ', card_html)
            plain = re.sub(r'\s+', ' ', plain).strip()
        import textwrap
        if len(plain) <= 300:
            # If short, print all
            print(f"{ind}  {plain}")
        else:
            # Otherwise, split into lines by sentence or period, fallback to 80-char chunks
            lines = [l.strip() for l in re.split(r'(?<=[.!?])\s+', plain) if l.strip()]
            if not lines or len(lines) == 1:
                lines = textwrap.wrap(plain, 80)
            max_lines = 5
            for i, line in enumerate(lines):
                if i >= max_lines:
                    print(f"{ind}  …")
                    break
                print(f"{ind}  {line}")

    print(sep)


# ── Translation drift interactive fix ───────────────────────────────────────
def _handle_drift_interactive(
    llm, en_file: str, lang_file: str, en_card: str, lang_card: str, lang: str,
    fetched: dict, changed: list, card_idx: int = -1, critique: str = "",
) -> str | None:
    """Prompt user to act on a flagged translation drift. Returns 'back' or None."""
    lang_label = {"es": "Spanish", "de": "German"}[lang]
    current_card = lang_card
    en_ref = [en_card]  # mutable so EN updates propagate to retranslate

    def _rewrite_en(instruction: str) -> str:
        """Rewrite the EN card using the given instruction, update fetched and en_ref."""
        from sync_translations import _split_sections
        new_en = llm.invoke(
            f"Update the following English portfolio card according to this instruction:\n{instruction}\n\n"
            f"Rules:\n"
            f"- Preserve the exact HTML structure and Tailwind CSS classes.\n"
            f"- Return ONLY the updated card HTML, no markdown, no backticks.\n\n"
            f"CURRENT ENGLISH CARD:\n{en_ref[0]}\n"
        ).content.strip()
        if new_en != en_ref[0]:
            en_ref[0] = new_en
            if card_idx >= 0:
                # Positional replace — reliable regardless of whitespace differences
                sections = _split_sections(fetched[en_file]["html"])
                sections[card_idx] = new_en
                fetched[en_file]["html"] = "".join(sections)
            else:
                # Fallback: string replace (card_idx unavailable)
                old_html = fetched[en_file]["html"]
                fetched[en_file]["html"] = old_html.replace(en_card, new_en, 1)
            if en_file not in changed:
                changed.append(en_file)
            print(f"      ✅  Updated EN card in {en_file}")
        return new_en

    def _discuss(concern: str) -> str:
        """LLM responds to user's concern and shares its plan."""
        response = llm.invoke(
            f"You are helping review a {lang_label} translation of an English portfolio card.\n\n"
            f"ENGLISH CARD:\n{en_ref[0]}\n\n"
            f"CURRENT TRANSLATION:\n{current_card}\n\n"
            f"The user raised this concern or question:\n{concern}\n\n"
            f"First, answer their question directly and share your opinion. "
            f"If the fix also requires updating the ENGLISH card, say so explicitly. "
            f"Then describe what you would change (2-4 bullet points). "
            f"Do NOT generate HTML."
        ).content.strip()
        return response

    def _plan_improvement(card: str, hint: str = "") -> str:
        """Ask LLM to describe what it would change, without generating HTML yet."""
        extra = f"\nThe user's specific instruction: {hint}\n" if hint else ""
        return llm.invoke(
            f"You are reviewing a {lang_label} translation of an English portfolio card for semantic drift.\n"
            f"{extra}\n"
            f"ENGLISH CARD:\n{en_card}\n\n"
            f"CURRENT TRANSLATION:\n{card}\n\n"
            f"Describe concisely (2-4 bullet points) what you would change to fix the drift. "
            f"Do NOT generate HTML yet — just explain your plan in plain text."
        ).content.strip()

    def _maybe_update_en(instruction: str) -> None:
        """Rewrite EN card only if the user explicitly asks to update/fix/change the English card."""
        en_keywords = ("update the english", "fix the english", "change the english",
                       "update english card", "fix english card", "update the en card",
                       "fix the en card", "update en card", "also update english",
                       "also fix english", "en version", "english version", "english card")
        if any(k in instruction.lower() for k in en_keywords):
            _rewrite_en(instruction)

    def _retranslate(card: str, feedback: str = "") -> str:
        extra = f"\nUser feedback to address: {feedback}\n" if feedback else ""
        return llm.invoke(
            f"Retranslate the following English portfolio card into {lang_label}.\n"
            f"Rules:\n"
            f"- Keep all technical terms and technology names in English.\n"
            f"- Preserve the exact HTML structure and Tailwind CSS classes.\n"
            f"- Return ONLY the translated card HTML, no markdown, no backticks.\n"
            f"{extra}\n"
            f"ENGLISH CARD:\n{en_ref[0]}\n"
        ).content.strip()

    def _show_card(card: str) -> None:
        _print_card_summary(en_ref[0], "EN")
        _print_card_summary(card, lang.upper())

    while True:
        choice = input("      Fix? [y=retranslate / improve / n=skip / back] ").strip().lower()
        if choice == "back":
            return "back"
        elif choice == "n":
            return None
        elif choice == "y":
            current_card = _retranslate(en_ref[0], feedback=critique)
        elif choice == "improve":
            concern = input("      Your concern or question: ").strip()
            response = _discuss(concern)
            print()
            for line in response.splitlines():
                print(f"        {line}")
            print()
            direction = input("      [proceed / redirect / n=cancel] ").strip().lower()
            if direction == "n":
                return None
            elif direction == "redirect":
                concern = input("      Your instruction: ").strip()
                instruction = concern
            else:
                instruction = response
            # Offer to update EN if the user's own words explicitly target it
            _maybe_update_en(concern)
            current_card = _retranslate(current_card, instruction)
        else:
            print("      Options: y  improve  n  back")
            continue

        # Show result and let user keep iterating
        _show_card(current_card)
        while True:
            accept = input("      Apply? [y / improve / n / back] ").strip().lower()
            if accept == "y":
                break  # fall through to apply
            elif accept == "n":
                return None
            elif accept == "back":
                current_card = lang_card
                break  # restart outer loop
            elif accept == "improve":
                concern = input("      Your concern or question: ").strip()
                response = _discuss(concern)
                print()
                for line in response.splitlines():
                    print(f"        {line}")
                print()
                direction = input("      [proceed / redirect / n=cancel] ").strip().lower()
                if direction == "n":
                    return None
                elif direction == "redirect":
                    concern = input("      Your instruction: ").strip()
                    instruction = concern
                else:
                    instruction = response
                # Offer to update EN if the user's own words explicitly target it
                _maybe_update_en(concern)
                current_card = _retranslate(current_card, instruction)
                _show_card(current_card)
            else:
                print("      Options: y  improve  n  back")
        if accept != "y":
            continue  # restart outer loop (back was pressed)

        # Apply the fixed card back into the file — positional replace to avoid whitespace mismatch
        from sync_translations import _split_sections
        old_html = fetched[lang_file]["html"]
        lang_sections = _split_sections(old_html)
        if 0 < card_idx < len(lang_sections):
            lang_sections[card_idx] = current_card
            new_html = "".join(lang_sections)
        else:
            new_html = old_html.replace(lang_card, current_card, 1)
        if new_html != old_html:
            fetched[lang_file]["html"] = new_html
            if lang_file not in changed:
                changed.append(lang_file)
            lang_code = lang_file.split(".")[-2] if "." in lang_file else lang_file
            if lang_code in ("es", "de"):
                print(f"      ✅  Updated {lang_code.upper()} card in {lang_file}")
            else:
                print(f"      ✅  Updated card in {lang_file}")
        return None


# ── LLM-based translation drift check ───────────────────────────────────────
def _llm_compare_translation(llm, en_card: str, lang_card: str, lang: str) -> str | None:
    """Ask LLM to compare EN and translation card for semantic drift. Returns critique if drift found, else None."""
    lang_label = {"es": "Spanish", "de": "German"}[lang]
    prompt = (
        f"Compare the following English and {lang_label} HTML portfolio cards.\n\n"
        f"ENGLISH CARD:\n{en_card}\n\n"
        f"{lang_label.upper()} CARD:\n{lang_card}\n\n"
        f"Rules:\n"
        f"- Check that all technologies, features, and details in the English card are present and accurate in the translation.\n"
        f"- Flag any missing, added, or incorrect content.\n"
        f"- If the translation is accurate, reply ONLY 'OK'.\n"
        f"- If there is any drift, reply with a short critique (1-2 sentences, no markdown)."
    )
    try:
        response = llm.invoke(prompt).content.strip()
    except Exception as e:
        print(f"      [LLM error: {e}]")
        return None
    if response.upper().startswith("OK"):
        return None
    return response


# ── Main menu ─────────────────────────────────────────────────────────────────

def main():
    g = Github(auth=Auth.Token(os.getenv("GITHUB_TOKEN")))
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        temperature=0,
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )

    portfolio, fetched, read_ref, open_audit_pr = _open_fix_session(g)
    all_changed: set[str] = set()

    PHASES = [
        ("1", "English Baseline & Repo Check",
         lambda: run_phase_1(g, llm, portfolio, fetched, read_ref)),
        ("2", "HTML Structure Consistency",
         lambda: run_phase_2(portfolio, fetched, read_ref)),
        ("3", "Translation Content Review",
         lambda: run_phase_3(llm, portfolio, fetched, read_ref)),
    ]

    while True:
        print("\n" + "═" * 60)
        print("  Portfolio Audit")
        print("─" * 60)
        for key, label, _ in PHASES:
            print(f"  {key}. {label}")
        print("  a. Run all phases")
        print("  q. Quit / commit pending changes")
        print("═" * 60)
        choice = input("  Select: ").strip().lower()

        if choice == "q":
            break

        if choice == "a":
            keys_to_run = [key for key, _, _ in PHASES]
        elif any(choice == key for key, _, _ in PHASES):
            keys_to_run = [choice]
        else:
            print("  Invalid choice.")
            continue

        phase_map = {key: (label, fn) for key, label, fn in PHASES}
        for i, key in enumerate(keys_to_run):
            label, run_fn = phase_map[key]
            changed = run_fn()
            all_changed.update(changed)
            # Offer to continue to the next phase when running sequentially
            if i < len(keys_to_run) - 1:
                cont = input("\n  ▶  Continue to next phase? [y/n] ").strip().lower()
                if cont != "y":
                    print("  Stopped. Return to the menu to run remaining phases.")
                    break

    if not all_changed:
        print("\n✅ Nothing changed. No PR needed.")
        return

    changed_list = sorted(all_changed)
    print(f"\n{len(changed_list)} file(s) updated: {', '.join(changed_list)}")
    confirm = input("\nPush changes to PR? [y/N] ").strip().lower()
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
            "chore: audit pass — update portfolio\n\n"
            "- fix stale/transferred GitHub links\n"
            "- update tech stack subtitles where languages/topics changed\n"
            "- refresh description paragraphs where README has drifted\n"
            "- normalize Tailwind CSS classes within cards\n"
            "- reorder ES/DE cards to match EN\n"
            "- remove blocks commented-out in EN but present in translations\n"
            "- add missing translated sections"
        ),
        pr_title="Portfolio audit",
        pr_body=(
            "Automated audit pass — applied the following fixes as needed:\n\n"
            "**Phase 1 — English Baseline & Repo Check**\n"
            "- Corrected transferred/stale repo URLs\n"
            "- Updated tech stack subtitles\n"
            "- Refreshed description paragraphs and bullets\n\n"
            "**Phase 2 — HTML Structure Consistency**\n"
            "- Normalized Tailwind CSS class strings\n"
            "- Reordered ES/DE cards to match EN\n"
            "- Removed commented-out blocks from translations\n\n"
            "**Phase 3 — Translation Content Review**\n"
            "- Added missing translated sections"
        ),
    )
    print(f"\n✅ PR: {pr_url}")


if __name__ == "__main__":
    main()
