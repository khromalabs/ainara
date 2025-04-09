Based on this skill description:

"{{{skill_description}}}"

Convert this natural language query: "{{{query}}}"
into a JSON object containing the parameters, following the specifications
of the previous skill description.

Pay special attention to the args (arguments) description.
Each parameter modifies how the skill functions, for example:

Args:
    <param_arg_name_1>: <param_arg_description_1>
    <param_arg_name_2>: <param_arg_description_2>

Optional Args:
    **kwargs:
        - <kwarg1>: <Optional argument to be enclosed in the kwarg dict>

Extract all relevant parameters from the user query. If a parameter isn't
explicitly mentioned but can be reasonably inferred, include it with an
appropriate value.

Example:
For a query "search for 20 recent news about AI regulation" to a web search skill:

{
    "query": "news about AI regulation",
    "source": "BBC",
    "recency": "recent"
    "kwargs": {
        "results": 20
    }
}

For empty values declare them as `null` not "None"
Enclose the JSON fields with double quotes.
Return ONLY the JSON object, no backticks, nothing else.
