{{!
  Template for selecting the best skill and generating parameters.
  Input variables:
  - query: The original natural language query from the user.
  - candidate_skills: A formatted string containing details of candidate skills.
}}
Analyze the user's request: "{{query}}"

Here are the potentially relevant skills identified by a preliminary search, along with their detailed descriptions and parameters:

{{{candidate_skills}}}

Based on the user's request and the detailed skill descriptions provided above:

1.  **Choose the single BEST skill** from the candidates that most accurately fulfills the user's request. PAY CLOSE ATTENTION to the skill description and carefully select the most appropiate skill for the user request.
2.  **Extract the necessary parameters** for the chosen skill from the user's request ("{{query}}"), following the parameter specifications listed in that skill's description.
3.  NEVER add a parameter which is not present in the parameter specifications. If a potentially required parameter to fulfill the user's request is not present, simply discard that skill as a possible candidate. All the possible paramers will always be present in the parameter specifications.
4.  Only add parameters identified as optional if are REALLY required to fulfill the user's request.
5.  Format the output STRICTLY as a JSON object containing ONLY the chosen `skill_id` (string) and the extracted `parameters` (object).
6. Add a natural-sounding phrase that a helpful assistant would say before performing the requested action. This should:
    - Be conversational and human-like (e.g., "Let me check that for you" rather than "Processing request")
    - Briefly indicate what you're about to do without technical jargon
    - Vary your phrasing (don't always start with "I'm checking" or "I'm looking")
    - Match the tone of the user's request (casual, urgent, curious, etc.)
    - Be concise (1-2 short sentences maximum)
    Examples:
    - For calculator: "Let me calculate that for you" or "Working out that equation now"
    - For file search: "Searching through your files now" or "I'll find that document for you"
    - For weather: "Checking the current forecast" or "Let me see what the weather's doing"
7. **Assess User Frustration**: Based on the user's query "{{query}}", determine if the user is expressing frustration, confusion, or dissatisfaction, possibly due to previous misunderstandings.
    - Include a `frustration_level` field in the JSON output: a float from 0.0 (no frustration) to 1.0 (high frustration).
    - Include a `frustration_reason` field: a brief string explaining the detected frustration (e.g., "User is repeating a correction", "User seems confused by the previous answer", "User is expressing annoyance"). If no frustration, this can be null or an empty string.


Example Output Format:
{
  "skill_id": "system/finder",
  "parameters": {
    "query": "recent documents about project X",
    "file_type": "pdf"
  },
  "skill_intention": "I'm looking in the local file system for the requested file...",
  "frustration_level": 0.1,
  "frustration_reason": ""
}

Another Example:
{
  "skill_id": "tools/calculator",
  "parameters": {
    "expression": "cos(3.14159) * 2"
  },
  "skill_intention": "I'm checking the calculator...",
  "frustration_level": 0.0,
  "frustration_reason": null
}

Ensure the output contains ONLY the JSON object, with no explanations, comments, backticks, or any other text before or after it. Use double quotes for all keys and string values within the JSON. For empty or null values, just use `null`.
