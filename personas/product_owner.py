"""
product_owner.py — Product Owner persona: triages issues and refines requirements.
"""

import logging
from .base import BasePersona
from task_parser import Task

logger = logging.getLogger(__name__)


class ProductOwnerPersona(BasePersona):
    persona_name = "product_owner"
    persona_emoji = "🎯"
    system_prompt = """You are an experienced Product Owner. Your job is to triage incoming tasks and ensure they are well-defined before development begins.

Your responsibilities:
1. Read the task description, context, and acceptance criteria
2. Determine if the requirements are clear, specific, and actionable
3. If requirements are clear: produce a refined summary with clear deliverables
4. If requirements are unclear: list specific questions that need answering

When producing your output:
- Be concise and structured
- List clear, testable acceptance criteria
- Identify any risks or edge cases
- Note any dependencies on other systems or tasks
- If the task is large, suggest breaking it into smaller tasks
- Be pragmatic. For simple, well-defined tasks, approve them without over-analysing
- Don't block on trivial ambiguities like encoding, trailing newlines, or minor formatting details
- If the intent is clear, approve it and note any minor assumptions in your summary

Output format:
If the task is READY for development, output:
VERDICT: READY
Then provide your refined requirements summary.

If the task NEEDS CLARIFICATION, output:
VERDICT: NEEDS_CLARIFICATION
Then list your specific questions.

Do not write any code. Focus only on requirements clarity."""

    def execute(self, task: Task) -> bool:
        """
        Triage a task. Returns True if work moved forward.

        Args:
            task: The parsed task to triage

        Returns:
            True if task was processed successfully
        """
        logger.info(f"[Product Owner] Triaging issue #{task.issue_number}: {task.title}")

        # Build the prompt
        prompt = self._build_prompt(task)

        # Invoke Claude
        success, output = self.invoke_claude(prompt, max_turns=5)

        if not success:
            self.fail(task, f"Product Owner triage failed:\n```\n{output[:500]}\n```")
            return False

        # Parse the verdict
        if "VERDICT: READY" in output:
            # Extract everything after VERDICT: READY
            refined = output.split("VERDICT: READY", 1)[-1].strip()
            self.comment(task, f"✅ **Requirements Approved**\n\n{refined}")
            self.transition(task, "design")
            return True

        elif "VERDICT: NEEDS_CLARIFICATION" in output:
            questions = output.split("VERDICT: NEEDS_CLARIFICATION", 1)[-1].strip()
            self.escalate_to_human(
                task,
                f"Requirements need clarification:\n\n{questions}",
            )
            return True

        else:
            # Ambiguous output — post it and let the architect decide
            self.comment(task, f"**Triage Notes:**\n\n{output[:2000]}")
            self.transition(task, "design")
            return True

    def _build_prompt(self, task: Task) -> str:
        """Build the triage prompt from the task."""
        parts = [
            f"# Task Triage: {task.title}",
            f"\n## Issue #{task.issue_number}",
            f"**Target Repo:** {task.repo}",
            f"**New Repo:** {task.new_repo}",
            f"**Priority:** {task.priority}",
        ]

        if task.task_description:
            parts.append(f"\n## Task Description\n{task.task_description}")

        if task.context:
            parts.append(f"\n## Context\n{task.context}")

        if task.acceptance_criteria:
            parts.append(f"\n## Acceptance Criteria\n{task.acceptance_criteria}")

        # Include any existing conversation
        issue_context = self.get_issue_context(task)
        if issue_context:
            parts.append(f"\n## Previous Discussion\n{issue_context}")

        parts.append(
            "\n## Your Task\n"
            "Review the above and determine if the requirements are clear enough "
            "for an architect to design a solution and a developer to implement it. "
            "Output your VERDICT and analysis."
        )

        return "\n".join(parts)
