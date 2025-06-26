Analyze the following conversation snippet. Your task is to determine if a new, lasting belief about the user can be extracted. A belief can be a fact, a preference, or a stated goal.

There are two types of beliefs:
1.  `key_beliefs`: For critical, core information that should ALWAYS be remembered. This includes the user's name, job, core family details (spouse, children), major life goals, or
critical health information.
2.  `extended_beliefs`: For all other general information. This includes hobbies, opinions, temporary interests, project details, or general preferences (e.g., likes coffee, prefers sci-fi
movies).

When in doubt, categorize a belief as `extended_beliefs`.

If you find a new belief, respond with a single JSON object in the following format. Do NOT add any other text before or after the JSON.
{
  "target": "key_beliefs" | "extended_beliefs",
  "belief_data": {
    "topic": "A concise topic category for the belief (e.g., 'personal_details', 'work', 'hobbies_and_interests').",
    "belief": "A detailed statement of the belief, written in the third person (e.g., 'The user's name is Jane Doe.').",
    "summary": "A very brief summary of the belief (e.g., 'User name: Jane Doe')."
  }
}

If NO new, lasting belief can be extracted from this snippet, respond with the single word: None

Conversation Snippet:
---
{{conversation_snippet}}
---

