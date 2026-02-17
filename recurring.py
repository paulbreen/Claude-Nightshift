"""
recurring.py — Track and evaluate recurring task schedules.
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = os.environ.get("DATA_DIR", "/data")


class RecurringTracker:
    """Tracks last-run times for recurring tasks."""

    def __init__(self, data_dir: str = DEFAULT_DATA_DIR):
        self.data_file = os.path.join(data_dir, "recurring.json")
        os.makedirs(data_dir, exist_ok=True)
        self._load()

    def is_due(self, issue_number: int, schedule: str) -> bool:
        """
        Check if a recurring task is due to run.

        Args:
            issue_number: The issue number
            schedule: one of "daily", "weekly", "monthly"

        Returns:
            True if the task should run
        """
        key = str(issue_number)
        if key not in self.data:
            return True

        last_run_str = self.data[key].get("last_run")
        if not last_run_str:
            return True

        last_run = datetime.fromisoformat(last_run_str)
        now = datetime.utcnow()

        intervals = {
            "daily": timedelta(days=1),
            "weekly": timedelta(weeks=1),
            "monthly": timedelta(days=30),
        }

        interval = intervals.get(schedule)
        if not interval:
            return True

        return (now - last_run) >= interval

    def record_run(self, issue_number: int, schedule: str):
        """Record that a recurring task was run."""
        key = str(issue_number)
        self.data[key] = {
            "schedule": schedule,
            "last_run": datetime.utcnow().isoformat(),
        }
        self._save()
        logger.info(f"Recorded run for recurring task #{issue_number}")

    def _load(self):
        """Load recurring data from disk."""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load recurring data: {e}")
                self.data = {}
        else:
            self.data = {}

    def _save(self):
        """Persist recurring data to disk."""
        try:
            with open(self.data_file, "w") as f:
                json.dump(self.data, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save recurring data: {e}")
