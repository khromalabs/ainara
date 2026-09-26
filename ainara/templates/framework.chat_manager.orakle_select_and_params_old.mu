User request: "{{query}}"

{{#orakle_data}}
Data payload provided:
<data>
{{{orakle_data}}}
</data>
{{/orakle_data}}

Available skills:
{{{candidate_skills}}}

Task: Select the best skill and extract parameters. Return ONLY a JSON object with these keys:
skill_id, parameters, frustration_level, frustration_reason, reasoning_level, skill_intention.

Instructions:
1. Choose the skill which better suits the user request. IMPORTANT: Use only the exact parameters defined in the skill specification.
2. Skip optional parameters unless needed.
3. If no skill fits, but query clearly seeks for information, use search_web skill as shown in example.
4. If no skill fits the query intent, return an empty skill_id and add error_msg.

Returned JSON object keys details:
- frustration_level (0.0-1.0): Detect user frustration, confusion, or dissatisfaction in the query.
- frustration_reason: Brief explanation if frustration, otherwise null.
- reasoning_level (0.0-1.0): 0.0 for direct commands, higher for analysis/comparison/planning tasks.
- skill_intention: Conversational sentence action preview in {{language}}. Be natural, match user's tone, avoid jargon.

Result example:

{
  "skill_id": "search_web",
  "parameters": {"query": "analyze pros and cons of nuclear energy"},
  "reasoning_level": 0.7
  "frustration_level": 0.0,
  "frustration_reason": null,
  "skill_intention": "I'll analyze the pros and cons of nuclear energy for you...",
}

Output only valid JSON with double quotes, no comments or formatting.
