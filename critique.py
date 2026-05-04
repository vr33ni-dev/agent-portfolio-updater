import os
from langchain_anthropic import ChatAnthropic
from state import PortfolioState

MAX_RETRIES = 3

llm = ChatAnthropic(
    model="claude-sonnet-4-20250514",
    temperature=0,
    api_key=os.getenv("ANTHROPIC_API_KEY"),
)


def critique(state: PortfolioState) -> dict:
    """Review the generated card and either approve it or return feedback for a retry."""
    if state.get("skip_critique"):
        return {"critique_feedback": "", "critique_retries": 0, "skip_critique": False}

    repo = state["repo_info"]
    card_html = state["summary_html"]  # critique only the EN version

    prompt = f"""You are reviewing a project card for a developer portfolio website.

Evaluate the card against these criteria:
1. **Accuracy** — does it correctly reflect the repo's purpose and tech stack?
2. **Structure** — does it use the correct Tailwind CSS classes (bg-white/dark:bg-gray-800, rounded-xl, shadow-md, p-6, text-xl font-semibold, text-sm text-gray-500, list-disc list-inside, text-blue-500 hover:underline)?
3. **Length** — description should be 2-3 sentences, 2-3 bullet points, not more
4. **No raw README** — should NOT just be a copy of the README intro
5. **GitHub link** — must include a working link to each repo URL

REPO INFO:
Name: {repo['name']}
Description: {repo['description']}
Languages: {', '.join(repo['languages'])}
URL(s): {', '.join(repo.get('urls', [repo['url']]))}

README (first 2000 chars):
{repo['readme'][:2000]}

CODE CONTEXT (key config/manifest files):
{repo.get('code_context', '')[:2000]}

GENERATED CARD:
{card_html}

Respond with exactly two lines:
Line 1: APPROVED or REJECTED
Line 2: If REJECTED, one concise sentence of specific feedback for improvement. If APPROVED, write "Looks good."
"""

    response = llm.invoke(prompt)
    lines = response.content.strip().splitlines()
    verdict = lines[0].strip().upper()
    feedback = lines[1].strip() if len(lines) > 1 else ""

    retries = state.get("critique_retries", 0)

    if verdict == "APPROVED" or retries >= MAX_RETRIES:
        if retries >= MAX_RETRIES and verdict != "APPROVED":
            print(f"  ⚠️  Max critique retries reached — proceeding with last generated card")
        else:
            print(f"  ✅ Card approved by critique (after {retries} retry/retries)")
        return {"critique_feedback": "", "critique_retries": retries}

    print(f"  🔁 Critique retry {retries + 1}/{MAX_RETRIES}: {feedback}")
    return {"critique_feedback": feedback, "critique_retries": retries + 1}


def should_retry(state: PortfolioState) -> str:
    """Routing function: retry generate_summary or proceed to update_portfolio."""
    if state.get("critique_feedback"):
        return "generate_summary"
    return "update_portfolio"
