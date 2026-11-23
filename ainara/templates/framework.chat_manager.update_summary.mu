Below is a previous summary of a conversation:

{{current_summary}}

Now summarize the following additional conversation and integrate it with the previous summary.
IMPORTANT: The TOTAL integrated summary must not exceed {{max_summary_tokens}} tokens (approximately {{max_summary_chars}} characters).
If needed, remove less important details from the previous summary to make room for new information.
Focus on maintaining a coherent overview that prioritizes recent and important information:

{{conversation_text}}

After the summary, output exactly one more line in this format (nothing else after it):
Topic: <2-5 word label for what this conversation is about>
If the conversation has not clearly moved on to something new, keep the previous topic: {{current_topic}}

Updated summary:
