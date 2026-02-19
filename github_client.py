"""
github_client.py — All GitHub API interactions: issues, labels, comments, PRs, repos.
"""

import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Handles all interactions with the GitHub API."""

    def __init__(self, token: str, task_repo: str, human_username: str):
        """
        Args:
            token: GitHub Personal Access Token
            task_repo: The task queue repo (e.g. "user/Claude-ToDo")
            human_username: GitHub username for @Human tagging
        """
        self.token = token
        self.task_repo = task_repo
        self.human_username = human_username
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    # ─── Issue Fetching ─────────────────────────────────────────────────

    def get_ready_issues(self) -> list[dict]:
        """Fetch all open issues with both 'claude' and 'ready' labels, oldest first."""
        url = f"{GITHUB_API}/repos/{self.task_repo}/issues"
        params = {
            "labels": "claude,ready",
            "state": "open",
            "sort": "created",
            "direction": "asc",
            "per_page": 50,
        }
        resp = self._request("GET", url, params=params)
        if resp is None:
            return []
        return [i for i in resp if "pull_request" not in i]

    def get_awaiting_human_issues(self) -> list[dict]:
        """Fetch all open issues with both 'claude' and 'awaiting-human' labels, oldest first."""
        url = f"{GITHUB_API}/repos/{self.task_repo}/issues"
        params = {
            "labels": "claude,awaiting-human",
            "state": "open",
            "sort": "created",
            "direction": "asc",
            "per_page": 50,
        }
        resp = self._request("GET", url, params=params)
        if resp is None:
            return []
        return [i for i in resp if "pull_request" not in i]

    def get_in_progress_issues(self) -> list[dict]:
        """Fetch issues currently being worked on (any active stage label)."""
        stages = ["triage", "design", "development", "code-review", "qa"]
        all_issues = []
        for stage in stages:
            url = f"{GITHUB_API}/repos/{self.task_repo}/issues"
            params = {
                "labels": f"claude,{stage}",
                "state": "open",
                "per_page": 50,
            }
            resp = self._request("GET", url, params=params)
            if resp:
                all_issues.extend([i for i in resp if "pull_request" not in i])
        # Deduplicate by issue number
        seen = set()
        unique = []
        for issue in all_issues:
            if issue["number"] not in seen:
                seen.add(issue["number"])
                unique.append(issue)
        return unique

    def get_issue(self, issue_number: int) -> Optional[dict]:
        """Fetch a single issue by number."""
        url = f"{GITHUB_API}/repos/{self.task_repo}/issues/{issue_number}"
        return self._request("GET", url)

    def get_issue_comments(self, issue_number: int) -> list[dict]:
        """Fetch all comments on an issue."""
        url = f"{GITHUB_API}/repos/{self.task_repo}/issues/{issue_number}/comments"
        params = {"per_page": 100}
        resp = self._request("GET", url, params=params)
        return resp if resp else []

    # ─── Labels ─────────────────────────────────────────────────────────

    def set_stage_label(self, issue_number: int, new_stage: str):
        """
        Remove all stage labels and set the new one.
        Keeps non-stage labels (claude, night-only, recurring, etc.) intact.
        """
        stage_labels = {
            "ready", "triage", "design", "development",
            "code-review", "qa", "awaiting-human", "done", "failed",
        }
        issue = self.get_issue(issue_number)
        if not issue:
            return

        current_labels = [l["name"] for l in issue.get("labels", [])]

        # Remove old stage labels
        for label in current_labels:
            if label in stage_labels and label != new_stage:
                self._remove_label(issue_number, label)

        # Add new stage label
        if new_stage not in current_labels:
            self._add_label(issue_number, new_stage)

    def add_label(self, issue_number: int, label: str):
        """Add a single label to an issue."""
        self._add_label(issue_number, label)

    def remove_label(self, issue_number: int, label: str):
        """Remove a single label from an issue."""
        self._remove_label(issue_number, label)

    def _add_label(self, issue_number: int, label: str):
        """Add a label, creating it if it doesn't exist."""
        url = f"{GITHUB_API}/repos/{self.task_repo}/issues/{issue_number}/labels"
        self._request("POST", url, json={"labels": [label]})

    def _remove_label(self, issue_number: int, label: str):
        """Remove a label from an issue."""
        url = f"{GITHUB_API}/repos/{self.task_repo}/issues/{issue_number}/labels/{label}"
        self._request("DELETE", url)

    def ensure_labels_exist(self):
        """Create all required labels in the task repo if they don't exist."""
        required = {
            "claude": "0e8a16",
            "ready": "c5def5",
            "night-only": "1d76db",
            "recurring": "5319e7",
            "triage": "fbca04",
            "design": "f9d0c4",
            "development": "bfd4f2",
            "code-review": "d4c5f9",
            "qa": "c2e0c6",
            "awaiting-human": "e4e669",
            "done": "0e8a16",
            "failed": "d73a4a",
        }

        url = f"{GITHUB_API}/repos/{self.task_repo}/labels"
        existing = self._request("GET", url, params={"per_page": 100})
        existing_names = {l["name"] for l in (existing or [])}

        for name, color in required.items():
            if name not in existing_names:
                self._request("POST", url, json={
                    "name": name,
                    "color": color,
                })
                logger.info(f"Created label: {name}")

    # ─── Comments ───────────────────────────────────────────────────────

    def post_comment(self, issue_number: int, body: str):
        """Post a comment on an issue."""
        url = f"{GITHUB_API}/repos/{self.task_repo}/issues/{issue_number}/comments"
        self._request("POST", url, json={"body": body})

    def post_persona_comment(self, issue_number: int, persona: str, body: str):
        """Post a comment prefixed with the persona identifier."""
        persona_headers = {
            "product_owner": "🎯 **Product Owner**",
            "architect": "🏗️ **Architect**",
            "developer": "💻 **Developer**",
            "qa": "🧪 **QA**",
        }
        header = persona_headers.get(persona, f"🤖 **{persona}**")
        full_body = f"{header}\n\n{body}"
        self.post_comment(issue_number, full_body)

    def tag_human(self, issue_number: int, persona: str, reason: str):
        """Tag the human user and set awaiting-human label."""
        body = (
            f"@{self.human_username} — Requesting human input.\n\n"
            f"**Reason:** {reason}"
        )
        self.post_persona_comment(issue_number, persona, body)
        self.set_stage_label(issue_number, "awaiting-human")

    # ─── Issues ─────────────────────────────────────────────────────────

    def close_issue(self, issue_number: int):
        """Close an issue."""
        url = f"{GITHUB_API}/repos/{self.task_repo}/issues/{issue_number}"
        self._request("PATCH", url, json={"state": "closed"})

    # ─── Repositories ───────────────────────────────────────────────────

    def create_repo(self, name: str, description: str = "", private: bool = False) -> Optional[dict]:
        """Create a new repository under the authenticated user."""
        url = f"{GITHUB_API}/user/repos"
        data = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": True,
        }
        return self._request("POST", url, json=data)

    # ─── Pull Requests ──────────────────────────────────────────────────

    def create_pull_request(
        self, repo: str, title: str, body: str,
        head: str, base: str = "main"
    ) -> Optional[dict]:
        """Create a pull request on the target repo."""
        url = f"{GITHUB_API}/repos/{repo}/pulls"
        data = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        }
        return self._request("POST", url, json=data)

    def get_pull_request(self, repo: str, pr_number: int) -> Optional[dict]:
        """Fetch a pull request."""
        url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
        return self._request("GET", url)

    def get_pr_diff(self, repo: str, pr_number: int) -> Optional[str]:
        """Fetch the diff for a pull request."""
        url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
        headers = {"Accept": "application/vnd.github.v3.diff"}
        resp = self.session.get(url, headers=headers)
        if resp.status_code == 200:
            return resp.text
        logger.error(f"Failed to get PR diff: {resp.status_code}")
        return None

    def get_pr_files(self, repo: str, pr_number: int) -> list[dict]:
        """Fetch the list of files changed in a PR."""
        url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/files"
        resp = self._request("GET", url, params={"per_page": 100})
        return resp if resp else []

    def merge_pull_request(self, repo: str, pr_number: int, merge_method: str = "squash") -> bool:
        """Merge a pull request."""
        url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/merge"
        data = {"merge_method": merge_method}
        resp = self._request("PUT", url, json=data)
        return resp is not None

    def get_default_branch(self, repo: str) -> str:
        """Get the default branch for a repo."""
        url = f"{GITHUB_API}/repos/{repo}"
        resp = self._request("GET", url)
        if resp:
            return resp.get("default_branch", "main")
        return "main"

    # ─── Internal ───────────────────────────────────────────────────────

    def _request(self, method: str, url: str, **kwargs) -> Optional[dict | list]:
        """Make an authenticated GitHub API request."""
        try:
            resp = self.session.request(method, url, **kwargs)

            if resp.status_code == 204:
                return {}

            if resp.status_code >= 400:
                logger.error(
                    f"GitHub API {method} {url} returned {resp.status_code}: "
                    f"{resp.text[:500]}"
                )
                return None

            if resp.text:
                return resp.json()
            return {}

        except requests.RequestException as e:
            logger.error(f"GitHub API request failed: {e}")
            return None
