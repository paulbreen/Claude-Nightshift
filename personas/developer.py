"""
developer.py — Developer persona: implements code using Claude CLI in YOLO mode.
"""

import logging
from .base import BasePersona
from task_parser import Task
from worktree_manager import WorktreeManager
from github_client import GitHubClient

logger = logging.getLogger(__name__)


class DeveloperPersona(BasePersona):
    persona_name = "developer"
    persona_emoji = "💻"
    system_prompt = """You are an expert software developer. You write clean, well-tested, production-quality code.

Your responsibilities:
1. Follow the architect's implementation plan exactly
2. Write clean, readable code following project conventions
3. Write or update tests for your changes
4. Handle edge cases and error conditions
5. Ensure the code builds and tests pass

Guidelines:
- Follow existing project conventions and patterns
- Write meaningful commit messages
- Don't introduce unnecessary dependencies
- Add comments for complex logic only
- Make sure all tests pass before considering the work done
- If tests exist, run them. If no test framework is set up, note it but don't block on it.

If you encounter a blocker that prevents completion, clearly describe what's blocking you."""

    def __init__(self, github: GitHubClient, config: dict, worktree_manager: WorktreeManager):
        super().__init__(github, config)
        self.worktree_manager = worktree_manager

    def execute(self, task: Task, worktree_path: str, is_revision: bool = False) -> bool:
        """
        Implement the task in the worktree.

        Args:
            task: The parsed task
            worktree_path: Path to the git worktree
            is_revision: True if this is a revision after code review

        Returns:
            True if code was written and pushed successfully
        """
        action = "Revising" if is_revision else "Implementing"
        logger.info(
            f"[Developer] {action} #{task.issue_number}: {task.title} "
            f"in {worktree_path}"
        )

        # Build the prompt with all context
        prompt = self._build_prompt(task, worktree_path, is_revision)

        # Invoke Claude CLI in the worktree — this is YOLO mode
        # Claude will directly modify files in the worktree
        success, output = self.invoke_claude(
            prompt,
            working_dir=worktree_path,
        )

        if not success:
            self.fail(
                task,
                f"Development {'revision' if is_revision else 'implementation'} "
                f"failed:\n```\n{output[:500]}\n```"
            )
            return False

        # Commit and push changes
        commit_msg = (
            f"{'fix' if is_revision else 'feat'}: "
            f"{task.title} (#{task.issue_number})"
        )
        has_changes = self.worktree_manager.commit_and_push(worktree_path, commit_msg)

        if not has_changes and not is_revision:
            self.fail(task, "Developer produced no changes to the codebase.")
            return False

        if not has_changes and is_revision:
            self.comment(task, "No additional changes needed based on review feedback.")

        # Post update
        summary = self._extract_summary(output)
        if is_revision:
            self.comment(task, f"🔧 **Revision pushed**\n\n{summary}")
        else:
            self.comment(task, f"🚀 **Implementation pushed**\n\n{summary}")

        return True

    def _build_prompt(self, task: Task, worktree_path: str, is_revision: bool) -> str:
        """Build the implementation prompt."""
        # Get all conversation history — this includes the architect's plan
        # and any review feedback
        issue_context = self.get_issue_context(task)

        parts = [f"# {'Revision' if is_revision else 'Implementation'}: {task.title}"]

        if is_revision:
            parts.append(
                "\n**IMPORTANT:** This is a revision based on code review feedback. "
                "Read the review comments carefully and address ALL requested changes. "
                "Focus only on what was asked — don't refactor unrelated code."
            )

        parts.append(f"\n## Issue #{task.issue_number}")

        if task.full_prompt:
            parts.append(f"\n## Original Task\n{task.full_prompt}")

        if issue_context:
            parts.append(
                f"\n## Conversation History (includes design plan and review feedback)"
                f"\n{issue_context[:4000]}"
            )

        parts.append(
            "\n## Instructions\n"
            "You are working in a git worktree. Make all necessary code changes "
            "to implement the task. Follow the architect's plan. "
            "Run tests if they exist. Do not commit — commits are handled externally.\n\n"
            "Focus on:\n"
            "- Writing clean, working code\n"
            "- Following project conventions\n"
            "- Writing/updating tests\n"
            "- Handling edge cases"
        )

        return "\n".join(parts)

    def _extract_summary(self, output: str, max_length: int = 1500) -> str:
        """Extract a useful summary from Claude CLI output."""
        # Take the last portion of the output as it's usually the summary
        if len(output) <= max_length:
            return output

        # Try to find a natural break point
        truncated = output[-max_length:]
        newline_pos = truncated.find("\n")
        if newline_pos > 0 and newline_pos < 200:
            truncated = truncated[newline_pos + 1:]

        return f"...\n{truncated}"
