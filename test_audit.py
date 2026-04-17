"""
Tests for audit.py and sync_translations.py — no network calls, no LLM calls, no user input.
"""

import re
from unittest.mock import MagicMock, patch

import pytest

from audit import (
    _card_label,
    _card_repo_paths,
    extract_repo_links,
    _fix_card_content_inplace,
    _element_bounds,
    _fix_commented_blocks_inplace,
    _list_en_pages,
    run_phase_1,
    run_phase_2,
    run_phase_3,
)
from sync_translations import (
    _split_sections,
    _section_anchor,
    _visible_text,
    _lang_filename,
    _sync_file,
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


# ── Unit tests: sync_translations helpers ────────────────────────────────────

def test_split_sections_card_page():
    html = '<div class="bg-white">card1</div>\n<div class="bg-white">card2</div>'
    parts = [p for p in _split_sections(html) if p.strip()]
    assert len(parts) == 2


def test_split_sections_section_page():
    html = (
        "<header>top</header>"
        '<section id="about">About</section>'
        '<section id="skills">Skills</section>'
    )
    parts = _split_sections(html)
    assert len(parts) == 3


def test_section_anchor_github_url():
    chunk = '<a href="https://github.com/vr33ni/my-project">link</a>'
    assert _section_anchor(chunk) == "https://github.com/vr33ni/my-project"


def test_section_anchor_heading():
    chunk = '<section><h2 class="title">About Me</h2><p>text</p></section>'
    assert _section_anchor(chunk) == "about me"


def test_section_anchor_id_over_heading():
    chunk = '<section id="contact"><h2 class="title">Contact</h2><p>text</p></section>'
    assert _section_anchor(chunk) == "contact"


def test_section_anchor_none():
    assert _section_anchor("<p>no heading or url</p>") is None


def test_lang_filename():
    assert _lang_filename("index.html", "es") == "index.es.html"
    assert _lang_filename("work.html", "de") == "work.de.html"


# ── Integration test: missing section gets translated and added ───────────────

@patch("builtins.input", return_value="y")
def test_sync_file_missing_section(mock_input):
    """ES page is missing a section that exists in EN → LLM translates it, user accepts."""
    EN_HTML = (
        "<header>nav</header>"
        "<section><h2>About Me</h2><p>I am a developer.</p></section>"
        "<section><h2>New Section</h2><p>Brand new content.</p></section>"
    )
    ES_HTML = (
        "<header>nav</header>"
        "<section><h2>About Me</h2><p>Soy desarrolladora.</p></section>"
    )
    TRANSLATED = "<section><h2>Nueva Sección</h2><p>Contenido nuevo.</p></section>"

    def _mock_contents(filename, ref=None):
        c = MagicMock()
        c.decoded_content = (EN_HTML if filename == "about.html" else ES_HTML).encode()
        return c

    portfolio = MagicMock()
    portfolio.get_contents.side_effect = lambda f, ref=None: (
        _mock_contents(f, ref)
        if f in ("about.html", "about.es.html")
        else (_ for _ in ()).throw(Exception("not found"))
    )

    llm = MagicMock()
    llm.invoke.return_value.content = TRANSLATED

    with patch("sync_translations.LANGS", ("es",)):
        updates = _sync_file(llm, portfolio, "about.html", "main")

    assert "about.es.html" in updates
    assert "Nueva Sección" in updates["about.es.html"]


def test_sync_file_in_sync():
    """When EN and ES already share all sections, no updates should be produced."""
    SHARED = (
        "<header>nav</header>"
        "<section><h2>About Me</h2><p>content</p></section>"
    )

    portfolio = MagicMock()
    portfolio.get_contents.return_value.decoded_content = SHARED.encode()

    llm = MagicMock()

    with patch("sync_translations.LANGS", ("es",)):
        updates = _sync_file(llm, portfolio, "about.html", "main")

    assert updates == {}
    llm.invoke.assert_not_called()


# ── Unit tests: _element_bounds ───────────────────────────────────────────────

def test_element_bounds_simple_div():
    # _element_bounds resolves the innermost element containing the fingerprint
    html = '<p>before</p><div class="foo"><span>hello</span></div><p>after</p>'
    result = _element_bounds(html, 'hello')
    assert result is not None
    start, end = result
    assert html[start:end] == '<span>hello</span>'


def test_element_bounds_nested():
    html = '<div id="outer"><div id="inner">target</div></div>'
    result = _element_bounds(html, 'target')
    assert result is not None
    start, end = result
    extracted = html[start:end]
    assert 'target' in extracted
    assert extracted.startswith('<div')


def test_element_bounds_not_found():
    html = '<div>nothing here</div>'
    assert _element_bounds(html, 'missing') is None


def test_element_bounds_self_closing_sibling():
    html = '<section><img src="x.png"/><p>content</p></section>'
    result = _element_bounds(html, 'content')
    assert result is not None
    start, end = result
    assert html[start:end] == '<p>content</p>'


# ── Unit tests: _fix_commented_blocks_inplace ─────────────────────────────────

def _make_portfolio_mock(en_filename: str, en_html: str, lang_files: dict):
    """Build a portfolio mock that returns HTML for specific filenames."""
    portfolio = MagicMock()

    def get_contents(path, ref=None):
        contents = {en_filename: en_html, **lang_files}
        if path == "":
            # repo root listing
            items = []
            for name in contents:
                m = MagicMock()
                m.name = name
                items.append(m)
            return items
        if path in contents:
            f = MagicMock()
            f.decoded_content = contents[path].encode()
            return f
        raise Exception(f"not found: {path}")

    portfolio.get_contents.side_effect = get_contents
    return portfolio


@patch("builtins.input", return_value="y")
def test_commented_block_drift_removed(mock_input):
    """Block commented-out in EN but present in ES should be flagged and removed."""
    block_content = (
        '<div class="promo">'
        '<a href="https://example.com/long-enough-link">Click here</a>'
        '<p>Some promotional text that is quite long enough to be significant.</p>'
        '</div>'
    )
    en_html = f'<main><!-- {block_content} --><p>keep this</p></main>'
    es_html = f'<main>{block_content}<p>keep this</p></main>'

    portfolio = _make_portfolio_mock("about.html", en_html, {"about.es.html": es_html})
    fetched = {
        "about.html": {"html": en_html, "sha": "aaa"},
        "about.es.html": {"html": es_html, "sha": "bbb"},
    }

    changed = _fix_commented_blocks_inplace(portfolio, fetched, "main")

    assert "about.es.html" in changed
    assert block_content not in fetched["about.es.html"]["html"]
    assert "keep this" in fetched["about.es.html"]["html"]


@patch("builtins.input", return_value="n")
def test_commented_block_drift_rejected(mock_input):
    """When user rejects removal, the translation file should not be modified."""
    block_content = (
        '<div class="promo">'
        '<a href="https://example.com/long-enough-link">Click here</a>'
        '<p>Long enough promotional text for this test to be triggered.</p>'
        '</div>'
    )
    en_html = f'<main><!-- {block_content} --><p>keep</p></main>'
    es_html = f'<main>{block_content}<p>keep</p></main>'

    portfolio = _make_portfolio_mock("about.html", en_html, {"about.es.html": es_html})
    fetched = {
        "about.html": {"html": en_html, "sha": "aaa"},
        "about.es.html": {"html": es_html, "sha": "bbb"},
    }

    changed = _fix_commented_blocks_inplace(portfolio, fetched, "main")

    assert changed == []
    assert block_content in fetched["about.es.html"]["html"]


def test_commented_block_no_drift():
    """If a commented block has no uncommented counterpart in translations, nothing changes."""
    comment_block = (
        '<div class="promo">'
        '<a href="https://example.com/long-enough-link">Click here</a>'
        '<p>This is commented out in EN and also absent in ES.</p>'
        '</div>'
    )
    en_html = f'<main><!-- {comment_block} --><p>keep</p></main>'
    es_html = '<main><p>keep</p></main>'

    portfolio = _make_portfolio_mock("about.html", en_html, {"about.es.html": es_html})
    fetched = {
        "about.html": {"html": en_html, "sha": "aaa"},
        "about.es.html": {"html": es_html, "sha": "bbb"},
    }

    changed = _fix_commented_blocks_inplace(portfolio, fetched, "main")

    assert changed == []


def test_commented_block_skips_small_comments():
    """Short comments (< 100 non-whitespace chars) should be ignored."""
    en_html = '<main><!-- TODO: fix this --><p>keep</p></main>'
    es_html = '<main><!-- TODO: fix this --><p>keep</p></main>'

    portfolio = _make_portfolio_mock("about.html", en_html, {"about.es.html": es_html})
    fetched = {
        "about.html": {"html": en_html, "sha": "aaa"},
        "about.es.html": {"html": es_html, "sha": "bbb"},
    }

    changed = _fix_commented_blocks_inplace(portfolio, fetched, "main")

    assert changed == []


# ── Unit tests: _list_en_pages ────────────────────────────────────────────────

def _make_root_listing(*names):
    """Create a portfolio mock whose root listing returns the given filenames."""
    portfolio = MagicMock()
    items = []
    for name in names:
        m = MagicMock()
        m.name = name
        items.append(m)
    portfolio.get_contents.return_value = items
    return portfolio


def test_list_en_pages_filters_correctly():
    """Only EN html pages should be returned; lang variants and 404 excluded."""
    portfolio = _make_root_listing(
        "index.html", "about.html", "work.html",
        "index.es.html", "work.de.html",
        "404.html", "style.css",
    )
    pages = _list_en_pages(portfolio, "main")
    assert set(pages) == {"index.html", "about.html", "work.html"}


def test_list_en_pages_fallback_on_error():
    """If the API call fails, fall back to [PORTFOLIO_FILE] without raising."""
    from audit import PORTFOLIO_FILE
    portfolio = MagicMock()
    portfolio.get_contents.side_effect = Exception("API error")
    pages = _list_en_pages(portfolio, "main")
    assert pages == [PORTFOLIO_FILE]


# ── Integration tests: phase runners ─────────────────────────────────────────

@patch("audit._fix_card_content_inplace", return_value=["work.html"])
@patch("audit._fix_links_inplace", return_value=["work.html", "work.es.html"])
def test_run_phase_1_returns_combined_changes(mock_links, mock_content):
    """run_phase_1 should aggregate changed files from both link and content helpers."""
    g = MagicMock()
    llm = MagicMock()
    portfolio = MagicMock()
    fetched = _make_fetched(CARD_SINGLE)

    changed = run_phase_1(g, llm, portfolio, fetched, "main")

    assert "work.html" in changed
    assert "work.es.html" in changed
    mock_links.assert_called_once_with(g, fetched)
    mock_content.assert_called_once_with(g, llm, fetched)


@patch("audit._fix_card_content_inplace", return_value=[])
@patch("audit._fix_links_inplace", return_value=[])
def test_run_phase_1_no_changes(mock_links, mock_content):
    """run_phase_1 returns an empty list when nothing changes."""
    g = MagicMock()
    llm = MagicMock()
    portfolio = MagicMock()
    fetched = _make_fetched(CARD_SINGLE)

    changed = run_phase_1(g, llm, portfolio, fetched, "main")
    assert changed == []


@patch("audit._fix_commented_blocks_inplace", return_value=["work.es.html"])
@patch("audit._fix_order_inplace", return_value=[])
@patch("audit._fix_styling_inplace", return_value=["work.html"])
def test_run_phase_2_returns_combined_changes(mock_style, mock_order, mock_drift):
    """run_phase_2 should aggregate changed files from all three structure helpers."""
    portfolio = MagicMock()
    fetched = _make_fetched(CARD_SINGLE)

    changed = run_phase_2(portfolio, fetched, "main")

    assert "work.html" in changed
    assert "work.es.html" in changed
    mock_style.assert_called_once_with(fetched)
    mock_order.assert_called_once_with(fetched)
    mock_drift.assert_called_once_with(portfolio, fetched, "main")


@patch("audit._fix_commented_blocks_inplace", return_value=[])
@patch("audit._fix_order_inplace", return_value=[])
@patch("audit._fix_styling_inplace", return_value=[])
def test_run_phase_2_no_changes(mock_style, mock_order, mock_drift):
    """run_phase_2 returns an empty list when all structure checks are clean."""
    changed = run_phase_2(MagicMock(), _make_fetched(CARD_SINGLE), "main")
    assert changed == []


def test_run_phase_3_populates_fetched_and_returns_changed():
    """run_phase_3 should call _sync_file for each EN page and record updated files."""
    translated_html = "<section><h2>Über mich</h2><p>Ich bin Entwicklerin.</p></section>"

    # Portfolio root lists two EN pages
    root_items = []
    for name in ("index.html", "about.html"):
        m = MagicMock()
        m.name = name
        root_items.append(m)
    portfolio = MagicMock()
    portfolio.get_contents.return_value = root_items

    llm = MagicMock()
    fetched = {}

    with patch(
        "sync_translations._sync_file",
        side_effect=[
            {},                                          # index.html — in sync
            {"about.de.html": translated_html},          # about.html — one section added
        ],
    ) as mock_sync:
        changed = run_phase_3(llm, portfolio, fetched, "main")

    assert "about.de.html" in changed
    assert fetched["about.de.html"]["html"] == translated_html
    assert mock_sync.call_count == 2


def test_run_phase_3_no_changes():
    """run_phase_3 returns empty list when all translations are in sync."""
    root_items = []
    for name in ("index.html",):
        m = MagicMock()
        m.name = name
        root_items.append(m)
    portfolio = MagicMock()
    portfolio.get_contents.return_value = root_items

    with patch("sync_translations._sync_file", return_value={}):
        changed = run_phase_3(MagicMock(), portfolio, {}, "main")

    assert changed == []
