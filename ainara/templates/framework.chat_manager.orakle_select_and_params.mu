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
4.  Only add parameters identified as optional if they are REALLY required to fulfill the user's request.
5.  Format your output as a single, complete JSON object. This JSON object MUST include the following top-level keys: `skill_id` (string), `parameters` (object), `skill_intention` (string), `frustration_level` (float), and `frustration_reason` (string or null). The specific content for these keys should be determined by following instructions 1-4, 6, and 7.
6. For the `skill_intention` key in the JSON object (defined in point 5), provide a phrase that a helpful assistant would say before performing the requested action. This should:
    - Be conversational and human-like (Don't introduce the request with a too standard declaration like "Processing request...")
    - Briefly indicate what you're about to do without technical jargon.
    - Match the tone of the user's request (casual, urgent, curious, etc.)
    - Be concise (1-2 short sentences maximum)
7. **Assess User Frustration** to populate the `frustration_level` and `frustration_reason` keys in the JSON object (defined in point 5): Based on the user's query "{{query}}", determine if the user is expressing frustration, confusion, or dissatisfaction, possibly due to previous misunderstandings.
    - The `frustration_level` key should contain: a float from 0.0 (no frustration) to 1.0 (high frustration).
    - The `frustration_reason` key should contain: a brief string explaining the detected frustration (e.g., "User is repeating a correction", "User seems confused by the previous answer", "User is expressing annoyance"). If no frustration, this can be null or an empty string.
8. If none of the available skills seem to be directly related with the user query but the query is a request of information that could be likely found on the Internet, try to use a web search skill if available. Don't select an skill if none of the options seem to fit at all for the user query. In that case, add an additional `error_msg` property in the returned JSON object explaining in conversational style why the user request can't performed.


Example Output Format:
{
  "skill_id": "system/finder",
  "parameters": {
    "query": "recent documents about project X",
    "file_type": "pdf"
  },
  "skill_intention": "I'm looking in the local file system for the requested file...",
  "frustration_level": 0.1,
  "frustration_reason": "",
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
Your entire response MUST consist SOLELY of this JSON object.

DON'T provide any comments appart from the JSON object.
