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
2.  **"create"**: If the conversation introduces a completely new piece of information not covered by existing memories. Provide the new `memory_data`, a `target` section, and a `past_memory_ids` list if this new memory makes others outdated.
3.  **"reinforce"**: If the conversation confirms, restates, or adds new details to an existing memory.
    - Provide the `memory_id` of the memory to reinforce.
    - **Updating Text**: If the memory text can be improved by incorporating new details, provide a `new_memory_text`. This new text should synthesize the old memory with the new information. Aim to keep the text concise (ideally under 60 words).
    - **Consolidating Duplicates**: If you find multiple memories covering the same fact, choose the most representative one to be reinforced (its ID goes in `memory_id`). List all other duplicate memories in a `duplicates` list so they can be deleted.

**Step 4: Provide JSON Output**
Respond with a single JSON object containing your decision.

Examples:
- For ignoring: `{"action": "ignore"}`
- For creation: `{"action": "create", "target": "extended_memories", "memory_data": {"topic": "Color Preferences", "memory": "The user likes the blue color."}}`
- For creation marking a previous memory as outdated: `{"action": "create", "target": "key_memories", "memory_data": {"topic": "Location", "memory": "The user has moved to a new city, New York."}, "past_memory_ids": ["uuid-of-old-location"]}`
- For simple reinforcement: `{"action": "reinforce", "memory_id": "some-uuid-1234"}`
- For reinforcement updating the memory content: `{"action": "reinforce", "memory_id": "some-uuid-4567", "new_memory_text": "The user likes the deep blue color, especially navy blue."}`
- For consolidating duplicates: `{"action": "reinforce", "memory_id": "uuid-of-primary-memory", "duplicates": ["uuid-of-duplicate-1", "uuid-of-duplicate-2"]}`
- For consolidating duplicates AND updating text: `{"action": "reinforce", "memory_id": "uuid-of-primary-memory", "new_memory_text": "The new, consolidated fact.", "duplicates": ["uuid-of-duplicate-1", "uuid-of-duplicate-2"]}`
