"""
task_parser.py — Parse GitHub issue frontmatter and body into a structured task.
"""

import frontmatter
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Task:
    """Represents a parsed task from a GitHub issue."""
    # GitHub issue metadata
    issue_number: int
    issue_url: str
    title: str
    raw_body: str

    # Parsed frontmatter
    repo: str = ""
    new_repo: bool = False
    repo_description: str = ""
    private: bool = False
    branch_prefix: str = "claude"
    priority: str = "medium"            # high | medium | low
    schedule: str = "once"              # once | daily | weekly | monthly
    night_only: bool = False
    persona: str = "product"            # entry persona
    group: Optional[str] = None
    depends_on: list = field(default_factory=list)
    human_review: bool = False

    # Parsed body sections
    task_description: str = ""
    context: str = ""
    acceptance_criteria: str = ""

    # Runtime state
    current_stage: str = "triage"
    review_cycles: int = 0
    qa_cycles: int = 0
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    branch_name: str = ""

    @property
    def target_owner(self) -> str:
        """Extract the owner from the repo string."""
        if "/" in self.repo:
            return self.repo.split("/")[0]
        return ""

    @property
    def target_repo_name(self) -> str:
        """Extract the repo name from the repo string."""
        if "/" in self.repo:
            return self.repo.split("/")[1]
        return self.repo

    @property
    def full_prompt(self) -> str:
        """Build the full prompt from parsed sections."""
        parts = []
        if self.task_description:
            parts.append(f"## Task\n{self.task_description}")
        if self.context:
            parts.append(f"## Context\n{self.context}")
        if self.acceptance_criteria:
            parts.append(f"## Acceptance Criteria\n{self.acceptance_criteria}")
        return "\n\n".join(parts) if parts else self.raw_body


PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def parse_issue(issue: dict) -> Task:
    """
    Parse a GitHub issue dict into a Task object.

    Args:
        issue: GitHub API issue response dict

    Returns:
        Parsed Task object
    """
    body = issue.get("body", "") or ""

    # Parse frontmatter
    try:
        post = frontmatter.loads(body)
        metadata = post.metadata or {}
        content = post.content
    except Exception:
        metadata = {}
        content = body

    # Parse body sections
    task_desc, context, criteria = _parse_body_sections(content)

    # Determine current stage from labels
    labels = [l["name"] for l in issue.get("labels", [])]
    current_stage = _stage_from_labels(labels)

    # Parse depends_on
    depends_on = metadata.get("depends_on", [])
    if isinstance(depends_on, int):
        depends_on = [depends_on]

    task = Task(
        issue_number=issue["number"],
        issue_url=issue["html_url"],
        title=issue["title"],
        raw_body=body,
        repo=metadata.get("repo", ""),
        new_repo=metadata.get("new_repo", False),
        repo_description=metadata.get("description", ""),
        private=metadata.get("private", False),
        branch_prefix=metadata.get("branch_prefix", "claude"),
        priority=metadata.get("priority", "medium"),
        schedule=metadata.get("schedule", "once"),
        night_only=metadata.get("night_only", False),
        persona=metadata.get("persona", "product"),
        group=metadata.get("group", None),
        depends_on=depends_on,
        human_review=metadata.get("human_review", False),
        task_description=task_desc,
        context=context,
        acceptance_criteria=criteria,
        current_stage=current_stage,
    )

    task.branch_name = f"{task.branch_prefix}/{task.issue_number}"

    return task


def _parse_body_sections(content: str) -> tuple[str, str, str]:
    """
    Extract ## Task, ## Context, and ## Acceptance Criteria sections.
    Returns (task_description, context, acceptance_criteria).
    """
    sections = {"task": "", "context": "", "acceptance criteria": ""}
    current_section = None
    current_lines = []

    for line in content.split("\n"):
        stripped = line.strip().lower()
        if stripped.startswith("## "):
            # Save previous section
            if current_section and current_section in sections:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = stripped[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Save last section
    if current_section and current_section in sections:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections["task"], sections["context"], sections["acceptance criteria"]


def _stage_from_labels(labels: list[str]) -> str:
    """Determine current stage from issue labels."""
    stage_labels = [
        "triage", "design", "development",
        "code-review", "qa", "awaiting-human",
        "done", "failed",
    ]
    for stage in stage_labels:
        if stage in labels:
            return stage
    return "triage"
