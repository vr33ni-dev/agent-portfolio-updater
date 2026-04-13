"""
Tests for audit.py — no network calls, no LLM calls, no user input.
"""

import re
from unittest.mock import MagicMock, patch

import pytest

from audit import (
    _card_label,
    _card_repo_paths,
    extract_repo_links,
    _fix_card_content_inplace,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

CARD_SINGLE = """\
<div class="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6">
  <h2 class="text-xl font-semibold mb-2">My Cool Project</h2>
  <p class="text-sm text-gray-500 dark:text-gray-400 mb-2">Python · FastAPI</p>
  <p class="mb-4">A tool that does stuff.</p>
  <ul class="list-disc list-inside text-sm mb-4 space-y-1">
    <li>Feature A</li>
    <li>Feature B</li>
  </ul>
  <a href="https://github.com/vr33ni/my-cool-project">GitHub</a>
</div>
"""

CARD_MULTI_REPO = """\
<div class="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6">
  <h2 class="text-xl font-semibold mb-2">Sales Assistant</h2>
  <p class="text-sm text-gray-500 dark:text-gray-400 mb-2">Vue.js · Go · PostgreSQL</p>
  <p class="mb-4">A full-stack sales assistant.</p>
  <ul class="list-disc list-inside text-sm mb-4 space-y-1">
    <li>Frontend in Vue.js</li>
    <li>Backend in Go</li>
  </ul>
  <a href="https://github.com/vr33ni/sales-assistant-frontend">Frontend</a>
  <a href="https://github.com/vr33ni/sales-assistant-go">Backend</a>
</div>
"""


def _make_fetched(en_card: str, es_card: str | None = None, de_card: str | None = None) -> dict:
    """Build a minimal fetched dict with the card wrapped in a preamble."""
    preamble = "<section>\n"
    return {
        "work.html":    {"html": preamble + en_card, "sha": "abc"},
        "work.es.html": {"html": preamble + (es_card or en_card), "sha": "def"},
        "work.de.html": {"html": preamble + (de_card or en_card), "sha": "ghi"},
    }


def _make_repo_mock(name: str, url: str):
    repo = MagicMock()
    repo.name = name
    repo.html_url = url
    repo.description = f"{name} description"
    repo.get_languages.return_value = {"Python": 1000}
    repo.get_topics.return_value = ["fastapi", "python"]
    readme = MagicMock()
    readme.decoded_content = b"# README\nThis project does things."
    repo.get_readme.return_value = readme
    return repo


# ── Unit tests: pure helpers ──────────────────────────────────────────────────

def test_extract_repo_links_single():
    links = extract_repo_links(CARD_SINGLE)
    assert links == ["vr33ni/my-cool-project"]


def test_extract_repo_links_multi():
    links = extract_repo_links(CARD_MULTI_REPO)
    assert "vr33ni/sales-assistant-frontend" in links
    assert "vr33ni/sales-assistant-go" in links
    assert len(links) == 2


def test_card_label_from_h2():
    assert _card_label(CARD_SINGLE) == "My Cool Project"


def test_card_label_from_h2_multi():
    assert _card_label(CARD_MULTI_REPO) == "Sales Assistant"


def test_card_label_fallback_to_repo_name():
    chunk = '<a href="https://github.com/vr33ni/some-project">link</a>'
    assert _card_label(chunk) == "some-project"


def test_card_repo_paths():
    paths = _card_repo_paths(CARD_MULTI_REPO)
    assert paths == ["vr33ni/sales-assistant-frontend", "vr33ni/sales-assistant-go"]


# ── Integration-style test: stale card (LLM says UPDATE) ─────────────────────

@patch("audit._fetch_subdir_readmes", return_value="")
@patch("audit._fetch_code_context", return_value="")
@patch("builtins.input", return_value="y")   # auto-accept all prompts
def test_stale_card_description_updated(mock_input, mock_code, mock_subdirs):
    """When LLM returns UPDATE for the description, the card HTML should be modified
    and the changed filename returned."""

    repo = _make_repo_mock("my-cool-project", "https://github.com/vr33ni/my-cool-project")

    g = MagicMock()
    g.get_repo.return_value = repo

    rewritten_card = CARD_SINGLE.replace(
        "<p class=\"mb-4\">A tool that does stuff.</p>",
        "<p class=\"mb-4\">A completely rewritten description.</p>",
    )

    call_count = {"n": 0}

    def llm_side_effect(prompt):
        response = MagicMock()
        call_count["n"] += 1
        if "Reply with just KEEP or UPDATE" in prompt:
            response.content = "UPDATE"
        elif "APPROVED or REJECTED" in prompt:
            response.content = "APPROVED\nLooks good."
        else:
            # description rewrite or translation
            response.content = rewritten_card
        return response

    llm = MagicMock()
    llm.invoke.side_effect = llm_side_effect

    fetched = _make_fetched(CARD_SINGLE)
    changed = _fix_card_content_inplace(g, llm, fetched)

    assert "work.html" in changed
    assert "A completely rewritten description." in fetched["work.html"]["html"]


@patch("audit._fetch_subdir_readmes", return_value="")
@patch("audit._fetch_code_context", return_value="")
def test_fresh_card_not_modified(mock_code, mock_subdirs):
    """When LLM says KEEP for both tech and description, nothing should change."""

    repo = _make_repo_mock("my-cool-project", "https://github.com/vr33ni/my-cool-project")

    g = MagicMock()
    g.get_repo.return_value = repo

    llm = MagicMock()
    llm.invoke.return_value.content = "KEEP"

    fetched = _make_fetched(CARD_SINGLE)
    original_html = fetched["work.html"]["html"]

    changed = _fix_card_content_inplace(g, llm, fetched)

    assert changed == []
    assert fetched["work.html"]["html"] == original_html


@patch("audit._fetch_subdir_readmes", return_value="")
@patch("audit._fetch_code_context", return_value="")
@patch("builtins.input", return_value="y")
def test_stale_tech_stack_updated(mock_input, mock_code, mock_subdirs):
    """When LLM proposes a new tech stack, it should be applied to all three files."""

    repo = _make_repo_mock("my-cool-project", "https://github.com/vr33ni/my-cool-project")
    repo.get_languages.return_value = {"Python": 1000, "TypeScript": 500}

    g = MagicMock()
    g.get_repo.return_value = repo

    def llm_side_effect(prompt):
        response = MagicMock()
        if "tech stack line" in prompt:
            response.content = "Python · TypeScript · FastAPI"
        else:
            response.content = "KEEP"
        return response

    llm = MagicMock()
    llm.invoke.side_effect = llm_side_effect

    fetched = _make_fetched(CARD_SINGLE)
    changed = _fix_card_content_inplace(g, llm, fetched)

    assert "work.html" in changed
    assert "Python · TypeScript · FastAPI" in fetched["work.html"]["html"]


@patch("audit._fetch_subdir_readmes", return_value="")
@patch("audit._fetch_code_context", return_value="")
def test_multi_repo_card_produces_one_status(mock_code, mock_subdirs, capsys):
    """A card with two repo links should produce exactly one FRESH/STALE line."""

    frontend = _make_repo_mock(
        "sales-assistant-frontend", "https://github.com/vr33ni/sales-assistant-frontend"
    )
    backend = _make_repo_mock(
        "sales-assistant-go", "https://github.com/vr33ni/sales-assistant-go"
    )

    g = MagicMock()
    g.get_repo.side_effect = lambda path: (
        frontend if "frontend" in path else backend
    )

    llm = MagicMock()
    llm.invoke.return_value.content = "KEEP"

    fetched = _make_fetched(CARD_MULTI_REPO)
    _fix_card_content_inplace(g, llm, fetched)

    captured = capsys.readouterr()
    status_lines = [l for l in captured.out.splitlines() if "FRESH" in l or "STALE" in l]
    assert len(status_lines) == 1
    assert "Sales Assistant" in status_lines[0]
