Given the following list of available skills, determine which skill(s) best
match the user's request.
Pay careful attention to the user request, fully understanding the query intention
and the most suitable skills for fulfilling the request. If the user is 
demanding in the query an specific skill by its name, give special priority to
that.

User request: {{{query}}}

If the user is asking for information that would require searching the internet
or retrieving current data (like facts, news, product details, etc),
prioritize general web search or research-related skills.
If multiple skills could be relevant, list them in order of relevance.
If you're unsure, you can suggest multiple potentially relevant skills.
Always provide at least one matching skill with the highest confidence possible.

Pay attention to any parameters mentioned in the user request that might help
determine which skill is most appropriate (e.g., specific sources, time periods,
locations, or other constraints). Skill list (format [name]: [description])

{{{skills_list}}}

Respond in this JSON format:
{
    "matches": [
        {
            "skill_id": "the_skill_id",
            "confidence": 0.9,  # between 0 and 1
            "reasoning": "Brief explanation of why this skill matches"
        }
    ]
}

Your response:
