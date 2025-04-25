# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

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