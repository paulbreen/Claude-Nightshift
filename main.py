"""
main.py — Entry point for the Claude Task Runner.

Runs continuously, polling GitHub for tasks labelled 'claude' + 'ready'.
Respects night-only scheduling and daily task limits.
"""

import os
import sys
import time
import signal
import logging
import yaml
from datetime import datetime, date

import pytz

from github_client import GitHubClient
from worktree_manager import WorktreeManager
from task_runner import TaskRunner
from task_parser import parse_issue, PRIORITY_ORDER
from recurring import RecurringTracker

# ─── Logging ────────────────────────────────────────────────────────────

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(os.environ.get("DATA_DIR", "/data"), "run.log"),
            mode="a",
        ),
    ],
)
logger = logging.getLogger("claude-task-runner")

# ─── Globals ────────────────────────────────────────────────────────────

shutdown_requested = False


def handle_signal(signum, frame):
    global shutdown_requested
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    shutdown_requested = True


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


# ─── Config ─────────────────────────────────────────────────────────────

def load_config(path: str = "/app/config.yaml") -> dict:
    """Load and validate configuration."""
    # Try multiple paths
    for p in [path, "config.yaml", "/data/config.yaml"]:
        if os.path.exists(p):
            with open(p, "r") as f:
                config = yaml.safe_load(f)
            logger.info(f"Loaded config from {p}")
            return resolve_env_vars(config)

    logger.error("No config.yaml found!")
    sys.exit(1)


def resolve_env_vars(config: dict) -> dict:
    """Resolve ${ENV_VAR} references in config values."""
    if isinstance(config, dict):
        return {k: resolve_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [resolve_env_vars(v) for v in config]
    elif isinstance(config, str) and config.startswith("${") and config.endswith("}"):
        env_var = config[2:-1]
        value = os.environ.get(env_var)
        if not value:
            logger.warning(f"Environment variable {env_var} not set")
        return value or config
    return config


# ─── Scheduling ─────────────────────────────────────────────────────────

def is_in_night_window(config: dict) -> bool:
    """Check if current time is within the night processing window."""
    schedule = config.get("schedule", {})
    tz_name = schedule.get("timezone", "UTC")
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)

    start = schedule.get("night_window_start", 2)
    end = schedule.get("night_window_end", 8)

    return start <= now.hour < end


class DailyCounter:
    """Track tasks completed today."""

    def __init__(self, max_per_day: int):
        self.max_per_day = max_per_day
        self.count = 0
        self.today = date.today()

    def can_run(self) -> bool:
        self._reset_if_new_day()
        return self.count < self.max_per_day

    def increment(self):
        self._reset_if_new_day()
        self.count += 1

    def _reset_if_new_day(self):
        if date.today() != self.today:
            self.count = 0
            self.today = date.today()


# ─── Task Selection ─────────────────────────────────────────────────────

def select_task(issues: list[dict], config: dict, recurring: RecurringTracker) -> dict | None:
    """
    Select the best task to work on next.

    Priority order:
    1. Filter out night-only tasks if not in night window
    2. Filter out recurring tasks that aren't due
    3. Sort by priority (high > medium > low)
    4. Pick the first one
    """
    in_night = is_in_night_window(config)

    candidates = []
    for issue in issues:
        task = parse_issue(issue)

        # Filter night-only tasks
        if task.night_only and not in_night:
            logger.debug(f"Skipping #{task.issue_number} (night-only, not in window)")
            continue

        # Filter recurring tasks not yet due
        if task.schedule != "once":
            if not recurring.is_due(task.issue_number, task.schedule):
                logger.debug(f"Skipping #{task.issue_number} (recurring, not due)")
                continue

        # Check dependencies
        if task.depends_on:
            # TODO: check if dependencies are resolved
            pass

        candidates.append((task, issue))

    if not candidates:
        return None

    # Sort by priority
    candidates.sort(key=lambda x: PRIORITY_ORDER.get(x[0].priority, 1))

    selected_task, selected_issue = candidates[0]
    logger.info(
        f"Selected task #{selected_task.issue_number}: {selected_task.title} "
        f"(priority: {selected_task.priority})"
    )
    return selected_issue


# ─── Main Loop ──────────────────────────────────────────────────────────

def main():
    global shutdown_requested

    logger.info("=" * 60)
    logger.info("Claude Task Runner starting up")
    logger.info("=" * 60)

    config = load_config()

    # Validate required env vars
    github_token = config.get("github", {}).get("token")
    if not github_token or github_token.startswith("${"):
        logger.error("GITHUB_TOKEN not set!")
        sys.exit(1)

    # Initialize components
    github_config = config.get("github", {})
    github = GitHubClient(
        token=github_token,
        task_repo=github_config.get("task_repo", ""),
        human_username=github_config.get("human_username", ""),
    )

    worktree_manager = WorktreeManager(github_token=github_token)
    recurring_tracker = RecurringTracker()

    limits = config.get("limits", {})
    daily_counter = DailyCounter(max_per_day=limits.get("max_tasks_per_day", 10))

    polling_interval = config.get("polling_interval_minutes", 5) * 60

    # Ensure labels exist in the task repo
    logger.info("Ensuring required labels exist...")
    github.ensure_labels_exist()

    logger.info(
        f"Polling {github_config.get('task_repo')} every "
        f"{config.get('polling_interval_minutes', 5)} minutes"
    )
    logger.info(
        f"Night window: {config['schedule']['night_window_start']}:00 - "
        f"{config['schedule']['night_window_end']}:00 "
        f"({config['schedule']['timezone']})"
    )

    # ─── Poll Loop ──────────────────────────────────────────────────

    while not shutdown_requested:
        try:
            if not daily_counter.can_run():
                logger.info(
                    f"Daily task limit reached ({daily_counter.max_per_day}). "
                    "Waiting for tomorrow."
                )
                _sleep(polling_interval)
                continue

            # Check for issues labelled 'claude' + 'ready'
            issues = github.get_ready_issues()
            logger.info(f"Found {len(issues)} ready task(s)")

            if not issues:
                _sleep(polling_interval)
                continue

            # Select the best task
            selected = select_task(issues, config, recurring_tracker)
            if not selected:
                logger.info("No eligible tasks to run right now")
                _sleep(polling_interval)
                continue

            # Run the task through its full lifecycle
            runner = TaskRunner(github, worktree_manager, recurring_tracker, config)
            completed = runner.run(selected)

            if completed:
                daily_counter.increment()
                logger.info(
                    f"Tasks completed today: {daily_counter.count}/"
                    f"{daily_counter.max_per_day}"
                )

            # Clean up between tasks
            worktree_manager.cleanup_all()

            # Brief pause before next poll
            if not shutdown_requested:
                time.sleep(10)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            break

        except Exception as e:
            logger.exception(f"Unhandled error in main loop: {e}")
            _sleep(polling_interval)

    logger.info("Claude Task Runner shut down")


def _sleep(seconds: int):
    """Sleep in small increments to allow for graceful shutdown."""
    global shutdown_requested
    elapsed = 0
    while elapsed < seconds and not shutdown_requested:
        time.sleep(min(5, seconds - elapsed))
        elapsed += 5


if __name__ == "__main__":
    main()
