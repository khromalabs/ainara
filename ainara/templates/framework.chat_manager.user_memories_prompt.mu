Here is a summary, listed as `memories`, of what I know about the user, based on our past conversations. I will use this information to provide a more personalized and relevant response. Each memory includes a relevance score, a timestamp, and context tags to help me judge its importance and nature. I'll give priority to the memories with a higher relevance. In case of contradiction between memories, the memory with the higher relevance is ALWAYS considered as the truth.

*Known User Facts & Preferences:**
{{#memories}}
- **Memory:** {{{memory}}}
  - **Relevance:** {{relevance}}
  - **Last Mentioned:** {{last_updated}}
  - **Context:** {{#context_tags}}{{{.}}}, {{/context_tags}}
{{/memories}}
