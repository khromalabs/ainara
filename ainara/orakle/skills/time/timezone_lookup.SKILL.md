---
name: "time_timezone_lookup"
version: "1.0"
description: "Look up timezone information using city, state, country or timezone name"
category: "time"
---

# Time Timezone Lookup

## Description

Look up timezone information using city, state, country or timezone name

## Trigger Conditions

Use when the user asks for timezone, time zone, or current time in a specific city, state, country or named timezone

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| city | Optional[str] | no | None | City name to search timezone for |
| state | Optional[str] | no | None | State or province name |
| country | Optional[str] | no | None | Country name |
| timezone | Optional[str] | no | None | Named timezone such as America/New_York |

## Returns

| Field | Type | Description |
|-------|------|-------------|
| success | boolean | Whether the operation succeeded |
| result | any | The skill output (present on success) |
| error | string | Error message (present on failure) |

## Examples

```
# Input: User asks to look up timezone information using city, state, country or timezone name
# city: "example request"
# Output: {"success": true, "result": "example request processed by time_timezone_lookup"}
```
