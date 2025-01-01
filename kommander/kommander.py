#!/usr/bin/env python3

import getopt
import logging
import os
import signal
import sys
import warnings
from datetime import datetime

import requests
import setproctitle
from prompt_toolkit import prompt
from prompt_toolkit.styles import Style

from ainara.framework.llm_backend import LiteLLMBackend

# Suppress pydantic warning about config keys
warnings.filterwarnings(
    "ignore", message="Valid config keys have changed in V2:*"
)

# Comment this line to disable the automatic chat backup
BACKUP = f"/tmp/chat_ai_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
CHAT = []
SYSTEM_MESSAGE = """
You are a helpful, respectful and honest assistant. Don't be neutral.
Have opinions. Strong opinions are better, but not mandatory. Just express
those opinions with a baseline of politeness. Short answers are better, but
don't omit details if you consider them important. Whenever you are completely
or partially unsure about the answer to any question asked just
admit it frankly.
"""

ORAKLE_SERVERS = [
    "http://127.0.0.1:5000",
    "http://192.168.1.200:5000",
]

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
]

logger = logging.getLogger()
llm = LiteLLMBackend()


def get_orakle_capabilities():
    """Query Orakle servers for capabilities, return a condensed summary"""
    for server in ORAKLE_SERVERS:
        try:
            response = requests.get(f"{server}/capabilities", timeout=2)
            if response.status_code == 200:
                capabilities = response.json()

                # Create a condensed summary
                summary = ["Available Orakle capabilities:"]

                # Add recipes with their full descriptions
                if "recipes" in capabilities:
                    summary.append("\nRecipes:")
                    for endpoint, recipe in capabilities["recipes"].items():
                        params = recipe.get("parameters", [])
                        required_skills = recipe.get("required_skills", [])

                        # Add endpoint and description
                        summary.append(f"- {endpoint}")

                        # Add parameters with descriptions if available
                        if params:
                            summary.append("  Parameters:")
                            for param in params:
                                param_desc = []
                                param_desc.append(f"    - {param['name']}")
                                if param.get("description"):
                                    param_desc.append(
                                        "      Description:"
                                        f" {param['description']}"
                                    )
                                if param.get("type"):
                                    param_desc.append(
                                        f"      Type: {param['type']}"
                                    )
                                if param.get("optional"):
                                    param_desc.append("      Optional: Yes")
                                summary.extend(param_desc)

                        # Add required skills info
                        if required_skills:
                            summary.append(
                                "  Required skills:"
                                f" {', '.join(required_skills)}"
                            )

                # Add skills with their descriptions
                if "skills" in capabilities:
                    summary.append("\nSkills:")
                    for skill_name, skill_info in capabilities[
                        "skills"
                    ].items():
                        summary.append(f"- {skill_name}")
                        if skill_info.get("description"):
                            summary.append(
                                f"  Description: {skill_info['description']}"
                            )

                        # Add run method info if available
                        if "run" in skill_info:
                            run_info = skill_info["run"]
                            if run_info.get("description"):
                                summary.append(
                                    f"  Run method: {run_info['description']}"
                                )

                            # Add parameters info
                            if run_info.get("parameters"):
                                summary.append("  Parameters:")
                                for param_name, param_info in run_info[
                                    "parameters"
                                ].items():
                                    param_desc = []
                                    param_desc.append(f"    - {param_name}")
                                    if param_info.get("type"):
                                        param_desc.append(
                                            f"      Type: {param_info['type']}"
                                        )
                                    if param_info.get("required"):
                                        param_desc.append(
                                            "      Required: Yes"
                                        )
                                    if param_info.get("default"):
                                        param_desc.append(
                                            "      Default:"
                                            f" {param_info['default']}"
                                        )
                                    summary.extend(param_desc)

                return "\n".join(summary)
        except requests.RequestException:
            continue
    return None


orakle_caps = get_orakle_capabilities()

print(f"orakle_caps: {orakle_caps}")


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

    # Add Orakle capabilities if available
    if orakle_caps:
        messages.append(
            {
                "role": "system",
                "content": (
                    "\nYou have access to the following Orakle"
                    f" capabilities:\n{orakle_caps}"
                ),
            }
        )
    for i in range(0, len(CHAT), 2):
        messages.append({"role": "user", "content": CHAT[i]})
        if i + 1 < len(CHAT):
            messages.append({"role": "assistant", "content": CHAT[i + 1]})
    messages.append({"role": "user", "content": new_message})
    return messages


def backup(content):
    if "BACKUP" in globals() and BACKUP:
        with open(BACKUP, "a") as f:
            f.write(content + "\n")
            f.close()


def chat_completion(question, stream=True) -> str:
    answer = llm.process_text(
        text=question,
        system_message=SYSTEM_MESSAGE,
        chat_history=CHAT,
        stream=stream,
    )
    if answer:
        backup(answer)
        CHAT.extend([question, trim(answer)])
    return answer


def signal_handler(sig, frame):
    print(f"{signal.Signals(sig).name} caught, exiting...")
    sys.exit(0)


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
                print(extract_code_blocks(response), end="")
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
