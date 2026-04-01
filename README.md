# Portfolio Updater Agent

A LangGraph agent that reads one of your GitHub repos, generates a portfolio-ready summary, adds it to your GitHub Pages site, and opens a PR for you to review.

## How It Works

```
┌──────────────┐
│    START      │
└──────┬───────┘
       ▼
┌──────────────┐
│  Read Repo   │  ← GitHub API: README, languages, topics
└──────┬───────┘
       ▼
┌──────────────┐
│  Generate    │  ← LLM writes a project card in HTML
│  Summary     │
└──────┬───────┘
       ▼
┌──────────────┐
│   Update     │  ← Inserts card into your portfolio page
│  Portfolio   │
└──────┬───────┘
       ▼
┌──────────────┐
│  Create PR   │  ← Branch + commit + PR on GitHub
└──────┬───────┘
       ▼
┌──────────────┐
│     END      │
└──────────────┘
```

Human-in-the-loop comes for free — the PR is your review step. Check the generated summary, tweak if needed, merge.

## Setup

```bash
git clone https://github.com/yourusername/agent-portfolio-updater.git
cd agent-portfolio-updater

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your keys
```

### API Keys Needed

| Key | Where to get it |
|-----|----------------|
| Anthropic API | [console.anthropic.com](https://console.anthropic.com/) |
| GitHub Token | [github.com/settings/tokens](https://github.com/settings/tokens) — needs `repo` scope |

### Prepare Your Portfolio

Add this HTML comment to your `index.html` where you want project cards inserted:

```html
<!-- NEW_PROJECTS_HERE -->
```

The agent will insert new project cards directly after this marker.

### Configure

Edit `main.py` and set your portfolio repo:

```python
PORTFOLIO_REPO = "yourusername/yourusername.github.io"
```

If your projects live on a different page than `index.html`, edit `PORTFOLIO_FILE` in both `nodes/update_portfolio.py` and `nodes/create_pr.py`.

## Usage

```bash
python main.py username/repo-name
```

Example:

```bash
python main.py vreeni/agent-morning-briefing
```

The agent will:
1. Read the repo's README, languages, and metadata
2. Generate a project card using Claude
3. Insert it into your portfolio page
4. Open a PR for you to review

## Example Output

```
🔍 Reading repo: vreeni/agent-morning-briefing
📝 Will update: vreeni/vreeni.github.io

✅ PR created: https://github.com/vreeni/vreeni.github.io/pull/42

🎉 Done! Review your PR at:
https://github.com/vreeni/vreeni.github.io/pull/42
```

## Stretch Goals

- [ ] **Critique loop**: Add a node that reviews the generated HTML and loops back if it doesn't match your site's style
- [ ] **Auto-detect style**: Read existing project cards to match formatting automatically
- [ ] **Screenshot**: Use a headless browser to generate a preview image of the card
- [ ] **Batch mode**: Run it on all repos at once to rebuild the entire portfolio
- [ ] **GitHub Action**: Trigger automatically when you create a new public repo

## Built With

- [LangGraph](https://github.com/langchain-ai/langgraph) — Agent orchestration
- [PyGithub](https://github.com/PyGithub/PyGithub) — GitHub API client
- [Claude](https://www.anthropic.com/) — Summary generation
