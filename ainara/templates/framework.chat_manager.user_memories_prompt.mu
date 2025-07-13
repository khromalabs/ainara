Here is a summary, listed as `memories`, of what you know about the user, based on your past conversations. You must use this information to provide a more personalized and relevant response. Each memory includes a relevance score, a timestamp, and context tags to help you judge its importance and nature. You must give priority to the memories with a higher relevance. In case of contradiction between memories, the memory with the higher relevance is ALWAYS considered as the truth.

*Known User Facts & Preferences:**
{{#memories}}
- **Memory:** {{{memory}}}
  - **Relevance:** {{relevance}}
  - **Last Mentioned:** {{last_updated}}
  - **Context:** {{#context_tags}}{{{.}}}, {{/context_tags}}
{{/memories}}
