import os
from langchain_anthropic import ChatAnthropic
from state import PortfolioState

llm = ChatAnthropic(
    model="claude-sonnet-4-20250514",
    temperature=0.7,
    api_key=os.getenv("ANTHROPIC_API_KEY"),
)


def generate_summary(state: PortfolioState) -> dict:
    """Use LLM to generate a portfolio-ready project card in HTML."""
    repo = state["repo_info"]

    prompt = f"""You are helping a developer update their GitHub portfolio website.

Based on the following repo info, generate a short, compelling project card in HTML.
The card should include:
- Project name as a link to the repo
- A 2-3 sentence description that sounds professional (not just the README intro)
- Tech stack as small tags/badges
- What makes this project interesting or unique

REPO INFO:
Name: {repo['name']}
Description: {repo['description']}
Languages: {', '.join(repo['languages'])}
Topics: {', '.join(repo['topics'])}
Created: {repo['created_at']}
URL: {repo['url']}

README (first 2000 chars):
{repo['readme'][:2000]}

Return ONLY the HTML for a single project card using this structure.
Do not include any markdown, backticks, or explanation. Just raw HTML.
Use simple, clean HTML with inline classes that work with most Jekyll themes.
Example structure:

<div class="project-card">
  <h3><a href="REPO_URL">Project Name</a></h3>
  <p>Description here.</p>
  <div class="project-tags">
    <span class="tag">Python</span>
    <span class="tag">LangGraph</span>
  </div>
</div>
"""

    response = llm.invoke(prompt)
    return {"summary_html": response.content}
