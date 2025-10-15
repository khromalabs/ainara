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
    - **If the memory text needs to be updated** with new information, also provide the `new_memory_text` which synthesizes the old memory with the new details.
    - If you find duplicate memories, provide a `duplicates` list with their IDs to be deleted. Keep the memory with the highest relevance.
    - These two actions can be optionally combined, as it is shown in the examples below.
3.  **"create"**: If the conversation introduces a completely new piece of information not covered by existing memories. Provide the new `memory_data`, a `target` section, and a `past_memory_ids` list if this new memory makes others outdated.

**Step 4: Provide JSON Output**
Respond with a single JSON object containing your decision.

Examples:
- For ignoring: `{"action": "ignore"}`
- For simple reinforcement: `{"action": "reinforce", "memory_id": "some-uuid-1234"}`
- For reinforcement with an update: `{"action": "reinforce", "memory_id": "some-uuid-4567", "new_memory_text": "The user's favorite color is deep blue, especially navy blue."}`
- For reinforcement with finding duplicates: `{"action": "reinforce", "memory_id": "some-uuid-1234", duplicates: [ "uuid-of-duplicate-memory-1", "uuid-of-duplicate-memory-2" ]}`
- For reinforcement with finding duplicates AND an update: `{"action": "reinforce", "memory_id": "some-uuid-1234", "new_memory_text": "The user's favorite color is deep blue, especially navy blue.", duplicates: [ "uuid-of-duplicate-memory-1", "uuid-of-duplicate-memory-2" ]}`
- For creation: `{"action": "create", "target": "key_memories", "memory_data": {"topic": "Location", "memory": "The user has moved to a new city."}, "past_memory_ids": ["uuid-of-old-location"]}`
