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

    card_template = """
<div class="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6">
  <h2 class="text-xl font-semibold mb-2">Project Name</h2>
  <p class="text-sm text-gray-500 dark:text-gray-400 mb-2">
    Tech · Stack · Here
  </p>
  <p class="mb-4">
    Description here.
  </p>
  <ul class="list-disc list-inside text-sm mb-4 space-y-1">
    <li><strong>Key point:</strong> Detail here</li>
    <li><strong>Key point:</strong> Detail here</li>
  </ul>
  <a href="REPO_URL" target="_blank" class="text-blue-500 hover:underline">View on GitHub</a>
</div>
<br />"""

    feedback = state.get("critique_feedback", "")
    user_improvement = state.get("user_improvement_feedback", "")
    current_card = state.get("summary_html", "")

    if user_improvement and current_card:
        feedback_section = f"\n\nThe user wants you to improve the existing card. Their request:\n{user_improvement}\n\nExisting card to refine (keep what works, only change what the user asked):\n{current_card}\n"
    elif feedback:
        feedback_section = f"\n\nPREVIOUS ATTEMPT WAS REJECTED. Feedback to address:\n{feedback}\n"
    else:
        feedback_section = ""

    base_prompt = f"""You are helping a developer update their GitHub portfolio website.

Based on the following repo info, generate a short, compelling project card in HTML.
The card should include:
- Project name as a heading
- Tech stack as a subtitle line (e.g. "Python · LangGraph · API Integration") — keep technical terms in English
- A 2-3 sentence description that sounds professional (not just the README intro)
- A bullet list of 2-3 key highlights
- A "View on GitHub" link (label translated to the target language)

REPO INFO:
Name: {repo['name']}
Description: {repo['description']}
Languages: {', '.join(repo['languages'])}
Topics: {', '.join(repo['topics'])}
Created: {repo['created_at']}
URL: {repo['url']}

README (first 2000 chars):
{repo['readme'][:2000]}

CODE CONTEXT (key config/manifest files):
{repo.get('code_context', '')[:2000]}
{feedback_section}
Return ONLY the HTML. No markdown, no backticks, no explanation.
Match this exact Tailwind CSS structure:
{card_template}
"""

    lang_instructions = [
        ("en", "Write the description and highlights in English."),
        ("es", "Write the description and highlights in Spanish. Keep technical terms (framework names, languages, tools) in English."),
        ("de", "Write the description and highlights in German. Keep technical terms (framework names, languages, tools) in English."),
    ]

    from concurrent.futures import ThreadPoolExecutor

    def _invoke_lang(lang_instr):
        lang, instruction = lang_instr
        return lang, llm.invoke(base_prompt + f"\nLanguage instruction: {instruction}").content

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = dict(executor.map(_invoke_lang, lang_instructions))

    return {
        "summary_html": results["en"],
        "summary_html_es": results["es"],
        "summary_html_de": results["de"],
        "user_improvement_feedback": "",  # Clear after use so critique retries don't re-apply it
        "critique_feedback": "",          # Clear sentinel so critique runs fresh
    }