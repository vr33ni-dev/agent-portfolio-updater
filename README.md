# Portfolio Updater Agent

A LangGraph agent that reads your GitHub repos, generates portfolio-ready project cards, and keeps your GitHub Pages site up to date across English, Spanish, and German — opening a PR for every change.

## Project Structure

| File | Purpose |
|------|---------|
| `graph.py` | LangGraph graph definition |
| `main.py` | Add or update a single repo on the portfolio |
| `audit.py` | Check and fix all existing portfolio cards in one pass |
| `review.py` | Shared interactive card review loop |
| `read_repo.py` | LangGraph node — fetch repo info + code context |
| `generate_summary.py` | LangGraph node — generate EN/ES/DE cards with Claude |
| `critique.py` | LangGraph node — review card accuracy, structure, length |
| `update_portfolio.py` | LangGraph node — insert or replace card in all 3 HTML files |
| `create_pr.py` | LangGraph node — push branch + open PR |
| `state.py` | LangGraph shared state definition |

## How It Works

### Single project (`main.py`)

```
┌──────────────┐
│    START     │
└──────┬───────┘
       ▼
┌──────────────┐
│  Read Repo   │  ← README, languages, topics, key config files (package.json, requirements.txt, etc.)
└──────┬───────┘
       ▼
┌──────────────┐
│  Generate    │  ← LLM writes project cards in EN / ES / DE
│  Summary     │◄─────────────────────────┐
└──────┬───────┘                          │ retry with feedback
       ▼                                  │
┌──────────────┐                          │
│  Critique    │  ← LLM checks accuracy   │
│              │    against README +       │
│              │    code context           │
└──────┬───────┘                          │
       │ REJECTED (max 3 retries) ────────┘
       │ APPROVED
       ▼
┌──────────────┐
│    PAUSE     │  ← You review: y / n / edit / improve
└──────┬───────┘
       ▼
┌──────────────┐
│   Update     │  ← Insert or replace card in work.html / work.es.html / work.de.html
│  Portfolio   │    Position in ES/DE matches EN order
└──────┬───────┘
       ▼
┌──────────────┐
│  Create PR   │  ← Branch + commit + PR (reuses existing open PR if present)
└──────────────┘
```

### Card Review Options

```
  y       — looks good, proceed
  n       — abort, no changes
  edit    — paste your own version
  improve — describe what to change, agent rewrites card only
```

**improve** lets you give natural language feedback (e.g. *"mention the PWA support and shorten the description"*) — the agent refines the existing card and shows it again. This loops until you approve.

### Audit (`audit.py`)

Runs a targeted pass over all cards — no full regeneration unless actually needed:

| Check | Method |
|-------|--------|
| Transferred/stale repo URLs | String replace, no LLM |
| Tailwind CSS class consistency | Regex patch, no LLM |
| Card order in ES/DE vs EN | Structural reorder, no LLM |
| Tech stack subtitle accuracy | LLM: KEEP or corrected string |
| Description paragraph accuracy | LLM: generate → critique loop (up to 3 retries) → your review |

All changes are committed together in one PR. If an open audit PR already exists, it pushes to that branch instead.

## Setup

```bash
git clone https://github.com/yourusername/agent-portfolio-updater.git
cd agent-portfolio-updater

python3.12 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your keys
```

### API Keys

| Key | Where to get it |
|-----|----------------|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) |
| `GITHUB_TOKEN` | [github.com/settings/tokens](https://github.com/settings/tokens) — classic token with `repo` scope |

### Prepare Your Portfolio

Add this HTML comment to `work.html`, `work.es.html`, and `work.de.html` where new cards should be inserted:

```html
<!-- NEW_PROJECTS_HERE -->
```

### Configure

In `main.py` and `audit.py`:

```python
PORTFOLIO_REPO = "yourusername/portfolio"
```

In `create_pr.py`:

```python
PR_REVIEWER = "yourusername"
```

## Usage

### Add or update a single project

```bash
python main.py username/repo-name
```

### Audit all existing cards

```bash
python audit.py
```

The audit will check every card, print what changed, and ask for confirmation before pushing.

## Example Output

```
🔗 Checking links...
    ✅ All links are current

🎨 Checking styling...
    ✅ Styling is consistent

🔀 Checking card order...
    ✅ work.es.html already in correct order
    🔀 Reordered work.de.html

⚙️  Checking card content (tech stack + description)...
    FRESH  eisbachtracker
    STALE  morning-briefing
       Tech stack:
         Current:  Python · OpenAI
         Proposed: Python · LangGraph · OpenAI · REST APIs
         Accept? [y/n/edit] y
       Description:
       ────────────────────────────────────────────────────────────
       Automates a daily morning briefing using LangGraph and
       OpenAI, fetching news, weather, and calendar events.
         • Built with LangGraph for agent orchestration
         • Sends briefing via email every morning
       ────────────────────────────────────────────────────────────
         Accept? [y/n/improve] y

2 file(s) updated: work.de.html, work.html
Push changes to PR? [y/N] y

✅ PR: https://github.com/vr33ni/portfolio/pull/12
```

## Built With

- [LangGraph](https://github.com/langchain-ai/langgraph) — Agent orchestration
- [PyGithub](https://github.com/PyGithub/PyGithub) — GitHub API client
- [Claude](https://www.anthropic.com/) — Card generation, critique, targeted rewrites
