"""Skill for tracking daily habit completion and streaks"""

import logging
import sqlite3
from datetime import date as Date
from datetime import datetime, timedelta
from typing import Annotated, Any, Dict, Iterable, Literal, Optional

from dateutil import parser

from ainara.framework.config import get_data_dir
from ainara.framework.skill import Skill


def compute_streak(dates: Iterable[Date], today: Date) -> int:
    """Count consecutive completed days ending today or yesterday.

    A streak still counts when today has not been logged yet, so a habit
    done every day through yesterday reports its full length instead of 0.
    Duplicate dates are ignored.
    """
    days = sorted(set(dates), reverse=True)
    if not days or days[0] < today - timedelta(days=1):
        return 0
    streak = 1
    for prev, d in zip(days, days[1:]):
        if d != prev - timedelta(days=1):
            break
        streak += 1
    return streak


class ToolsHabitTracker(Skill):
    """Tracks daily habit completion and streaks"""

    matcher_info = (
        "Use when user wants to create, track or log habits, or check a habit streak or daily commitment"
    )

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        db_dir = get_data_dir()
        db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_dir / "habits.db")

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS habits
               (habit_name TEXT, date TEXT, completed INTEGER DEFAULT 0,
                PRIMARY KEY (habit_name, date))"""
        )
        conn.commit()
        return conn

    async def run(
        self,
        action: Annotated[Literal['log_completion', 'add_habit', 'get_streak', 'plan_habit'], "The operation to perform on habits"],
        habit_name: Annotated[Optional[str], "Name of the habit to add, log, or manage"] = None,
        commitment: Annotated[Optional[str], "Desired frequency or commitment level for the habit"] = None,
        date: Annotated[Optional[str], "Date for logging completion or checking streak in YYYY-MM-DD format"] = None,
    ) -> Dict[str, Any]:
        """Executes the habit tracker skill"""
        try:
            # Local date: habits are logged against the user's own day, and a
            # UTC "today" would shift evening completions onto tomorrow.
            today = datetime.now().date()
            conn = self._get_conn()
            cursor = conn.cursor()

            if action == 'add_habit':
                if not habit_name:
                    return {"success": False, "result": "habit_name is required"}
                cursor.execute(
                    "INSERT OR IGNORE INTO habits (habit_name, date, completed) VALUES (?, ?, 0)",
                    (habit_name, today.isoformat())
                )
                conn.commit()
                result = f"Habit '{habit_name}' added"

            elif action == 'log_completion':
                if not habit_name:
                    return {"success": False, "result": "habit_name is required"}
                # Normalize so a free-form date can't poison later streak parsing
                log_date = parser.parse(date).date().isoformat() if date else today.isoformat()
                cursor.execute(
                    "INSERT OR REPLACE INTO habits (habit_name, date, completed) VALUES (?, ?, 1)",
                    (habit_name, log_date)
                )
                conn.commit()
                result = f"Logged completion for '{habit_name}' on {log_date}"

            elif action == 'get_streak':
                if not habit_name:
                    return {"success": False, "result": "habit_name is required"}
                cursor.execute(
                    "SELECT date FROM habits WHERE habit_name = ? AND completed = 1 ORDER BY date DESC",
                    (habit_name,)
                )
                dates = [parser.parse(row[0]).date() for row in cursor.fetchall()]
                if not dates:
                    result = f"No completions recorded for '{habit_name}'"
                else:
                    streak = compute_streak(dates, today)
                    result = f"Current streak for '{habit_name}': {streak} days"

            elif action == 'plan_habit':
                if not habit_name or not commitment:
                    return {"success": False, "result": "habit_name and commitment required"}
                cursor.execute(
                    "INSERT OR IGNORE INTO habits (habit_name, date, completed) VALUES (?, ?, 0)",
                    (habit_name, today.isoformat())
                )
                conn.commit()
                result = f"Habit '{habit_name}' planned with commitment: {commitment}"

            else:
                result = f"Unknown action '{action}'. Valid actions: log_completion, add_habit, get_streak, plan_habit"

            conn.close()
            return {"success": True, "result": result}
        except Exception as e:
            self.logger.error(f"{self.name} failed: {e}")
            return {"success": False, "error": str(e)}
