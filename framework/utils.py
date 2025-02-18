from colorama import Fore, Style
import json


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
            f"  {Fore.GREEN}{k}{Style.RESET_ALL}:"
            f" {Fore.YELLOW}{repr(v)}{Style.RESET_ALL}"
            for k, v in params_dict.items()
        )
    except json.JSONDecodeError:
        formatted_params = params

    # Build formatted command
    return (
        f"{Fore.CYAN}╭─ {cmd_type}{Style.RESET_ALL} "
        f"{Fore.LIGHTBLUE_EX}{name}{Style.RESET_ALL}\n"
        f"{Fore.CYAN}╰─ Parameters:{Style.RESET_ALL}\n"
        f"{formatted_params}"
    )
