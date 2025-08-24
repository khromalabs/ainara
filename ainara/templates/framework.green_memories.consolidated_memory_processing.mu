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
2.  **"reinforce"**: If the conversation confirms or restates an existing memory. Provide the 'memory_id' of the memory to reinforce. If several memories contain exactly the same concept, chose the memory with the highest relevance to be reinforced, and add all the duplicates in an array which will mark them to be erased.
3.  **"create"**: If the conversation introduces a new piece of information. Provide the new 'memory_data', a 'target' section, and if this memory makes outdated other memories, a 'past_memory_ids' list containing the IDs of any memories that this new fact make outdated.

**Step 4: Provide JSON Output**
Respond with a single JSON object containing your decision.

Examples:
- For ignoring: `{"action": "ignore"}`
- For reinforcement without finding duplicates: `{"action": "reinforce", "memory_id": "some-uuid-1234"}`
- For reinforcement with finding duplicates: `{"action": "reinforce", "memory_id": "some-uuid-1234", duplicates: [ "uuid-of-duplicate-memory-1", "uuid-of-duplicate-memory-2" ]}`
- For creation: `{"action": "create", "target": "key_memories", "memory_data": {"topic": "Location", "memory": "The user has moved to a new city."}, "past_memory_ids": ["uuid-of-old-location"]}`
