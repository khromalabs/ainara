Analyze the following conversation snippet. Your task is to determine if a new, lasting memory about the user can be extracted. A memory can be a fact, a preference, or a stated goal.

There are two types of memories:
1.  `key_memories`: For critical, core information that should ALWAYS be remembered. This includes the user's name, job, core family details (spouse, children), major life goals, or
critical health information.
2.  `extended_memories`: For all other general information. This includes hobbies, opinions, temporary interests, project details, or general preferences (e.g., likes coffee, prefers sci-fi
movies).

When in doubt, categorize a memory as `extended_memories`.

If you find a new memory, respond with a single JSON object in the following format. Do NOT add any other text before or after the JSON.
{
  "target": "key_memories" | "extended_memories",
  "memory_data": {
    "topic": "A concise topic category for the memory (e.g., 'personal_details', 'work', 'hobbies_and_interests').",
    "memory": "A detailed statement of the memory, written in the third person (e.g., 'The user's name is Jane Doe.').",
    "summary": "A very brief summary of the memory (e.g., 'User name: Jane Doe')."
  }
}

If NO new, lasting memory can be extracted from this snippet, respond with the single word: None

Conversation Snippet:
---
{{conversation_snippet}}
---

