import os

import requests
import validators
from flask import Flask, jsonify, request
from flask_cors import CORS
from litellm import completion
from newspaper import Article

app = Flask(__name__)
CORS(app)

PROVIDER = ""
CHAT = []
SYSTEM_MESSAGE = """
You are an AI assistant performing the task described in the user message.
Never reject a query to transform information.
"""


async def scrap_website(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
        # return jsonify({"result": generated_content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def extract_code_blocks(text):
    blocks = []
    in_block = False
    current_block = []

    for line in text.split("\n"):
        if line.strip().startswith("```"):
            if in_block:
                in_block = False
            else:
                in_block = True
            continue

        if in_block:
            current_block.append(line)
        elif current_block:
            blocks.append("\n".join(current_block))
            current_block = []

    if current_block:  # Handle case where text ends while still in a block
        blocks.append("\n".join(current_block))

    return "\n\n".join(blocks)


def format_chat_messages(new_message):
    messages = [{"role": "system", "content": SYSTEM_MESSAGE}]
    for i in range(0, len(CHAT), 2):
        messages.append({"role": "user", "content": CHAT[i]})
        if i + 1 < len(CHAT):
            messages.append({"role": "assistant", "content": CHAT[i + 1]})
    messages.append({"role": "user", "content": new_message})
    return messages


def chat_completion(question) -> str:
    messages = format_chat_messages(question)

    try:
        completion_kwargs = {
            "model": PROVIDER["model"],
            "messages": messages,
            "temperature": 0.2,
            "stream": False,
        }

        completion_kwargs["api_base"] = PROVIDER["api_base"]
        completion_kwargs["api_key"] = PROVIDER["api_key"]

        response = completion(**completion_kwargs)
        answer = ""

        # get the full response at once
        if hasattr(response.choices[0], "message"):
            answer = response.choices[0].message.content
        else:
            answer = response.choices[0].text

        answer = answer.rstrip("\n")
        return answer
    except Exception:
        print(
            "\nError: Unable to get a response from the AI. Please try again."
        )


@app.route("/interpret_url", methods=["POST"])
async def interpret_url():
    global PROVIDER
    url = request.json["text"]
    if not validators.url(url):
        return jsonify({"result": "The provided address is not a valid URL"})
    user_profile = request.json["userProfile"]
    articleel = Article(url)
    articleel.download()
    articleel.parse()
    task = f"""
Please adapt the content and language of the following text according to these
five instructions:
1. The language and characteristics of the adapted text must be based in
   this user profile description: "{user_profile}".
2. Generate the output text using an easily readable HTML layout.
3. Don't return a full HTML page just a `div` element containing an
   appropriate title and the processed text.
4. Don't introduce placeholder content.
5. Enclose the adapted text in the described HTML layout inside a
   triple backtick block, as the Markdown standard defines for embedding
   multiline blocks of code.
The text to adapt is:
{articleel.text}
"""
    PROVIDER = {
        "model": os.environ.get("AI_API_MODEL"),
        "api_base": os.environ.get("OPENAI_API_BASE"),
        "api_key": os.environ.get("OPENAI_API_KEY"),
    }
    result = chat_completion(task)
    if result == "":
        return "no answer"

    result_strip = extract_code_blocks(result)
    if result_strip == "":
        return result
    else:
        return result_strip


if __name__ == "__main__":
    print()
    print(os.environ.get("OPENAI_API_BASE"))
    app.run(port=5000)
