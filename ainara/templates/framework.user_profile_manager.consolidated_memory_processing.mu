Your goal is to analyze a conversation and decide how it should affect the user's profile. Follow these steps and provide your output in JSON format.

**Step 1: Analyze the Conversation**
Review the following conversation snippet. Does it contain a new, meaningful, and lasting fact, preference, or detail about the user?

**Conversation Snippet:**
{{conversation_snippet}}

**Step 2: Compare with Existing Memories**
Here are some existing memories from the user's profile that might be related.

**Existing Memories:**
{{#existing_memories}}
- ID: {{id}}, Memory: "{{memory}}"
{{/existing_memories}}
{{^existing_memories}}
No similar memories found.
{{/existing_memories}}

**Step 3: Make a Decision**
Based on your analysis, choose one of the following actions:

1.  **"ignore"**: If the conversation contains no new lasting information, or if the information is already perfectly captured by an existing memory.
2.  **"reinforce"**: If the conversation strongly confirms or restates an existing memory. Provide the 'memory_id' of the memory to reinforce.
3.  **"create"**: If the conversation introduces a genuinely new piece of information not covered by existing memories. Provide the new 'memory_data' (including 'topic' and 'memory') and a 'target' section ('key_memories' for core facts like name/location, 'extended_memories' for everything else).

**Step 4: Provide JSON Output**
Respond with a single JSON object containing your decision.

Examples:
- For reinforcement: `{"action": "reinforce", "memory_id": "some-uuid-1234"}`
- For creation: `{"action": "create", "target": "extended_memories", "memory_data": {"topic": "Hobbies", "memory": "The user enjoys hiking on weekends."}}`
- For ignoring: `{"action": "ignore"}`
