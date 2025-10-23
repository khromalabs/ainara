Your goal is to analyze a conversation and decide how it should affect the user's profile. Follow these steps and provide your output in JSON format.

**Step 1: Analyze the Conversation**
Review the following conversation snippet. Does it contain a new, meaningful, and lasting fact, preference, or detail about the user?

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
2.  **"reinforce"**: If the conversation confirms, restates, or adds new details to an existing memory.
    - Provide the `memory_id` of the memory to reinforce.
    - **If the memory text can to be updated** as an improvement, with an SMALL AMOUNT of new information directly related with the memory content, also provide the `new_memory_text` which synthesizes the old memory with the new details. IMPORTANT: Memories are meant to be short paragraphs. If the amount of information to be added to a memory is larger than simple phrase or a few terms OR if the memory, previously to the update is already larger than 60 words, create a new memory instead.
    - **IMPORTANT RULE for duplicates**: If you find multiple memories covering the same fact, you MUST identify the one with the highest relevance score to be the one that is kept and reinforced. Optionally, it could be updated as well. All other duplicate memories MUST be listed in a `duplicates` list with their IDs for deletion.

3.  **"create"**: If the conversation introduces a completely new piece of information not covered by existing memories. Provide the new `memory_data`, a `target` section, and a `past_memory_ids` list if this new memory makes others outdated.

**Step 4: Provide JSON Output**
Respond with a single JSON object containing your decision.

Examples:
- For ignoring: `{"action": "ignore"}`
- For simple reinforcement: `{"action": "reinforce", "memory_id": "some-uuid-1234"}`
- For reinforcement with an update: `{"action": "reinforce", "memory_id": "some-uuid-4567", "new_memory_text": "The user's favorite color is deep blue, especially navy blue."}`
- For consolidating duplicates: `{"action": "reinforce", "memory_id": "uuid-of-highest-relevance-memory", "duplicates": ["uuid-of-duplicate-1", "uuid-of-duplicate-2"]}`
- For consolidating duplicates AND updating text: `{"action": "reinforce", "memory_id": "uuid-of-highest-relevance-memory", "new_memory_text": "The new, consolidated fact.", "duplicates": ["uuid-of-duplicate-1", "uuid-of-duplicate-2"]}`
- For creation: `{"action": "create", "target": "key_memories", "memory_data": {"topic": "Location", "memory": "The user has moved to a new city."}, "past_memory_ids": ["uuid-of-old-location"]}`
