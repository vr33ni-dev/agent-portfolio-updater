"""
simulate_stale.py — Run _fix_card_content_inplace against a fake stale card.

No GitHub API, no Anthropic API, no real portfolio files touched.
input() prompts are live so you can respond interactively.

Usage:
    python simulate_stale.py
"""

from unittest.mock import MagicMock, patch
import re
from audit import _fix_card_content_inplace, _card_to_text

# ── Fake portfolio card ───────────────────────────────────────────────────────

STALE_CARD = """\
<div class="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6">
  <h2 class="text-xl font-semibold mb-2">My Cool Project</h2>
  <p class="text-sm text-gray-500 dark:text-gray-400 mb-2">Python · Flask</p>
  <p class="mb-4">A simple REST API built with Flask.</p>
  <ul class="list-disc list-inside text-sm mb-4 space-y-1">
    <li>Basic CRUD endpoints</li>
    <li>SQLite storage</li>
  </ul>
  <a href="https://github.com/vr33ni/my-cool-project">GitHub</a>
</div>
"""

# The README reflects a rewrite to FastAPI + PostgreSQL — card is now stale
FAKE_README = """\
# my-cool-project

A production-grade REST API migrated from Flask to FastAPI, backed by PostgreSQL.

## Features
- Async endpoints with FastAPI
- PostgreSQL with SQLAlchemy ORM
- JWT authentication
- Docker Compose for local dev
"""

REWRITTEN_CARD = """\
<div class="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6">
  <h2 class="text-xl font-semibold mb-2">My Cool Project</h2>
  <p class="text-sm text-gray-500 dark:text-gray-400 mb-2">Python · Flask</p>
  <p class="mb-4">A production-grade async REST API built with FastAPI and PostgreSQL.</p>
  <ul class="list-disc list-inside text-sm mb-4 space-y-1">
    <li>Async endpoints with FastAPI</li>
    <li>PostgreSQL + SQLAlchemy ORM</li>
    <li>JWT authentication and Docker Compose setup</li>
  </ul>
  <a href="https://github.com/vr33ni/my-cool-project">GitHub</a>
</div>
"""

# ── Mocks ─────────────────────────────────────────────────────────────────────

def _make_repo():
    repo = MagicMock()
    repo.name = "my-cool-project"
    repo.html_url = "https://github.com/vr33ni/my-cool-project"
    repo.description = "Production REST API with FastAPI and PostgreSQL"
    repo.get_languages.return_value = {"Python": 12000}
    repo.get_topics.return_value = ["fastapi", "postgresql", "python", "rest-api"]
    readme = MagicMock()
    readme.decoded_content = FAKE_README.encode()
    repo.get_readme.return_value = readme
    return repo


def _make_llm(last_stage: dict):
    call_count = {"n": 0}
    # last_stage is shared with _patched_input so hints stay in sync with mock responses.

    def side_effect(prompt):
        response = MagicMock()
        call_count["n"] += 1

        if "tech stack line" in prompt:
            # Simulate stale tech: card says Flask but repo is now FastAPI + PostgreSQL
            last_stage["name"] = "tech"
            response.content = "Python · FastAPI · PostgreSQL"

        elif "You proposed this tech stack" in prompt:
            # edit hint: try "remove FastAPI, use Flask instead"
            # → mock returns: Python · Flask · PostgreSQL
            last_stage["name"] = "tech"
            response.content = "Python · Flask · PostgreSQL"

        elif "Reply with just KEEP or UPDATE" in prompt:
            # Description is stale — README shows FastAPI but card says Flask
            last_stage["name"] = "desc"
            response.content = "UPDATE"

        elif "APPROVED or REJECTED" in prompt:
            response.content = "APPROVED\nLooks good."

        elif "Improve this portfolio card" in prompt:
            # improve hint: try "replace FastAPI with Flask throughout"
            # → mock rewrites card using Flask instead of FastAPI
            response.content = REWRITTEN_CARD.replace(
                "<p class=\"mb-4\">A production-grade async REST API built with FastAPI and PostgreSQL.</p>",
                "<p class=\"mb-4\">A production-grade REST API built with Flask and PostgreSQL.</p>",
            ).replace(
                "<li>Async endpoints with FastAPI</li>",
                "<li>RESTful endpoints with Flask</li>",
            )

        else:
            # Description rewrite or translation
            response.content = REWRITTEN_CARD

        return response

    llm = MagicMock()
    llm.invoke.side_effect = side_effect
    return llm


def _patched_input(last_stage: dict):
    """Wrap input() to print a hint before any 'What to change:' prompt."""
    _real_input = __builtins__["input"] if isinstance(__builtins__, dict) else input

    def _inner(prompt=""):
        if "What to change" in prompt:
            if last_stage.get("name") == "tech":
                print("         [hint] e.g. 'remove FastAPI, use Flask instead'"
                      "  →  mock returns: Python · Flask · PostgreSQL")
            elif last_stage.get("name") == "desc":
                print("         [hint] e.g. 'replace FastAPI with Flask throughout'"
                      "  →  mock rewrites card using Flask instead of FastAPI")
        return _real_input(prompt)

    return _inner


# ── Run ───────────────────────────────────────────────────────────────────────

def main():
    preamble = "<section>\n"
    fetched = {
        "work.html":    {"html": preamble + STALE_CARD, "sha": "aaa"},
        "work.es.html": {"html": preamble + STALE_CARD, "sha": "bbb"},
        "work.de.html": {"html": preamble + STALE_CARD, "sha": "ccc"},
    }

    g = MagicMock()
    g.get_repo.return_value = _make_repo()
    last_stage: dict = {"name": ""}
    llm = _make_llm(last_stage)

    with patch("audit._fetch_code_context", return_value=""), \
         patch("audit._fetch_subdir_readmes", return_value=""), \
         patch("builtins.input", side_effect=_patched_input(last_stage)):
        changed = _fix_card_content_inplace(g, llm, fetched)

    print(f"\nChanged files: {changed}")
    if "work.html" in changed:
        sep = "─" * 50
        print(f"\n── Updated work.html card ──────────────────────")
        parts = re.split(r'(?=<div class="bg-white)', fetched["work.html"]["html"])
        for p in parts:
            if "github.com" in p:
                print(sep)
                print(_card_to_text(p))
                print(sep)


if __name__ == "__main__":
    main()
