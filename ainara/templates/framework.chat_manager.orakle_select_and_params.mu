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
skill_id, parameters, frustration_level, frustration_reason, reasoning_level{{^agentic_mode}}, skill_intention, requires_agent{{/agentic_mode}}.

Instructions:
1. Choose the skill which better suits the user request. IMPORTANT: Use only the exact parameters defined in the skill specification.
2. Skip optional parameters unless needed.
3. If no skill{{^agentic_mode}} or combination of skills (using requires_agent){{/agentic_mode}} fits, but query clearly seeks for information, use search_web skill as shown in example.
4. If no skill fits the query intent, return an empty skill_id and add error_msg.

Returned JSON object keys details:
- frustration_level (0.0-1.0): Detect frustration, confusion, or dissatisfaction in the query.
- frustration_reason: Brief explanation if frustration, otherwise null.
- reasoning_level (0.0-1.0): 0.0 for direct commands, higher for analysis/comparison/planning tasks.
{{^agentic_mode}}
- skill_intention: Conversational sentence action preview in {{language}}, which will be use to introduce the action. Be natural, match user's tone, avoid jargon. Never mention any subject as a third person in the skill intention, because that subject might be the user and mentioning them that way sounds odd.
- requires_agent (boolean): true only when the request spans MULTIPLE capabilities or needs sequenced external actions between them (e.g., "look first for X then Y", "compare A and B", "research and summarize", "do X, also Y, and send Z"). For such multi-capability requests ALWAYS return requires_agent: true — never select one skill and silently drop the rest of the request. EXCEPTION: if a candidate skill's card declares compound scope (it handles multi-part requests in a single execution), that skill takes the whole request directly — return requires_agent: false and pass every part to it (in the query and its parameters); the skill's internal steps cover the entire request and return one unified result.
{{/agentic_mode}}

Result example (skill):

{
  "skill_id": "search_web",
  "parameters": {"query": "analyze pros and cons of nuclear energy"},
  "reasoning_level": 0.7{{^agentic_mode}},
  "frustration_level": 0.0,
  "frustration_reason": null,
  "requires_agent": false
  "skill_intention": "I'll analyze the pros and cons of nuclear energy for you...",
{{/agentic_mode}}

}

{{^agentic_mode}}

Result example 2 (agent):

{
  "skill_id": null,
  "parameters": {},
  "skill_intention": "This requires multiple steps. Let me work on that...",
  "frustration_level": 0.0,
  "frustration_reason": null,
  "reasoning_level": 0.5,
  "requires_agent": true
}
{{/agentic_mode}}

Output only valid JSON with double quotes, no comments or formatting.
