"""
worktree_manager.py — Manage git repos, worktrees, branches, commits, and pushes.
"""

import os
import subprocess
import logging
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

WORK_DIR = os.environ.get("WORK_DIR", "/work")
REPOS_DIR = os.path.join(WORK_DIR, "repos")
WORKTREES_DIR = os.path.join(WORK_DIR, "worktrees")


class WorktreeManager:
    """Manages git repos and worktrees for task execution."""

    def __init__(self, github_token: str):
        self.github_token = github_token
        os.makedirs(REPOS_DIR, exist_ok=True)
        os.makedirs(WORKTREES_DIR, exist_ok=True)

        # Configure git globally
        self._run_git(["config", "--global", "user.name", "Claude Worker"])
        self._run_git(["config", "--global", "user.email", "claude-worker@noreply.github.com"])
        # Allow all directories
        self._run_git(["config", "--global", "--add", "safe.directory", "*"])

    def setup_repo(self, repo: str) -> str:
        """
        Clone or update a bare repo for use with worktrees.

        Args:
            repo: Full repo path e.g. "user/my-project"

        Returns:
            Path to the bare repo directory
        """
        repo_dir = os.path.join(REPOS_DIR, repo.replace("/", "_"))
        clone_url = f"https://x-access-token:{self.github_token}@github.com/{repo}.git"

        if os.path.exists(repo_dir):
            # Fetch latest (ignore errors for empty repos)
            logger.info(f"Fetching latest for {repo}")
            try:
                self._run_git(["fetch", "--all", "--prune"], cwd=repo_dir)
            except subprocess.CalledProcessError:
                logger.warning(f"Fetch failed for {repo} (may be empty), continuing")
        else:
            # Clone as bare repo (optimised for worktrees)
            logger.info(f"Cloning bare repo {repo}")
            try:
                self._run_git(["clone", "--bare", clone_url, repo_dir])
            except subprocess.CalledProcessError:
                # Empty repo — init bare and add remote
                logger.warning(f"Bare clone failed for {repo} (may be empty), initialising")
                os.makedirs(repo_dir, exist_ok=True)
                self._run_git(["init", "--bare"], cwd=repo_dir)
                self._run_git(["remote", "add", "origin", clone_url], cwd=repo_dir)

        return repo_dir

    def create_worktree(
        self, repo: str, branch_name: str, base_branch: str = "main",
        issue_number: Optional[int] = None
    ) -> str:
        """
        Create a git worktree for a task.

        Args:
            repo: Full repo path e.g. "user/my-project"
            branch_name: Branch to create (e.g. "claude/42")
            base_branch: Branch to base off (e.g. "main")
            issue_number: Issue number for directory naming

        Returns:
            Path to the worktree directory
        """
        repo_dir = self.setup_repo(repo)
        worktree_name = f"{repo.replace('/', '_')}_{issue_number or branch_name.replace('/', '_')}"
        worktree_path = os.path.join(WORKTREES_DIR, worktree_name)

        # Clean up existing worktree if present
        if os.path.exists(worktree_path):
            self.remove_worktree(repo, worktree_path)

        # Fetch to ensure we have latest refs (ignore errors for empty repos)
        try:
            self._run_git(["fetch", "--all"], cwd=repo_dir)
        except subprocess.CalledProcessError:
            logger.warning(f"Fetch failed (repo may be empty), continuing")

        # Check if the base branch exists (bare repos don't use origin/ prefix)
        base_ref = None
        for candidate in [f"origin/{base_branch}", base_branch]:
            check = self._run_git(
                ["rev-parse", "--verify", candidate],
                cwd=repo_dir, capture=True,
            )
            if check:
                base_ref = candidate
                break

        if base_ref:
            # Check if branch already exists (e.g. from a previous stage)
            branch_exists = self._run_git(
                ["rev-parse", "--verify", branch_name],
                cwd=repo_dir, capture=True,
            )
            if branch_exists:
                # Reuse existing branch
                self._run_git(
                    ["worktree", "add", worktree_path, branch_name],
                    cwd=repo_dir,
                )
            else:
                # Create new branch from base
                self._run_git(
                    ["worktree", "add", "-b", branch_name, worktree_path, base_ref],
                    cwd=repo_dir,
                )
        else:
            # Empty repo: create a regular checkout and init an orphan branch
            logger.info(f"Base branch {base_branch} not found, initialising empty worktree")
            os.makedirs(worktree_path, exist_ok=True)
            self._run_git(["init"], cwd=worktree_path)
            clone_url = f"https://x-access-token:{self.github_token}@github.com/{repo}.git"
            self._run_git(["remote", "add", "origin", clone_url], cwd=worktree_path)
            self._run_git(["checkout", "--orphan", branch_name], cwd=worktree_path)

        # Set push URL with auth in the worktree
        clone_url = f"https://x-access-token:{self.github_token}@github.com/{repo}.git"
        self._run_git(["remote", "set-url", "origin", clone_url], cwd=worktree_path)

        logger.info(f"Created worktree at {worktree_path} on branch {branch_name}")
        return worktree_path

    def commit_and_push(self, worktree_path: str, message: str) -> bool:
        """
        Stage all changes, commit, and push.

        Returns:
            True if there were changes to push, False if clean.
        """
        # Stage everything
        self._run_git(["add", "-A"], cwd=worktree_path)

        # Check if there's anything to commit
        result = self._run_git(
            ["status", "--porcelain"], cwd=worktree_path, capture=True
        )
        if not result or not result.strip():
            logger.info("No changes to commit")
            return False

        # Commit
        self._run_git(["commit", "-m", message], cwd=worktree_path)

        # Push
        branch = self._run_git(
            ["rev-parse", "--abbrev-ref", "HEAD"],
            cwd=worktree_path, capture=True,
        ).strip()

        try:
            self._run_git(
                ["push", "-u", "origin", branch],
                cwd=worktree_path,
            )
        except subprocess.CalledProcessError:
            # Force push if normal push is rejected (e.g. orphan branch divergence)
            logger.warning(f"Normal push failed for {branch}, force pushing")
            self._run_git(
                ["push", "--force-with-lease", "-u", "origin", branch],
                cwd=worktree_path,
            )

        logger.info(f"Pushed branch {branch}")
        return True

    def remove_worktree(self, repo: str, worktree_path: str):
        """Remove a worktree and clean up."""
        repo_dir = os.path.join(REPOS_DIR, repo.replace("/", "_"))

        try:
            if os.path.exists(repo_dir):
                self._run_git(
                    ["worktree", "remove", worktree_path, "--force"],
                    cwd=repo_dir,
                )
        except Exception as e:
            logger.warning(f"Git worktree remove failed, cleaning manually: {e}")

        # Ensure directory is gone
        if os.path.exists(worktree_path):
            shutil.rmtree(worktree_path, ignore_errors=True)

        # Prune worktree references
        if os.path.exists(repo_dir):
            self._run_git(["worktree", "prune"], cwd=repo_dir)

        logger.info(f"Removed worktree {worktree_path}")

    def cleanup_all(self):
        """Remove all worktrees. Called between tasks for clean state."""
        if os.path.exists(WORKTREES_DIR):
            for name in os.listdir(WORKTREES_DIR):
                path = os.path.join(WORKTREES_DIR, name)
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)

        # Prune all bare repos
        if os.path.exists(REPOS_DIR):
            for name in os.listdir(REPOS_DIR):
                repo_dir = os.path.join(REPOS_DIR, name)
                if os.path.isdir(repo_dir):
                    self._run_git(["worktree", "prune"], cwd=repo_dir)

        logger.info("Cleaned up all worktrees")

    def get_file_list(self, worktree_path: str) -> list[str]:
        """Get list of tracked files in the worktree."""
        result = self._run_git(
            ["ls-files"], cwd=worktree_path, capture=True,
        )
        return result.strip().split("\n") if result and result.strip() else []

    def get_tree_summary(self, worktree_path: str, max_depth: int = 3) -> str:
        """Get a directory tree summary for context."""
        try:
            result = subprocess.run(
                ["find", ".", "-maxdepth", str(max_depth),
                 "-not", "-path", "./.git/*",
                 "-not", "-path", "./node_modules/*",
                 "-not", "-path", "./.git"],
                cwd=worktree_path, capture_output=True, text=True, timeout=10,
            )
            return result.stdout
        except Exception:
            return ""

    # ─── Internal ───────────────────────────────────────────────────────

    def _run_git(
        self, args: list[str], cwd: Optional[str] = None,
        capture: bool = False
    ) -> Optional[str]:
        """Run a git command."""
        cmd = ["git"] + args
        try:
            result = subprocess.run(
                cmd, cwd=cwd, capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                logger.error(
                    f"Git command failed: {' '.join(cmd)}\n"
                    f"stderr: {result.stderr[:500]}"
                )
                if not capture:
                    raise subprocess.CalledProcessError(
                        result.returncode, cmd, result.stdout, result.stderr
                    )
                return None
            if capture:
                return result.stdout
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.error(f"Git command timed out: {' '.join(cmd)}")
            if capture:
                return None
            raise
