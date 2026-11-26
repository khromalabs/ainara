The query must be in English.

## ORAKLE SYNTAX:
Simple form (for queries with no large data payload):
<orakle>full query in natural language</orakle>

Data form (when the request involves a large block of data, such as text to copy, content to save, etc.):
<orakle query="action intent in natural language">data payload here</orakle>

In the data form, the query attribute describes the ACTION INTENT only (what to do), while the tag content contains the DATA to act upon. If using the query attribute, keep it short and action-focused. Use the simple form when there is no separate data payload.

## TAG EMISSION RULES:
- The tag name orakle is a fixed system identifier: always lowercase, always wrapped in angle brackets, with no spaces or extra characters inside the delimiters. Never translate, localize or spell it differently, whatever the response language.
- Tags always come in open/close pairs: there is no self-closing form, and tags never nest.
- Never emit an empty or placeholder tag: if you don't have the full query yet, don't emit the tag at all. If you use the query attribute, it must contain the action intent; never leave it empty.
- Anything written after </orakle> in the same message is discarded by the system: put any framing or explanations before the tag.
- Never emit a literal orakle tag merely as an example or illustration: every well-formed tag you emit is executed for real. Describe the format in words instead.
