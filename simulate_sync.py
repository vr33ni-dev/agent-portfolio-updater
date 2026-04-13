"""
simulate_sync.py — Run _sync_file against a fake EN page with a missing section.

No GitHub API, no Anthropic API, no real portfolio files touched.
No commit or PR is opened at the end.
input() prompts are live so you can respond interactively.

Usage:
    python simulate_sync.py
"""

from unittest.mock import MagicMock, patch
from sync_translations import _sync_file

# ── Fake page content ─────────────────────────────────────────────────────────

EN_HTML = """\
<header>
  <nav>Portfolio</nav>
</header>
<section id="about">
  <h2 class="title">About Me</h2>
  <p>I'm a software engineer who loves building things.</p>
</section>
<section id="contact">
  <h2 class="title">Contact</h2>
  <p>You can reach me at hello@example.com or on LinkedIn.</p>
</section>
"""

# ES already has "About Me" but is missing "Contact"
ES_HTML = """\
<header>
  <nav>Portfolio</nav>
</header>
<section id="about">
  <h2 class="title">Sobre mí</h2>
  <p>Soy desarrolladora de software apasionada por construir cosas.</p>
</section>
"""

# DE already has "About Me" but is missing "Contact"
DE_HTML = """\
<header>
  <nav>Portfolio</nav>
</header>
<section id="about">
  <h2 class="title">Über mich</h2>
  <p>Ich bin eine Softwareentwicklerin, die gerne Dinge baut.</p>
</section>
"""

# Canned translations returned by the mock LLM
TRANSLATED: dict[str, str] = {
    "es": """\
<section id="contact">
  <h2 class="title">Contacto</h2>
  <p>Puedes contactarme en hello@example.com o en LinkedIn.</p>
</section>
""",
    "de": """\
<section id="contact">
  <h2 class="title">Kontakt</h2>
  <p>Du kannst mich unter hello@example.com oder auf LinkedIn erreichen.</p>
</section>
""",
}

# ── Mocks ─────────────────────────────────────────────────────────────────────

def _make_portfolio():
    """Mock GitHub repository with fake page files."""
    _pages: dict[str, str] = {
        "about.html":    EN_HTML,
        "about.es.html": ES_HTML,
        "about.de.html": DE_HTML,
    }

    def _get_contents(filename, ref=None):
        if filename not in _pages:
            raise Exception(f"file not found: {filename}")
        c = MagicMock()
        c.decoded_content = _pages[filename].encode()
        return c

    portfolio = MagicMock()
    portfolio.get_contents.side_effect = _get_contents
    return portfolio


def _make_llm():
    """Mock LLM that returns canned translations keyed by target language code."""
    call_count = {"n": 0}

    def side_effect(prompt):
        call_count["n"] += 1
        response = MagicMock()

        # Detect language from the lang_label injected by _translate()
        if "Spanish" in prompt:
            response.content = TRANSLATED["es"]
        elif "German" in prompt:
            response.content = TRANSLATED["de"]
        else:
            response.content = "<section><h2>Translated</h2><p>Content.</p></section>"

        print(f"  [mock LLM call #{call_count['n']}]")
        return response

    llm = MagicMock()
    llm.invoke.side_effect = side_effect
    return llm


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("simulate_sync.py")
    print("Simulating _sync_file for about.html (ES + DE)")
    print("  EN has: 'About Me' + 'Contact'")
    print("  ES/DE have: 'About Me' only  (Contact is missing)")
    print("=" * 60)
    print()

    portfolio = _make_portfolio()
    llm = _make_llm()

    updates = _sync_file(llm, portfolio, "about.html", "main")

    print()
    print("=" * 60)
    print("Simulation complete.")
    if updates:
        print(f"Files with accepted updates: {list(updates.keys())}")
        for fname, html in updates.items():
            print(f"\n── {fname} (final HTML, first 400 chars) ──")
            print(html[:400])
    else:
        print("No updates accepted (either rejected or already in sync).")
    print("=" * 60)


if __name__ == "__main__":
    main()
