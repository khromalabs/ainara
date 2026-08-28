---
name: "messaging_daily_morning_ritual_reminder"
version: "1.0"
description: "Sends a daily 9 a.m. Eastern reminder to Jordan about completing the morning ritual"
category: "messaging"
---

# Messaging Daily Morning Ritual Reminder

## Description

Sends a daily 9 a.m. Eastern reminder to Jordan about completing the morning ritual

## Trigger Conditions

Use when user wants to schedule or configure recurring reminders for Jordan's daily ritual including workout, meditation, diet rules, and gym sessions

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| recipient | str | yes |  | Name of the person receiving the reminder |
| delivery_method | Literal['email', 'desktop_notification'] | yes |  | How the reminder should be delivered |
| reminder_time | str | yes |  | Time to send the reminder in 24-hour format |
| time_zone | str | yes |  | Time zone for the reminder time |
| ritual_items | str | no | light workout, meditation, no sugar, no processed food, gym workout, clean eating | Comma-separated list of ritual activities to include in reminder |
| frequency_days | int | no | 5 | Minimum number of days per week the ritual should be completed |

## Returns

| Field | Type | Description |
|-------|------|-------------|
| success | boolean | Whether the operation succeeded |
| result | any | The skill output (present on success) |
| error | string | Error message (present on failure) |

## Examples

```
# Input: User asks to sends a daily 9 a.m. eastern reminder to jordan about completing the morning ritual
# recipient: "example request"
# Output: {"success": true, "result": "example request processed by messaging_daily_morning_ritual_reminder"}
```
