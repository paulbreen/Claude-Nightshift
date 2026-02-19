"""
base.py — Base persona with shared Claude CLI invocation logic.
"""

import subprocess
import logging
import os
from typing import Optional
from task_parser import Task
from github_client import GitHubClient

logger = logging.getLogger(__name__)


class BasePersona:
    """Base class for all agent personas."""

    # Override in subclasses
    persona_name: str = "base"
    persona_emoji: str = "🤖"
    system_prompt: str = "You are a helpful assistant."

    def __init__(self, github: GitHubClient, config: dict):
        self.github = github
        self.config = config
        self.claude_config = config.get("claude", {})

    def invoke_claude(
        self,
        prompt: str,
        working_dir: Optional[str] = None,
        timeout_minutes: Optional[int] = None,
        max_turns: Optional[int] = None,
        append_system: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Invoke Claude CLI in YOLO mode.

        Args:
            prompt: The prompt to send to Claude
            working_dir: Directory to run Claude in
            timeout_minutes: Override timeout
            max_turns: Override max turns
            append_system: Additional system prompt content

        Returns:
            Tuple of (success: bool, output: str)
        """
        timeout = (timeout_minutes or self.claude_config.get("timeout_minutes", 30)) * 60
        turns = max_turns or self.claude_config.get("max_turns", 50)
        model = self.claude_config.get("default_model", "sonnet")

        # Build the full system prompt
        full_system = self.system_prompt
        if append_system:
            full_system += f"\n\n{append_system}"

        cmd = [
            "claude",
            "--dangerously-skip-permissions",
            "--print",
            "--model", model,
            "--max-turns", str(turns),
            "--system-prompt", full_system,
            "-p", prompt,
        ]

        cwd = working_dir or os.getcwd()
        logger.info(
            f"[{self.persona_name}] Invoking Claude CLI in {cwd} "
            f"(model={model}, max_turns={turns}, timeout={timeout}s)"
        )

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ},
            )

            output = result.stdout
            if result.returncode != 0:
                logger.error(
                    f"[{self.persona_name}] Claude CLI exited with code {result.returncode}\n"
                    f"stderr: {result.stderr[:1000]}"
                )
                return False, result.stderr or "Claude CLI failed with no output"

            logger.info(f"[{self.persona_name}] Claude CLI completed successfully")
            return True, output

        except subprocess.TimeoutExpired:
            logger.error(f"[{self.persona_name}] Claude CLI timed out after {timeout}s")
            return False, f"Claude CLI timed out after {timeout // 60} minutes"

        except FileNotFoundError:
            logger.error(f"[{self.persona_name}] Claude CLI not found. Is it installed?")
            return False, "Claude CLI not found"

        except Exception as e:
            logger.error(f"[{self.persona_name}] Unexpected error: {e}")
            return False, str(e)

    def get_issue_context(self, task: Task) -> str:
        """
        Build context from all issue comments — this is the shared memory
        between personas.
        """
        comments = self.github.get_issue_comments(task.issue_number)
        if not comments:
            return ""

        context_parts = []
        for c in comments:
            author = c.get("user", {}).get("login", "unknown")
            body = c.get("body", "")
            context_parts.append(f"**{author}:**\n{body}")

        return "\n\n---\n\n".join(context_parts)

    def comment(self, task: Task, body: str):
        """Post a comment as this persona."""
        self.github.post_persona_comment(
            task.issue_number, self.persona_name, body
        )

    def fail(self, task: Task, reason: str):
        """Mark a task as failed with a reason."""
        self.comment(task, f"❌ **Failed**\n\n{reason}")
        self.github.set_stage_label(task.issue_number, "failed")

    def escalate_to_human(self, task: Task, reason: str):
        """Escalate to the human for input."""
        self.github.tag_human(task.issue_number, self.persona_name, reason)
        task.current_stage = "awaiting-human"

    def transition(self, task: Task, new_stage: str):
        """Move a task to a new stage."""
        self.github.set_stage_label(task.issue_number, new_stage)
        logger.info(
            f"[{self.persona_name}] Issue #{task.issue_number}: "
            f"{task.current_stage} → {new_stage}"
        )
        task.current_stage = new_stage
