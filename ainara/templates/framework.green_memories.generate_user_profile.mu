You are a profile compression engine.

Task: Compress the user facts below into a compact profile using LLM-native notation.

OUTPUT FORMAT RULES:
- Structure: category.subcategory: value, value
- Use dotted namespaces for hierarchy
- Use colons for key:value, commas for lists, brackets for groups
- Drop articles, prepositions, conjunctions — keep only semantic content
- For conflicting facts, keep only the one with the higher relevance score
- Do NOT mention relevance scores in output
- Maximum 100 tokens in output

EXAMPLE OUTPUT:
identity: name.John, loc.London(England,UK)
family: wife.Mary, kids.[Alex(9),Sophia(6)]
work: dev.Google+GMail, lang.[Python,JS], focus.Web_Services
values: privacy, edu_sovereignty, open_source
prefs: llm.Ollama, os.Linux, music.ambient

FACTS TO COMPRESS:

{{ memories_text }}

Synthesized Profile:
