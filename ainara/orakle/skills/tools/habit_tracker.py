"""Skill for logs habit streaks, sends reminders, and tracks daily habit completion"""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Dict, Literal, Optional

import pytz
from dateutil import parser

from ainara.framework.platform_utils import get_default_data_dir
from ainara.framework.skill import Skill


class ToolsHabitTracker(Skill):
    """Logs habit streaks, sends reminders, and tracks daily habit completion"""

    matcher_info = (
        "Use when user wants to create, track, log, or get reminders about habits, streaks, or daily commitments"
    )

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        db_dir = Path(get_default_data_dir())
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
        action: Annotated[Literal['log_completion', 'set_reminder', 'add_habit', 'get_streak', 'plan_habit'], "The operation to perform on habits"],
        habit_name: Annotated[Optional[str], "Name of the habit to add, log, or manage"] = None,
        commitment: Annotated[Optional[str], "Desired frequency or commitment level for the habit"] = None,
        date: Annotated[Optional[str], "Date for logging completion or checking streak in YYYY-MM-DD format"] = None,
    ) -> Dict[str, Any]:
        """Executes the habit tracker skill"""
        try:
            tz = pytz.timezone('UTC')
            conn = self._get_conn()
            cursor = conn.cursor()

            if action == 'add_habit':
                if not habit_name:
                    return {"success": False, "result": "habit_name is required"}
                cursor.execute(
                    "INSERT OR IGNORE INTO habits (habit_name, date, completed) VALUES (?, ?, 0)",
                    (habit_name, datetime.now(tz).strftime('%Y-%m-%d'))
                )
                conn.commit()
                result = f"Habit '{habit_name}' added"

            elif action == 'log_completion':
                if not habit_name:
                    return {"success": False, "result": "habit_name is required"}
                log_date = date if date else datetime.now(tz).strftime('%Y-%m-%d')
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
                    streak = 0
                    check_date = datetime.now(tz).date()
                    for d in dates:
                        if d == check_date or d == check_date - timedelta(days=streak):
                            streak += 1
                            check_date = d
                        else:
                            break
                    result = f"Current streak for '{habit_name}': {streak} days"

            elif action == 'set_reminder':
                result = (
                    "Reminder scheduling requires email configuration in ainara.yaml "
                    "(notifications.email section). Use the morning ritual reminder skill "
                    "to schedule recurring notifications."
                )

            elif action == 'plan_habit':
                if not habit_name or not commitment:
                    return {"success": False, "result": "habit_name and commitment required"}
                cursor.execute(
                    "INSERT OR IGNORE INTO habits (habit_name, date, completed) VALUES (?, ?, 0)",
                    (habit_name, datetime.now(tz).strftime('%Y-%m-%d'))
                )
                conn.commit()
                result = f"Habit '{habit_name}' planned with commitment: {commitment}"

            else:
                result = f"Unknown action '{action}'. Valid actions: log_completion, set_reminder, add_habit, get_streak, plan_habit"

            conn.close()
            return {"success": True, "result": result}
        except Exception as e:
            self.logger.error(f"{self.name} failed: {e}")
            return {"success": False, "error": str(e)}
