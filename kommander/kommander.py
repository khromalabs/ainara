#!/usr/bin/env python3

import getopt
import json
import logging
import os
import re
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

                # Create a summary focused on command usage
                summary = ["You can use the following Orakle commands:"]

                # Add recipes with command format and return type
                if "recipes" in capabilities:
                    summary.append(
                        '\nRecipes (use with ```oraklecmd\\nRECIPE("name",'
                        " params)\\n```):"
                    )
                    for endpoint, recipe in capabilities["recipes"].items():
                        params = recipe.get("parameters", [])
                        param_dict = {}

                        # Build parameter dictionary for example
                        for param in params:
                            param_name = param["name"]
                            param_type = param.get("type", "string")
                            param_dict[param_name] = f"<{param_type}>"

                        # Create example command
                        example = f'RECIPE("{endpoint}", {param_dict})'
                        summary.append(f"- {example}")

                        # Add description if available
                        if recipe.get("description"):
                            summary.append(f"  Purpose: {recipe['description']}")

                        # Add return type if available
                        if "flow" in recipe and recipe["flow"]:
                            last_step = recipe["flow"][-1]
                            if last_step.get("output_type"):
                                summary.append(
                                    f"  Returns: {last_step['output_type']}"
                                )

                        if any(p.get("description") for p in params):
                            summary.append("  Parameters:")
                            for p in params:
                                if p.get("description"):
                                    summary.append(
                                        f"    {p['name']}: {p['description']}"
                                    )

                # Add skills with command format
                if "skills" in capabilities:
                    summary.append(
                        '\nSkills (use with ```oraklecmd\\nSKILL("name",'
                        " params)```):"
                    )
                    for skill_name, skill_info in capabilities[
                        "skills"
                    ].items():
                        if "run" in skill_info:
                            run_info = skill_info["run"]
                            params = {}

                            # Build parameter dictionary for example
                            if run_info.get("parameters"):
                                for param_name, param_info in run_info[
                                    "parameters"
                                ].items():
                                    param_type = param_info.get("type", "any")
                                    params[param_name] = f"<{param_type}>"

                            # Create example command
                            example = f'SKILL("{skill_name}", {params})'
                            summary.append(f"- {example}")

                            # Add parameter descriptions and return type if
                            # available
                            if run_info.get("description"):
                                summary.append(
                                    f"  Purpose: {run_info['description']}"
                                )
                            if run_info.get("return_type"):
                                summary.append(
                                    f"  Returns: {run_info['return_type']}"
                                )
                            if run_info.get("parameters"):
                                summary.append("  Parameters:")
                                for param_name, param_info in run_info[
                                    "parameters"
                                ].items():
                                    if param_info.get("description"):
                                        desc = param_info.get(
                                            "description", ""
                                        )
                                        summary.append(
                                            f"    {param_name}:{desc}"
                                        )

                return "\n".join(summary)
        except requests.RequestException:
            continue
    return None


orakle_caps = get_orakle_capabilities()
current_date = datetime.now()

SYSTEM_MESSAGE = f"""
You are a helpful, respectful and honest assistant. Don't be neutral.
Have opinions. Strong opinions are better, but not mandatory. Just express
those opinions with a baseline of politeness. Short answers are better, but
don't omit details if you consider them important. Whenever you are completely
or partially unsure about the answer to any question asked just
admit it frankly.

Today's date in YYYY-MM-DD format is: {datetime.now().strftime('%Y-%m-%d')}

To fullfil the user requests, there are especial commands available to be used
by you in this chat, which will be called by this chat utility to the Orakle
API server. Orakle is a powerful server that provides various capabilities
through skills and recipes:

1. Skills: Individual components for specific tasks like text processing,
   HTML parsing, News searching, Web content downloading, etc

2. Recipes: Pre-defined workflows that combine multiple skills for complex
   tasks. They accept input parameters and execute skills in sequence.

To use these capabilities, you can send single commands wrapped in
```oraklecmd``` blocks like this:
- `SKILL("skill_name", {{ "parameter1": "value1"...)`:
  For direct skill execution
- `RECIPE("recipe_name", {{ "parameter1": "value1"...)`:
  For running multi-step workflows

{orakle_caps}
"""

print(f"SYSTEM_MESSAGE: {SYSTEM_MESSAGE}")


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
    if "BACKUP" in globals() and BACKUP:
        with open(BACKUP, "a") as f:
            f.write(content + "\n")
            f.close()


def execute_orakle_command(command_block):
    """Execute an Orakle command and return the result"""
    for server in ORAKLE_SERVERS:
        try:
            # Extract command type and parameters
            match = re.match(
                r'(SKILL|RECIPE)\("([^"]+)",\s*({[^}]+})', command_block
            )
            if not match:
                return "Error: Invalid command format"

            cmd_type, cmd_name, params_str = match.groups()
            try:
                params = json.loads(params_str)
            except json.JSONDecodeError:
                return "Error: Invalid JSON parameters"

            # Make request to Orakle server
            endpoint = f"{server}/{cmd_type.lower()}/{cmd_name}"
            response = requests.post(endpoint, json=params, timeout=30)

            if response.status_code == 200:
                return json.dumps(response.json(), indent=2)
            else:
                return f"Error: Server returned {response.status_code}"

        except requests.RequestException:
            continue
    return "Error: No Orakle servers available"


def process_orakle_commands(text):
    """Process any oraklecmd blocks in the text and return modified text"""

    def replace_command(match):
        command = match.group(1).strip()
        result = execute_orakle_command(command)
        return f"```oraklecmd\n{command}\n```\nResult:\n```json\n{result}\n```"

    pattern = r"```oraklecmd\n(.*?)\n```"
    return re.sub(pattern, replace_command, text, flags=re.DOTALL)


def chat_completion(question, stream=True) -> str:
    answer = llm.process_text(
        text=question,
        system_message=SYSTEM_MESSAGE,
        chat_history=CHAT,
        stream=stream,
    )
    if answer:
        # Process any Orakle commands in the response
        processed_answer = process_orakle_commands(answer)
        backup(processed_answer)
        CHAT.extend([question, trim(processed_answer)])
        return processed_answer
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
