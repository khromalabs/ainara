Your goal is to analyze a conversation and decide how it should affect the user's profile. Follow these steps and provide your output in JSON format.

**Step 1: Analyze the Conversation**
Review the following conversation snippet between the user and the assistant. Does it contain a new, meaningful, and lasting fact, preference, or detail about the user?

**Conversation Snippet:**
{{conversation_snippet}}

**Step 2: Compare with Existing Memories**
Here are some existing memories from the user's profile that might be related.

**Existing Memories:**
{{#existing_memories}}
- ID: {{id}}, Relevance: {{relevance}}, Memory: "{{memory}}"
{{/existing_memories}}
{{^existing_memories}}
No similar memories found.
{{/existing_memories}}

**Step 3: Make a Decision**
Based on your analysis, choose one of the following actions:

1.  **"ignore"**: If the conversation contains no new lasting information, or if the information is already perfectly captured by an existing memory.
2.  **"create"**: If the conversation introduces a completely new piece of information not covered by existing memories. Provide the new `memory_data`, a `target` section (`key_memories` or `extended_memories`), and a `past_memory_ids` list if this new memory makes others outdated. Synthesize the information in the most concise way possible while fully and completely maintaining its meaning.
3.  **"reinforce"**: If the conversation confirms, restates, or adds new details to an existing memory.
    - Provide the `memory_id` of the memory to reinforce.
    - **Updating Text**: If the memory text can be improved by incorporating new details, provide a `new_memory_text`. This new text should synthesize the old memory with the new information. Aim to keep the text concise (ideally under 60 words).
    - **Consolidating Duplicates**: If you find multiple memories covering the same fact, choose the most representative one to be reinforced (its ID goes in `memory_id`). List all other duplicate memories in a `duplicates` list so they can be deleted.

4.  **"retract"**: If the conversation reveals that one or more existing memories are **factually wrong** — the user is explicitly correcting information that was never true (e.g., a hallucinated name, an invented preference, a fabricated detail). This is a HIGH BAR action:
    - Only use when the user **unambiguously states** a stored memory is wrong, not merely outdated.
    - **Key distinction**: Information that was once true but has changed → use `"create"` with `past_memory_ids`. Information that was **never true** (hallucination, fabrication) → use `"retract"`.
    - Provide `memory_ids` as a **list** of UUIDs to retract — this handles cases where the same hallucinated fact may have spread across multiple memories via reinforcement.
    - Optionally provide a brief `reason` string for the audit trail.
    - Do NOT use retract for contradictions you infer yourself — only when the user explicitly signals the correction.

**Memory Writing Style**
When writing any memory text (`memory` in `create`, `new_memory_text` in `reinforce`), apply a compact, direct style:
- Strip articles ("the", "a"), filler verbs ("has expressed", "seems to"), and redundant qualifiers.
- Every word must carry semantic weight. Omit words a reader could infer.
- Write in third-person but drop "The user" when the subject is obvious from context.
- Prefer short factual statements: "Enjoys jazz, dislikes pop" over "The user has expressed that they enjoy jazz music and do not enjoy pop music."
- Hard limit: 30 words for simple facts, 60 words for complex or composite memories.

**Step 4: Provide JSON Output**
Respond with a single JSON object containing your decision.

Examples:
- For ignoring: `{"action": "ignore"}`
- For creation: `{"action": "create", "target": "extended_memories", "memory_data": {"topic": "Color Preferences", "memory": "Likes blue, especially navy."}}`
- For creation marking a previous memory as outdated: `{"action": "create", "target": "key_memories", "memory_data": {"topic": "Location", "memory": "Moved to New York."}, "past_memory_ids": ["uuid-of-old-location"]}`
- For simple reinforcement: `{"action": "reinforce", "memory_id": "some-uuid-1234"}`
- For reinforcement updating the memory content: `{"action": "reinforce", "memory_id": "some-uuid-4567", "new_memory_text": "Likes deep blue, especially navy."}`
- For consolidating duplicates: `{"action": "reinforce", "memory_id": "uuid-of-primary-memory", "duplicates": ["uuid-of-duplicate-1", "uuid-of-duplicate-2"]}`
- For consolidating duplicates AND updating text: `{"action": "reinforce", "memory_id": "uuid-of-primary-memory", "new_memory_text": "The new, consolidated fact.", "duplicates": ["uuid-of-duplicate-1", "uuid-of-duplicate-2"]}`
- For retracting a single wrong memory: `{"action": "retract", "memory_ids": ["uuid-of-wrong-memory"], "reason": "User corrected: sister's name is Laura, not Ana"}`
- For retracting multiple related wrong memories: `{"action": "retract", "memory_ids": ["uuid-wrong-1", "uuid-wrong-2", "uuid-wrong-3"], "reason": "User clarified they have no siblings; multiple memories contained fabricated family members"}`
