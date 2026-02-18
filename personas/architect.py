"""
architect.py — Architect persona: designs solutions and performs code reviews.
"""

import logging
from .base import BasePersona
from task_parser import Task
from worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


class ArchitectPersona(BasePersona):
    persona_name = "architect"
    persona_emoji = "🏗️"
    system_prompt = """You are a senior software architect. You have two modes of operation:

MODE 1 — DESIGN:
When given a task to design, you:
1. Analyze the requirements and the existing codebase structure
2. Produce a clear, actionable implementation plan
3. Specify which files to create, modify, or delete
4. Define the approach, patterns, and conventions to follow
5. Note any risks, trade-offs, or prerequisites

Your design output should be specific enough that a developer can implement it without ambiguity.

Output format for design:
DESIGN_PLAN:
Then provide your structured plan.

MODE 2 — CODE REVIEW:
When reviewing a pull request diff, you:
1. Check the code against the original requirements and design plan
2. Verify correctness, readability, and maintainability
3. Check for bugs, security issues, and edge cases
4. Verify tests are adequate
5. Ensure conventions and patterns are followed

Output format for code review:
If the code is APPROVED:
REVIEW_VERDICT: APPROVED
Then provide any minor notes.

If changes are REQUIRED:
REVIEW_VERDICT: CHANGES_REQUIRED
Then list specific, actionable changes needed.

Be thorough but pragmatic. Don't block on style nitpicks."""

    def __init__(self, github, config, worktree_manager: WorktreeManager):
        super().__init__(github, config)
        self.worktree_manager = worktree_manager

    def execute_design(self, task: Task, worktree_path: str) -> bool:
        """
        Design an implementation plan for a task.

        Args:
            task: The parsed task
            worktree_path: Path to the worktree with the codebase

        Returns:
            True if design was produced successfully
        """
        logger.info(f"[Architect] Designing solution for #{task.issue_number}: {task.title}")

        prompt = self._build_design_prompt(task, worktree_path)
        success, output = self.invoke_claude(prompt, working_dir=worktree_path, max_turns=10)

        if not success:
            self.fail(task, f"Architecture design failed:\n```\n{output[:500]}\n```")
            return False

        # Post the design plan
        if "DESIGN_PLAN:" in output:
            plan = output.split("DESIGN_PLAN:", 1)[-1].strip()
        else:
            plan = output.strip()

        self.comment(task, f"📐 **Implementation Plan**\n\n{plan[:3000]}")
        self.transition(task, "development")
        return True

    def execute_review(self, task: Task) -> str:
        """
        Review a pull request.

        Args:
            task: The parsed task (must have pr_number set)

        Returns:
            One of: "approved", "changes_required", "failed"
        """
        if not task.pr_number:
            logger.error(f"[Architect] No PR number for review on #{task.issue_number}")
            self.fail(task, "No pull request found to review")
            return "failed"

        logger.info(
            f"[Architect] Reviewing PR #{task.pr_number} for "
            f"#{task.issue_number}: {task.title}"
        )

        # Get the PR diff
        diff = self.github.get_pr_diff(task.repo, task.pr_number)
        if not diff:
            self.fail(task, "Could not retrieve PR diff for review")
            return "failed"

        # Get the conversation context (includes design plan)
        issue_context = self.get_issue_context(task)

        prompt = self._build_review_prompt(task, diff, issue_context)
        success, output = self.invoke_claude(prompt, max_turns=5)

        if not success:
            self.fail(task, f"Code review failed:\n```\n{output[:500]}\n```")
            return "failed"

        if "REVIEW_VERDICT: APPROVED" in output:
            review_notes = output.split("REVIEW_VERDICT: APPROVED", 1)[-1].strip()
            self.comment(
                task,
                f"✅ **Code Review: Approved**\n\n{review_notes[:2000]}"
            )
            return "approved"

        elif "REVIEW_VERDICT: CHANGES_REQUIRED" in output:
            changes = output.split("REVIEW_VERDICT: CHANGES_REQUIRED", 1)[-1].strip()
            task.review_cycles += 1
            max_cycles = self.config.get("limits", {}).get("max_review_cycles", 3)

            if task.review_cycles >= max_cycles:
                self.escalate_to_human(
                    task,
                    f"Code review has gone through {task.review_cycles} cycles "
                    f"without resolution. Latest feedback:\n\n{changes[:1500]}",
                )
                return "escalated"

            self.comment(
                task,
                f"🔄 **Code Review: Changes Required** "
                f"(cycle {task.review_cycles}/{max_cycles})\n\n{changes[:2000]}"
            )
            self.transition(task, "development")
            return "changes_required"

        else:
            # Ambiguous — treat as needing changes
            self.comment(task, f"**Review Notes:**\n\n{output[:2000]}")
            self.transition(task, "development")
            return "changes_required"

    def _build_design_prompt(self, task: Task, worktree_path: str) -> str:
        """Build the design prompt with codebase context."""
        tree_summary = self.worktree_manager.get_tree_summary(worktree_path)

        parts = [
            f"# Architecture Design: {task.title}",
            f"\n## Issue #{task.issue_number}",
            f"**Target Repo:** {task.repo}",
            f"**New Repo:** {task.new_repo}",
        ]

        # Include issue context (product owner's refined requirements)
        issue_context = self.get_issue_context(task)
        if issue_context:
            parts.append(f"\n## Requirements & Discussion\n{issue_context}")

        if task.full_prompt:
            parts.append(f"\n## Original Task\n{task.full_prompt}")

        if tree_summary:
            parts.append(f"\n## Codebase Structure\n```\n{tree_summary[:2000]}\n```")

        parts.append(
            "\n## Your Task\n"
            "Review the codebase and requirements. Produce a detailed "
            "implementation plan that a developer can follow. "
            "Be specific about files, functions, and patterns.\n"
            "Output DESIGN_PLAN: followed by your plan."
        )

        return "\n".join(parts)

    def _build_review_prompt(
        self, task: Task, diff: str, issue_context: str
    ) -> str:
        """Build the code review prompt."""
        # Truncate diff if extremely large
        max_diff = 10000
        truncated = diff[:max_diff]
        if len(diff) > max_diff:
            truncated += f"\n\n... (diff truncated, {len(diff) - max_diff} chars omitted)"

        parts = [
            f"# Code Review: {task.title}",
            f"\n## Issue #{task.issue_number} — PR #{task.pr_number}",
        ]

        if task.acceptance_criteria:
            parts.append(f"\n## Acceptance Criteria\n{task.acceptance_criteria}")

        if issue_context:
            parts.append(f"\n## Design Plan & Discussion\n{issue_context[:3000]}")

        parts.append(f"\n## Pull Request Diff\n```diff\n{truncated}\n```")

        parts.append(
            "\n## Your Task\n"
            "Review this pull request against the requirements and design plan. "
            "Check for correctness, bugs, security issues, and test coverage.\n"
            "Output REVIEW_VERDICT: APPROVED or REVIEW_VERDICT: CHANGES_REQUIRED "
            "followed by your notes."
        )

        return "\n".join(parts)
