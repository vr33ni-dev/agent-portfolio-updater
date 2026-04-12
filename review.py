"""
Shared card review loop used by both main.py and audit.py.
After the graph pauses at update_portfolio, this shows the generated card
and lets the user: approve, abort, manually edit, or ask the agent to improve it.
"""
import re
import sys


def _card_to_text(html: str) -> str:
    """Strip HTML tags and render the card as readable plain text."""
    # Newline before block-level elements so content separates naturally
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</(p|div|h[1-6]|li|ul)>', '\n', html, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', '', html)
    # Collapse whitespace but preserve intentional newlines
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()]
    # Remove blank runs of more than one line
    result = []
    prev_blank = False
    for line in lines:
        if line == '':
            if not prev_blank:
                result.append('')
            prev_blank = True
        else:
            result.append(line)
            prev_blank = False
    return '\n'.join(result).strip()


def review_and_confirm(agent, config, repo_name: str = "") -> bool:
    """
    Show the generated EN card and ask for confirmation.
    Returns True if the graph should proceed, False if aborted.
    Loops if the user asks for an agent improvement or manual edit.
    """
    label = f" for {repo_name}" if repo_name else ""

    while True:
        state = agent.get_state(config).values
        print("\n" + "─" * 60)
        print(f"Generated card{label} — review before it goes to your portfolio:")
        print("─" * 60)
        print(_card_to_text(state["summary_html"]))
        print("─" * 60)
        print("\nOptions:")
        print("  y       — looks good, proceed")
        print("  n       — abort, no changes")
        print("  edit    — paste your own version")
        print("  improve — describe what to change, agent rewrites")
        choice = input("\nYour choice: ").strip().lower()

        if choice == "y":
            return True

        if choice in ("n", ""):
            print("Aborted. No changes made.")
            return False

        if choice == "edit":
            print("Paste your edited EN card HTML. Enter a line with just END when done:")
            lines = []
            while True:
                line = input()
                if line.strip() == "END":
                    break
                lines.append(line)
            agent.update_state(config, {"summary_html": "\n".join(lines)})
            return True

        if choice == "improve":
            feedback = input("Describe what to improve (e.g. 'make description shorter, mention Docker'): ").strip()
            if not feedback:
                print("No feedback entered, try again.")
                continue
            # Skip critique for user-driven rewrites — user is the quality gate
            agent.update_state(
                config,
                {"user_improvement_feedback": feedback, "critique_feedback": "__improve__", "critique_retries": 0, "skip_critique": True},
                as_node="critique",
            )
            # Run generate_summary → critique → interrupt again
            agent.invoke(None, config)
            # Loop back to show the new card
            continue

        print("Invalid choice, try again.")
