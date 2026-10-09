---
name: "tools_habit_tracker"
version: "1.0"
description: "Tracks daily habit completion and streaks"
category: "tools"
---

# Tools Habit Tracker

## Description

Tracks daily habit completion and streaks

## Trigger Conditions

Use when user wants to create, track or log habits, or check a habit streak or daily commitment

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | Literal['log_completion', 'add_habit', 'get_streak', 'plan_habit'] | yes |  | The operation to perform on habits |
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
# Input: "I went for a run today"
# action: "log_completion", habit_name: "running"
# Output: {"success": true, "result": "Logged completion for 'running' on 2026-10-08"}

# Input: "How's my running streak?"
# action: "get_streak", habit_name: "running"
# Output: {"success": true, "result": "Current streak for 'running': 5 days"}
```
