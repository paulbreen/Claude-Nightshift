"""
qa.py — QA persona: validates work against acceptance criteria and merges PRs.
"""

import logging
from .base import BasePersona
from task_parser import Task
from worktree_manager import WorktreeManager
from github_client import GitHubClient

logger = logging.getLogger(__name__)


class QAPersona(BasePersona):
    persona_name = "qa"
    persona_emoji = "🧪"
    system_prompt = """You are a thorough QA engineer. Your job is to validate that implemented work meets the requirements.

Your responsibilities:
1. Verify every acceptance criterion is met
2. Check for obvious bugs, regressions, or missing functionality
3. Verify tests exist and are meaningful
4. Check for security issues, error handling, and edge cases
5. Validate the PR diff makes sense as a coherent change

You are the last gate before code is merged. Be thorough but fair.

Output format:
If the work PASSES QA:
QA_VERDICT: PASS
Then note what was verified.

If the work FAILS QA:
QA_VERDICT: FAIL
Then list specific, actionable issues that must be fixed.

Be specific. Reference file names and line numbers where possible."""

    def __init__(self, github: GitHubClient, config: dict, worktree_manager: WorktreeManager):
        super().__init__(github, config)
        self.worktree_manager = worktree_manager

    def execute(self, task: Task, worktree_path: str) -> str:
        """
        Run QA validation on a task.

        Args:
            task: The parsed task (must have pr_number set)
            worktree_path: Path to the worktree for running tests

        Returns:
            One of: "pass", "fail", "escalated", "failed"
        """
        if not task.pr_number:
            self.fail(task, "No pull request found for QA validation.")
            return "failed"

        logger.info(
            f"[QA] Validating PR #{task.pr_number} for "
            f"#{task.issue_number}: {task.title}"
        )

        # Run tests first if they exist
        test_results = self._run_tests(worktree_path)

        # Get PR diff and files
        diff = self.github.get_pr_diff(task.repo, task.pr_number)
        pr_files = self.github.get_pr_files(task.repo, task.pr_number)

        if not diff:
            self.fail(task, "Could not retrieve PR diff for QA.")
            return "failed"

        # Build prompt and invoke Claude
        prompt = self._build_prompt(task, diff, pr_files, test_results)
        success, output = self.invoke_claude(
            prompt, working_dir=worktree_path, max_turns=10,
        )

        if not success:
            self.fail(task, f"QA validation failed:\n```\n{output[:500]}\n```")
            return "failed"

        # Parse verdict
        if "QA_VERDICT: PASS" in output:
            notes = output.split("QA_VERDICT: PASS", 1)[-1].strip()
            self.comment(task, f"✅ **QA: Passed**\n\n{notes[:1500]}")
            return "pass"

        elif "QA_VERDICT: FAIL" in output:
            issues = output.split("QA_VERDICT: FAIL", 1)[-1].strip()
            task.qa_cycles += 1
            max_cycles = self.config.get("limits", {}).get("max_qa_cycles", 2)

            if task.qa_cycles >= max_cycles:
                self.escalate_to_human(
                    task,
                    f"QA has rejected this {task.qa_cycles} times. "
                    f"Latest issues:\n\n{issues[:1500]}",
                )
                return "escalated"

            self.comment(
                task,
                f"❌ **QA: Failed** (cycle {task.qa_cycles}/{max_cycles})\n\n"
                f"{issues[:2000]}"
            )
            self.transition(task, "development")
            return "fail"

        else:
            self.comment(task, f"**QA Notes:**\n\n{output[:2000]}")
            # Ambiguous — let architect decide
            self.transition(task, "code-review")
            return "fail"

    def merge(self, task: Task) -> bool:
        """
        Merge the PR and close the issue.

        Args:
            task: The parsed task

        Returns:
            True if merge was successful
        """
        if not task.pr_number:
            self.fail(task, "No PR to merge")
            return False

        # Check if human review is required
        if task.human_review:
            self.escalate_to_human(
                task,
                "This task requires human review before merge. "
                f"PR: {task.pr_url or f'#{task.pr_number}'}",
            )
            return False

        # Merge the PR
        merged = self.github.merge_pull_request(task.repo, task.pr_number)
        if not merged:
            self.fail(task, f"Failed to merge PR #{task.pr_number}")
            return False

        self.comment(
            task,
            f"🎉 **Merged!** PR #{task.pr_number} has been merged into main."
        )

        # Close the issue if it's a one-off task
        if task.schedule == "once":
            self.github.set_stage_label(task.issue_number, "done")
            self.github.close_issue(task.issue_number)
        else:
            # Recurring — remove stage labels, keep recurring + claude
            self.github.set_stage_label(task.issue_number, "done")
            self.github.add_label(task.issue_number, "recurring")

        logger.info(f"[QA] Merged and closed #{task.issue_number}")
        return True

    def _run_tests(self, worktree_path: str) -> str:
        """Attempt to run tests in the worktree. Returns results summary."""
        import subprocess
        import os

        results = []

        # Detect and run test frameworks
        test_commands = []

        if os.path.exists(os.path.join(worktree_path, "package.json")):
            test_commands.append(("npm test", ["npm", "test", "--", "--passWithNoTests"]))
        if os.path.exists(os.path.join(worktree_path, "pytest.ini")) or \
           os.path.exists(os.path.join(worktree_path, "pyproject.toml")) or \
           os.path.exists(os.path.join(worktree_path, "setup.py")):
            test_commands.append(("pytest", ["python", "-m", "pytest", "-v", "--tb=short"]))
        if os.path.exists(os.path.join(worktree_path, "Cargo.toml")):
            test_commands.append(("cargo test", ["cargo", "test"]))
        if os.path.exists(os.path.join(worktree_path, "go.mod")):
            test_commands.append(("go test", ["go", "test", "./..."]))

        if not test_commands:
            return "No test framework detected."

        for name, cmd in test_commands:
            try:
                result = subprocess.run(
                    cmd, cwd=worktree_path,
                    capture_output=True, text=True, timeout=300,
                )
                status = "✅ PASSED" if result.returncode == 0 else "❌ FAILED"
                output = result.stdout[-500:] if result.stdout else ""
                error = result.stderr[-500:] if result.stderr else ""
                results.append(
                    f"**{name}**: {status}\n"
                    f"```\n{output}\n{error}\n```"
                )
            except subprocess.TimeoutExpired:
                results.append(f"**{name}**: ⏰ Timed out after 5 minutes")
            except FileNotFoundError:
                results.append(f"**{name}**: ⚠️ Command not found")
            except Exception as e:
                results.append(f"**{name}**: ⚠️ Error: {e}")

        return "\n\n".join(results)

    def _build_prompt(
        self, task: Task, diff: str,
        pr_files: list[dict], test_results: str
    ) -> str:
        """Build the QA validation prompt."""
        max_diff = 10000
        truncated_diff = diff[:max_diff]
        if len(diff) > max_diff:
            truncated_diff += f"\n\n... ({len(diff) - max_diff} chars omitted)"

        # Summarise changed files
        file_summary = "\n".join(
            f"- `{f['filename']}` (+{f.get('additions', 0)}/-{f.get('deletions', 0)})"
            for f in pr_files[:30]
        )

        issue_context = self.get_issue_context(task)

        parts = [
            f"# QA Validation: {task.title}",
            f"\n## Issue #{task.issue_number} — PR #{task.pr_number}",
        ]

        if task.acceptance_criteria:
            parts.append(f"\n## Acceptance Criteria\n{task.acceptance_criteria}")

        if issue_context:
            parts.append(f"\n## Discussion & History\n{issue_context[:2000]}")

        if test_results:
            parts.append(f"\n## Test Results\n{test_results}")

        parts.append(f"\n## Files Changed\n{file_summary}")
        parts.append(f"\n## Diff\n```diff\n{truncated_diff}\n```")

        parts.append(
            "\n## Your Task\n"
            "Validate this PR against the acceptance criteria. "
            "Check for bugs, security issues, missing tests, and edge cases. "
            "Output QA_VERDICT: PASS or QA_VERDICT: FAIL followed by your notes."
        )

        return "\n".join(parts)
