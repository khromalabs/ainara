#!/usr/bin/env python3

import contextlib
import getopt
import os
import signal
import sys
from datetime import datetime

import requests
import setproctitle
from prompt_toolkit import prompt
from prompt_toolkit.styles import Style

# Redirect stderr to /dev/null for LiteLLM import
with contextlib.redirect_stderr(open(os.devnull, "w")):
    import litellm

from litellm import completion


# Comment this line to disable the automatic chat backup
BACKUP = f"/tmp/chat_ai_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
CHAT = []
SYSTEM_MESSAGE = """
You are a helpful, respectful and honest assistant. Don't be neutral.
Have opinions. Strong opinions are better, but not mandatory. Just express
those opinions with a baseline of politeness. Short answers are better, but
don't omit details if you consider them important. Whenever you are completely
or partially unsure about the answer to any question asked by the user just
admit it frankly.
"""

PROVIDERS = [
    {
        "model": "openai/gamingpc",
        "api_base": "http://127.0.0.1:7080",
        "api_key": "nokey",
    },
    {
        "model": "openai/gamingpc",
        "api_base": "http://192.168.1.200:7080",
        "api_key": "nokey",
    },
    # Add more providers as needed
]


def find_working_provider():
    for provider in PROVIDERS:
        try:
            # Check if the provider's API base is reachable
            response = requests.head(provider["api_base"])
            if response.status_code == 200:
                return provider
        except requests.RequestException:
            continue
    print("No working LLM provider found, exiting...")
    sys.exit(1)


def parse_arguments():
    model = os.environ.get("AI_API_MODEL")
    light_mode = False
    strip_mode = False
    usage = (
        f"Usage: {os.path.basename(__file__)} [-l|--light] [-m|--model"
        " LLM_MODEL] [-s|--strip]\n\n-l|--light    Use colors for light"
        " themes\n-m|--model    Model as specified in the LLMLite"
        " definitions\n-s|--strip    Strip everything except code"
        " blocks in non-interactive mode"
        "\n\nFirst message can be send also with a stdin pipe"
        " which will be processed in non-interactive mode\n"
    )
    try:
        opts, _ = getopt.getopt(
            sys.argv[1:], "hlms", ["help", "light", "model=", "strip"]
        )
        for opt, arg in opts:
            if opt in ("-h", "--help"):
                print(usage)
                sys.exit()
            if opt in ("-l", "--light"):
                light_mode = True
            if opt in ("-m", "--model"):
                if not model:
                    model = arg
            if opt in ("-s", "--strip"):
                strip_mode = True
    except getopt.GetoptError as err:
        print(err)
        sys.exit(2)
    return model, light_mode, strip_mode


def trim(s):
    return s.strip()


def format_chat_messages(new_message):
    messages = [{"role": "system", "content": SYSTEM_MESSAGE}]
    for i in range(0, len(CHAT), 2):
        messages.append({"role": "user", "content": CHAT[i]})
        if i + 1 < len(CHAT):
            messages.append({"role": "assistant", "content": CHAT[i + 1]})
    messages.append({"role": "user", "content": new_message})
    return messages


def backup(content):
    if 'BACKUP' in globals() and BACKUP:
        with open(BACKUP, "a") as f:
            f.write(content + "\n")
            f.close()


def chat_completion(question, stream=True) -> str:
    messages = format_chat_messages(question)

    try:
        completion_kwargs = {
            "model": PROVIDER["model"],
            "messages": messages,
            "temperature": 0.2,
            "stream": stream,
        }

        if PROVIDER:
            completion_kwargs["api_base"] = PROVIDER["api_base"]
            completion_kwargs["api_key"] = PROVIDER["api_key"]

        response = completion(**completion_kwargs)
        answer = ""

        if stream:
            for chunk in response:
                if (
                    hasattr(chunk.choices[0], "delta")
                    and chunk.choices[0].delta.content is not None
                ):
                    content = chunk.choices[0].delta.content
                elif hasattr(chunk.choices[0], "text"):
                    content = chunk.choices[0].text
                else:
                    continue

                print(content, end="", flush=True)
                answer += content
        else:
            # For non-streaming mode, get the full response at once
            if hasattr(response.choices[0], "message"):
                answer = response.choices[0].message.content
            else:
                answer = response.choices[0].text

        answer = answer.rstrip("\n")
        backup(answer)
        CHAT.extend([question, trim(answer)])
        return answer
    except Exception:
        print(
            "\nError: Unable to get a response from the AI. Please try again."
        )


def signal_handler(sig, frame):
    print(f"{signal.Signals(sig).name} caught, exiting...")
    sys.exit(0)


def extract_code_blocks(text):
    blocks = []
    in_block = False
    current_block = []

    for line in text.split('\n'):
        if line.strip().startswith('```'):
            if in_block:
                in_block = False
            else:
                in_block = True
            continue

        if in_block:
            current_block.append(line)
        elif current_block:
            blocks.append('\n'.join(current_block))
            current_block = []

    if current_block:  # Handle case where text ends while still in a block
        blocks.append('\n'.join(current_block))

    return '\n\n'.join(blocks)


def main():
    global PROVIDER
    model_override, light_mode, strip_mode = parse_arguments()
    if model_override:
        PROVIDER = {"model": model_override, "api_base": None, "api_key": None}
    else:
        PROVIDER = find_working_provider()
    setproctitle.setproctitle(os.path.basename(__file__))
    signal.signal(signal.SIGINT, signal_handler)
    prompt_style = Style.from_dict(
        {
            "": "#006600" if light_mode else "#00ff00",
        }
    )

    # Check if input is coming from a pipe (non-interactive)
    if not sys.stdin.isatty():
        initial_message = sys.stdin.read().strip()
        if initial_message:
            backup(f"> {initial_message}")
            response = chat_completion(initial_message, stream=not strip_mode)
            if strip_mode:
                print(extract_code_blocks(response), end='')
            else:
                print()
        # Exit after processing the piped input
        sys.stdin.close()
        sys.stdout.flush()
        return

    # Interactive mode
    while True:
        try:
            question = prompt("> ", style=prompt_style).strip()
            if not question:
                continue
            backup(f"> {question}")
            chat_completion(question)
            print()
        except KeyboardInterrupt:
            signal_handler(signal.SIGINT, 0)
            break


if __name__ == "__main__":
    main()
