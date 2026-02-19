"""
task_runner.py — Orchestrates the full lifecycle of a task through all personas.

Flow: Triage → Design → Develop → PR → Code Review → Tag Human
Each stage is owned by a persona. Communication happens via GitHub issue comments.
"""

import logging
from typing import Optional
from task_parser import Task, parse_issue
from github_client import GitHubClient
from worktree_manager import WorktreeManager
from recurring import RecurringTracker
from personas import (
    ProductOwnerPersona,
    ArchitectPersona,
    DeveloperPersona,
)

logger = logging.getLogger(__name__)


class TaskRunner:
    """Runs a single task through its full lifecycle."""

    def __init__(
        self,
        github: GitHubClient,
        worktree_manager: WorktreeManager,
        recurring: RecurringTracker,
        config: dict,
    ):
        self.github = github
        self.worktree = worktree_manager
        self.recurring = recurring
        self.config = config

        # Initialize personas
        self.product_owner = ProductOwnerPersona(github, config)
        self.architect = ArchitectPersona(github, config, worktree_manager)
        self.developer = DeveloperPersona(github, config, worktree_manager)

    def run(self, issue: dict) -> bool:
        """
        Run a task through its lifecycle.

        This is the main entry point. It picks up wherever the task
        currently is in the pipeline and drives it forward.

        Args:
            issue: Raw GitHub issue dict

        Returns:
            True if the task completed (done or failed), False if blocked
        """
        task = parse_issue(issue)
        logger.info(
            f"▶ Running task #{task.issue_number}: {task.title} "
            f"(stage: {task.current_stage})"
        )

        # Swap from 'ready' to first stage
        if task.current_stage == "triage" and "ready" in [
            l["name"] for l in issue.get("labels", [])
        ]:
            self.github.remove_label(task.issue_number, "ready")
            self.github.set_stage_label(task.issue_number, "triage")

        worktree_path = None

        try:
            # Drive the task through stages
            result = self._drive(task)

            if result == "done":
                logger.info(f"✅ Task #{task.issue_number} completed successfully")
                # Record if recurring
                if task.schedule != "once":
                    self.recurring.record_run(task.issue_number, task.schedule)
                return True

            elif result == "blocked":
                logger.info(f"⏸ Task #{task.issue_number} is blocked (awaiting human)")
                return False

            elif result == "failed":
                logger.info(f"❌ Task #{task.issue_number} failed")
                return True

            else:
                logger.warning(f"❓ Task #{task.issue_number} ended in unexpected state: {result}")
                return False

        except Exception as e:
            logger.exception(f"💥 Unhandled error on task #{task.issue_number}")
            try:
                self.github.post_persona_comment(
                    task.issue_number, "system",
                    f"❌ **Unhandled Error**\n\n```\n{str(e)[:500]}\n```"
                )
                self.github.set_stage_label(task.issue_number, "failed")
            except Exception:
                pass
            return True

        finally:
            # Always clean up worktrees
            self.worktree.cleanup_all()

    def handle_human_response(self, issue: dict):
        """
        Process a human's response on an awaiting-human issue.

        Checks the latest comment for approve/changes keywords and acts accordingly:
        - Approve: merge the PR, set label to 'done', close the issue.
        - Changes: move back to 'development' stage for the pipeline to re-run.
        """
        task = parse_issue(issue)
        issue_num = task.issue_number
        logger.info(f"Handling human response on #{issue_num}")

        comments = self.github.get_issue_comments(issue_num)
        if not comments:
            return

        latest_body = comments[-1].get("body", "").lower().strip()

        approve_keywords = ["approved", "approve", "lgtm", "merge", "looks good", "ship it"]
        changes_keywords = ["changes", "fix", "update", "revise"]

        is_approve = any(kw in latest_body for kw in approve_keywords)
        is_changes = any(kw in latest_body for kw in changes_keywords)

        if is_approve:
            # Find and merge the PR
            pr_number = task.pr_number or self._find_pr_number(task)
            if pr_number:
                merged = self.github.merge_pull_request(task.repo, pr_number)
                if merged:
                    self.github.post_persona_comment(
                        issue_num, "system",
                        f"✅ PR #{pr_number} merged. Closing issue."
                    )
                else:
                    self.github.post_persona_comment(
                        issue_num, "system",
                        f"⚠️ Failed to merge PR #{pr_number}. Please merge manually."
                    )
            else:
                self.github.post_persona_comment(
                    issue_num, "system",
                    "⚠️ Could not find a PR to merge."
                )

            self.github.set_stage_label(issue_num, "done")
            self.github.close_issue(issue_num)
            logger.info(f"✅ #{issue_num} approved — PR merged, issue closed")

        elif is_changes:
            self.github.set_stage_label(issue_num, "ready")
            self.github.post_persona_comment(
                issue_num, "system",
                "🔄 Human requested changes. Moving back to **ready** for re-processing."
            )
            logger.info(f"🔄 #{issue_num} — changes requested, moved back to ready")

        else:
            logger.info(
                f"#{issue_num} — human comment didn't match approve/changes keywords, skipping"
            )

    def _drive(self, task: Task) -> str:
        """
        Drive a task through its stages until it completes, blocks, or fails.

        Returns:
            One of: "done", "blocked", "failed"
        """
        max_iterations = 20  # Safety limit to prevent infinite loops
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            logger.info(
                f"  Stage: {task.current_stage} "
                f"(iteration {iteration}/{max_iterations})"
            )

            if task.current_stage == "triage":
                result = self._run_triage(task)

            elif task.current_stage == "design":
                result = self._run_design(task)

            elif task.current_stage == "development":
                result = self._run_development(task)

            elif task.current_stage == "code-review":
                result = self._run_code_review(task)

            elif task.current_stage in ("done", "failed"):
                return task.current_stage

            elif task.current_stage == "awaiting-human":
                return "blocked"

            else:
                logger.error(f"Unknown stage: {task.current_stage}")
                return "failed"

            # Check result
            if result == "continue":
                continue
            elif result in ("done", "blocked", "failed"):
                return result
            else:
                continue

        logger.error(f"Task #{task.issue_number} hit max iterations ({max_iterations})")
        self.github.post_persona_comment(
            task.issue_number, "system",
            f"⚠️ Task exceeded maximum iterations ({max_iterations}). "
            "This may indicate an infinite loop. Marking as failed."
        )
        self.github.set_stage_label(task.issue_number, "failed")
        return "failed"

    # ─── Stage Handlers ─────────────────────────────────────────────────

    def _run_triage(self, task: Task) -> str:
        """Run the Product Owner triage stage."""
        success = self.product_owner.execute(task)
        if not success:
            return "failed"
        # Task's current_stage was updated by the persona
        if task.current_stage == "awaiting-human":
            return "blocked"
        return "continue"

    def _run_design(self, task: Task) -> str:
        """Run the Architect design stage."""
        # Set up the worktree for the architect to inspect the codebase
        worktree_path = self._ensure_worktree(task)
        if not worktree_path:
            return "failed"

        success = self.architect.execute_design(task, worktree_path)
        if not success:
            return "failed"
        return "continue"

    def _run_development(self, task: Task) -> str:
        """Run the Developer implementation stage."""
        worktree_path = self._ensure_worktree(task)
        if not worktree_path:
            return "failed"

        is_revision = task.review_cycles > 0 or task.qa_cycles > 0
        success = self.developer.execute(task, worktree_path, is_revision=is_revision)
        if not success:
            return "failed"

        # Create or update the PR
        if not task.pr_number:
            pr_created = self._create_pr(task)
            if not pr_created:
                return "failed"

        # Move to code review
        self.github.set_stage_label(task.issue_number, "code-review")
        task.current_stage = "code-review"
        return "continue"

    def _run_code_review(self, task: Task) -> str:
        """Run the Architect code review stage."""
        # Ensure we have the PR number
        if not task.pr_number:
            task.pr_number = self._find_pr_number(task)
            if not task.pr_number:
                self.github.post_persona_comment(
                    task.issue_number, "system",
                    "❌ Cannot find PR for code review."
                )
                self.github.set_stage_label(task.issue_number, "failed")
                return "failed"

        verdict = self.architect.execute_review(task)

        if verdict == "approved":
            # Tag the human for final review and merge
            self.github.tag_human(
                task.issue_number, "architect",
                f"Code review passed. PR is ready for your review.\n\n"
                f"**PR:** {task.pr_url or f'#{task.pr_number}'}",
            )
            return "blocked"
        elif verdict == "changes_required":
            return "continue"  # Will loop back to development
        elif verdict == "escalated":
            return "blocked"
        else:
            return "failed"

    # ─── Helpers ─────────────────────────────────────────────────────────

    def _ensure_worktree(self, task: Task) -> Optional[str]:
        """Ensure a worktree exists for the task, creating repo if needed."""
        try:
            # Create new repo if needed
            if task.new_repo:
                existing = self.github._request(
                    "GET", f"https://api.github.com/repos/{task.repo}"
                )
                if not existing:
                    logger.info(f"Creating new repo: {task.repo}")
                    self.github.create_repo(
                        task.target_repo_name,
                        description=task.repo_description,
                        private=task.private,
                    )

            # Get the default branch
            default_branch = self.github.get_default_branch(task.repo)

            # Create worktree
            worktree_path = self.worktree.create_worktree(
                task.repo,
                task.branch_name,
                base_branch=default_branch,
                issue_number=task.issue_number,
            )
            return worktree_path

        except Exception as e:
            logger.error(f"Failed to set up worktree: {e}")
            self.github.post_persona_comment(
                task.issue_number, "system",
                f"❌ Failed to set up working environment:\n```\n{str(e)[:500]}\n```"
            )
            self.github.set_stage_label(task.issue_number, "failed")
            return None

    def _create_pr(self, task: Task) -> bool:
        """Create a pull request for the task."""
        default_branch = self.github.get_default_branch(task.repo)

        pr_body = (
            f"## Closes #{task.issue_number}\n\n"
            f"**Task:** {task.title}\n\n"
            f"This PR was generated by the Claude Task Runner.\n"
            f"See the [issue]({task.issue_url}) for full context and discussion."
        )

        pr = self.github.create_pull_request(
            repo=task.repo,
            title=f"{task.title} (#{task.issue_number})",
            body=pr_body,
            head=task.branch_name,
            base=default_branch,
        )

        if pr:
            task.pr_number = pr["number"]
            task.pr_url = pr["html_url"]
            self.developer.comment(
                task,
                f"📬 **PR opened:** {task.pr_url}"
            )
            return True

        logger.error(f"Failed to create PR for #{task.issue_number}")
        return False

    def _find_pr_number(self, task: Task) -> Optional[int]:
        """Find an existing PR for this task's branch."""
        url = f"https://api.github.com/repos/{task.repo}/pulls"
        params = {"head": f"{task.target_owner}:{task.branch_name}", "state": "open"}
        prs = self.github._request("GET", url, params=params)
        if prs and len(prs) > 0:
            pr = prs[0]
            task.pr_url = pr["html_url"]
            return pr["number"]
        return None
