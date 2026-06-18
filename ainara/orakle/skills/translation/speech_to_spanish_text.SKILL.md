---
name: "translation_speech_to_spanish_text"
version: "1.0"
description: "Converts English speech input into Spanish text output"
category: "translation"
---

# Translation Speech To Spanish Text

## Description

Converts English speech input into Spanish text output

## Trigger Conditions

Use when the user wants to translate spoken English into written Spanish, keywords: speech, english, spanish, text, translate

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| speech_input | str | yes |  | The English speech content or audio transcription to translate |

## Returns

| Field | Type | Description |
|-------|------|-------------|
| success | boolean | Whether the operation succeeded |
| result | any | The skill output (present on success) |
| error | string | Error message (present on failure) |

## Examples

```
# Input: User asks to converts english speech input into spanish text output
# speech_input: "example request"
# Output: {"success": true, "result": "example request processed by translation_speech_to_spanish_text"}
```
