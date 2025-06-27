Your goal is to analyze a conversation and decide how it should affect the user's profile. Follow these steps and provide your output in JSON format.

**Step 1: Analyze the Conversation**
Review the following conversation snippet. Does it contain a new, meaningful, and lasting fact, preference, or detail about the user?

**Conversation Snippet:**
{{conversation_snippet}}

**Step 2: Compare with Existing Beliefs**
Here are some existing beliefs from the user's profile that might be related.

**Existing Beliefs:**
{{#existing_beliefs}}
- ID: {{id}}, Belief: "{{belief}}"
{{/existing_beliefs}}
{{^existing_beliefs}}
No similar beliefs found.
{{/existing_beliefs}}

**Step 3: Make a Decision**
Based on your analysis, choose one of the following actions:

1.  **"ignore"**: If the conversation contains no new lasting information, or if the information is already perfectly captured by an existing belief.
2.  **"reinforce"**: If the conversation strongly confirms or restates an existing belief. Provide the 'belief_id' of the belief to reinforce.
3.  **"create"**: If the conversation introduces a genuinely new piece of information not covered by existing beliefs. Provide the new 'belief_data' (including 'topic' and 'belief') and a 'target' section ('key_beliefs' for core facts like name/location, 'extended_beliefs' for everything else).

**Step 4: Provide JSON Output**
Respond with a single JSON object containing your decision.

Examples:
- For reinforcement: `{"action": "reinforce", "belief_id": "some-uuid-1234"}`
- For creation: `{"action": "create", "target": "extended_beliefs", "belief_data": {"topic": "Hobbies", "belief": "The user enjoys hiking on weekends."}}`
- For ignoring: `{"action": "ignore"}`
