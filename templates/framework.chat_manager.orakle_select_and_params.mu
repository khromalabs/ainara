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

1.  **Choose the single BEST skill** from the candidates that most accurately fulfills the user's request.
2.  **Extract the necessary parameters** for the chosen skill from the user's request ("{{query}}"), following the parameter specifications listed in that skill's description.
3.  If a parameter isn't explicitly mentioned in the request but is required or can be reasonably inferred (e.g., default values mentioned in the description), include it.
4.  For parameters not mentioned and not inferable, omit them from the JSON unless they are explicitly marked as required with no default.
5.  Format the output STRICTLY as a JSON object containing ONLY the chosen `skill_id` (string) and the extracted `parameters` (object).

Example Output Format:
{
  "skill_id": "system/finder",
  "parameters": {
    "query": "recent documents about project X",
    "file_type": "pdf"
  }
}

Another Example:
{
  "skill_id": "tools/calculator",
  "parameters": {
    "expression": "cos(3.14159) * 2"
  }
}

Ensure the output contains ONLY the JSON object, with no explanations, comments, backticks, or any other text before or after it. Use double quotes for all keys and string values within the JSON. For empty or null values, use `null`.
