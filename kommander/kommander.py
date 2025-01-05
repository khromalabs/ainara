#!/usr/bin/env python3

import getopt
import json
import os
import re
import signal
import sys
import warnings
from datetime import datetime

import requests
import setproctitle
from colorama import Fore, init
from prompt_toolkit import prompt
from prompt_toolkit.styles import Style

from ainara.framework.llm_backend import LiteLLMBackend
from ainara.framework.logging_setup import logger, logging_manager

init()

# Set up logging first, before any logger calls
logging_manager.setup(log_dir="kommander")

# Suppress pydantic warning about config keys
warnings.filterwarnings(
    "ignore", message="Valid config keys have changed in V2:*"
)


# Comment this line to disable the automatic chat backup
BACKUP = f"/tmp/kommander_ai_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
CHAT = []


ORAKLE_SERVERS = [
    "http://127.0.0.1:5000",
    # "http://192.168.1.200:5000",
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

llm = LiteLLMBackend()


def get_orakle_capabilities():
    """Query Orakle servers for capabilities, return a condensed summary"""
    logger.info("Retrieving Orakle server capabilities...")
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

                        # Build parameter dictionary for example with proper
                        # JSON formatting
                        for param in params:
                            param_name = param["name"]
                            param_type = param.get("type", "string")
                            # Use a placeholder value based on type
                            if param_type == "string":
                                param_dict[param_name] = "value"
                            elif param_type == "integer":
                                param_dict[param_name] = 0
                            elif param_type == "boolean":
                                param_dict[param_name] = False
                            else:
                                param_dict[param_name] = "value"

                        # Create example command with properly formatted JSON
                        json_params = json.dumps(param_dict)
                        example = f'RECIPE("{endpoint}", {json_params})'
                        summary.append(f"- {example}")

                        # Add description if available
                        if recipe.get("description"):
                            summary.append(
                                f"  Purpose: {recipe['description']}"
                            )

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

                            # Build parameter dictionary for example with
                            # proper JSON formatting
                            if run_info.get("parameters"):
                                for param_name, param_info in run_info[
                                    "parameters"
                                ].items():
                                    param_type = param_info.get("type", "any")
                                    # Use a placeholder value based on type
                                    if param_type == "string":
                                        params[param_name] = "value"
                                    elif param_type == "integer":
                                        params[param_name] = 0
                                    elif param_type == "boolean":
                                        params[param_name] = False
                                    else:
                                        params[param_name] = "value"

                            # Create example command with properly formatted
                            # JSON
                            json_params = json.dumps(params)
                            example = f'SKILL("{skill_name}", {json_params})'
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

                logger.info("...done")
                return "\n".join(summary)
        except requests.RequestException:
            continue
    return (
        "WARNING: No Orakle capabilities found, is the Orakle server running?"
    )


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
by you in this chat, which will be send by this chat utility to the Orakle
API server. Orakle is a powerful server that provides various capabilities
through skills and recipes:

1. Skills: Individual components for specific tasks.

2. Recipes: Pre-defined workflows that combine multiple skills for complex
   tasks. Recipes execute skills in sequence.

Both skills and recipes accept input parameters and return processed data.

To use these capabilities, you must send single commands wrapped in tripe
backticks ```oraklecmd``` blocks like this:
- `SKILL("skill_name", {{ "parameter1": "value1"...)`:
  For direct skill execution
- `RECIPE("recipe_name", {{ "parameter1": "value1"...)`:
  For running multi-step workflows

Don't suggest the user to use Orakle commands, as are meant to be used by you
the assistant. Don't mention in the chat that you are executing an Orakle
command, just send the oraklecmd block.

Give priority to recipes if, and only if, a user request completely fits the
recipe purpose. Don't give priority to recipes in any other case.

Orakle commands are processed one at a time, don't send more than one Orakle
command per answer.

{orakle_caps}
"""


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
    log_dir = None
    log_level = "INFO"
    usage = (
        f"Usage: {os.path.basename(__file__)} [-l|--light] [-m|--model"
        " LLM_MODEL] [-s|--strip] [--log-dir DIR] [--log-level"
        " LEVEL]\n\n-l|--light    Use colors for light themes\n-m|--model   "
        " Model as specified in the LLMLite definitions\n-s|--strip    Strip"
        " everything except code blocks in non-interactive mode\n--log-dir   "
        " Directory for log files\n--log-level   Logging level"
        " (DEBUG,INFO,WARNING,ERROR,CRITICAL)\n\nFirst message can be send"
        " also with a stdin pipe which will be processed in non-interactive"
        " mode\n"
    )
    try:
        opts, _ = getopt.getopt(
            sys.argv[1:],
            "hlms",
            ["help", "light", "model=", "strip", "log-dir=", "log-level="],
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
            if opt == "--log-dir":
                log_dir = arg
            if opt == "--log-level":
                log_level = arg.upper()
    except getopt.GetoptError as err:
        print(err)
        sys.exit(2)
    return model, light_mode, strip_mode, log_dir, log_level


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
                r'(SKILL|RECIPE)\("/?([^"]+)",\s*({[^}]+})', command_block
            )
            if not match:
                return (
                    'Error: Invalid command format. Expected SKILL("name",'
                    ' {params}) or RECIPE("name", {params})'
                )

            cmd_type, cmd_name, params_str = match.groups()
            try:
                params = json.loads(params_str)
            except json.JSONDecodeError as e:
                return f"Error: Invalid JSON parameters - {str(e)}"

            # Make request to Orakle server
            # Remove any leading/trailing slashes from cmd_name
            cmd_name = cmd_name.strip("/")
            # Always use plural form for endpoints
            endpoint_type = f"{cmd_type.lower()}s"
            endpoint = f"{server.rstrip('/')}/{endpoint_type}/{cmd_name}"
            response = requests.post(endpoint, json=params, timeout=30)

            if response.status_code == 200:
                try:
                    # First try to parse as JSON
                    json_response = response.json()
                    # print(f"json_response: {json_response}")
                    # Handle empty responses
                    if not json_response:
                        return "Empty response received"
                    # Handle both string and dict responses
                    if isinstance(json_response, str):
                        return json_response
                    return json.dumps(json_response, indent=2)
                except json.JSONDecodeError:
                    # If not JSON, return the raw text response
                    text_response = response.text
                    # print(f"text_response: {text_response}")
                    return text_response if text_response else "Empty response"
            else:
                error_msg = f"Error: Server returned {response.status_code}"
                try:
                    error_details = response.json()
                    error_msg += (
                        f"\nDetails: {json.dumps(error_details, indent=2)}"
                    )
                except (ValueError, json.JSONDecodeError):
                    if response.text:
                        error_msg += f"\nDetails: {response.text}"
                return error_msg

        except requests.RequestException:
            continue
    return "Error: No Orakle servers available"


def format_orakle_command(command: str) -> str:
    """Format Orakle command with colors and layout"""
    import re

    # Extract command parts
    match = re.match(
        r'(SKILL|RECIPE)\("([^"]+)",\s*({[^}]+})', command.strip()
    )
    if not match:
        return command

    cmd_type, name, params = match.groups()

    # Parse and format parameters
    try:
        params_dict = json.loads(params)
        formatted_params = "\n".join(
            f"  {Fore.CYAN}{k}{Style.RESET_ALL}:"
            f" {Fore.YELLOW}{repr(v)}{Style.RESET_ALL}"
            for k, v in params_dict.items()
        )
    except json.JSONDecodeError:
        formatted_params = params

    # Build formatted command
    return (
        f"{Fore.GREEN}╭─ {cmd_type}{Style.RESET_ALL} "
        f"{Fore.BLUE}{name}{Style.RESET_ALL}\n"
        f"{Fore.GREEN}╰─{Style.RESET_ALL} Parameters:\n"
        f"{formatted_params}"
    )


def process_orakle_commands(text):
    """
    Process any oraklecmd blocks in the text and return results and command
    types
    """
    results = []
    command_types = []

    def replace_command(match):
        command = match.group(1).strip()
        # Extract command type (SKILL or RECIPE)
        cmd_type_match = re.match(r"(SKILL|RECIPE)", command)
        if cmd_type_match:
            command_types.append(cmd_type_match.group(1))

        result = execute_orakle_command(command)
        results.append(result)
        formatted_cmd = command  # format_orakle_command(command)
        return f"{formatted_cmd}\n\nResult:\n```json\n{result}\n```"

    pattern = r"```oraklecmd\n(.*?)\n```"
    processed_text = re.sub(pattern, replace_command, text, flags=re.DOTALL)
    return processed_text, results, command_types


def chat_completion(question, stream=True) -> str:
    answer = llm.process_text(
        text=question,
        system_message=SYSTEM_MESSAGE,
        chat_history=CHAT,
        stream=stream,
    )
    if answer:
        # Process any Orakle commands in the response
        processed_answer, results, command_types = process_orakle_commands(
            answer
        )

        # If there are command results, ask LLM to interpret them
        if results:
            # Format results based on whether they are valid JSON or plain text
            formatted_results = []
            for r in results:
                try:
                    # Try to parse as JSON to validate and pretty print
                    json.loads(r)
                    formatted_results.append(f"```json\n{r}\n```")
                except json.JSONDecodeError:
                    # If not valid JSON, treat as plain text
                    formatted_results.append(f"```text\n{r}\n```")

            # Determine instruction based on command type
            if command_types and command_types[0] == "RECIPE":
                instruction = (
                    "This was a RECIPE command. Please reproduce the command"
                    " result verbatim in your response, maintaining all"
                    " formatting and structure. Add a brief introduction"
                    " explaining what the recipe did."
                )
            else:
                instruction = (
                    "This was a SKILL command. Don't reproduce the JSON "
                    "data received, if any, in your next answer"
                )

            interpretation_prompt = (
                "Based on the Orakle command results:\n"
                + "\n".join(formatted_results)
                + "\n\n"
                + instruction
            )
            print()

            final_answer = llm.process_text(
                text=interpretation_prompt,
                system_message=SYSTEM_MESSAGE,
                chat_history=CHAT,
                stream=stream,
            )

            if final_answer:
                processed_answer = final_answer
                # separator = "\n\nResult:\n" + "=" * 40 + "\n"
                # processed_answer += f"{separator}{final_answer}\n" + "=" * 40

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
    model_override, light_mode, strip_mode, log_dir, log_level = (
        parse_arguments()
    )
    if log_dir or log_level != "INFO":
        # Only reconfigure logging if custom options are provided
        logging_manager.setup(
            log_dir=log_dir, log_level=log_level, log_filter="kommander"
        )
    logger.debug(f"SYSTEM_MESSAGE: {SYSTEM_MESSAGE}")
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
