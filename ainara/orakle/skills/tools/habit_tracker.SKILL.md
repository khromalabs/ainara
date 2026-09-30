---
name: "tools_habit_tracker"
version: "1.0"
description: "Logs habit streaks, sends reminders, and tracks daily habit completion"
category: "tools"
---

# Tools Habit Tracker

## Description

Logs habit streaks, sends reminders, and tracks daily habit completion

## Trigger Conditions

Use when user wants to create, track, log, or get reminders about habits, streaks, or daily commitments

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | Literal['log_completion', 'set_reminder', 'add_habit', 'get_streak', 'plan_habit'] | yes |  | The operation to perform on habits |
| habit_name | str | no | None | Name of the habit to add, log, or manage |
| commitment | str | no | None | Desired frequency or commitment level for the habit |
| date | str | no | None | Date for logging completion or checking streak in YYYY-MM-DD format |

## Returns

| Field | Type | Description |
|-------|------|-------------|
| success | boolean | Whether the operation succeeded |
| result | any | The skill output (present on success) |
| error | string | Error message (present on failure) |

## Examples

```
# Input: User asks to logs habit streaks, sends reminders, and tracks daily habit completion
# action: "example request"
# Output: {"success": true, "result": "example request processed by tools_habit_tracker"}
```
