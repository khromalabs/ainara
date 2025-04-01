# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez - khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, see
# <https://www.gnu.org/licenses/>

import json
# import pprint
import logging
import re
from typing import Any, Dict, Generator, List, Optional

import requests

from ainara.framework.matcher.llm import OrakleMatcherLLM
from ainara.framework.template_manager import TemplateManager

# from ainara.framework.utils import format_orakle_command

logger = logging.getLogger(__name__)


class OrakleMiddleware:
    """
    Middleware for processing Orakle commands in streaming LLM responses.

    This class handles the detection and execution of Orakle commands within
    a stream of text from an LLM, allowing for command processing without
    breaking the streaming experience.
    """

    def __init__(
        self,
        llm,
        orakle_servers: List[str],
        system_message: str,
        capabilities: Optional[dict] = None,
    ):
        """
        Initialize the OrakleMiddleware.

        Args:
            llm: The LLM instance to use for parameter generation
            orakle_servers: List of Orakle server URLs
            system_message: System message for LLM context
            capabilities: Optional pre-loaded capabilities dictionary
        """
        self.llm = llm
        self.orakle_servers = orakle_servers
        self.system_message = system_message
        self.template_manager = TemplateManager()
        self.matcher = OrakleMatcherLLM(llm)

        # Initialize capabilities
        if capabilities:
            self.capabilities = capabilities
        else:
            self.capabilities = {"recipes": [], "skills": []}
            self.capabilities = self.get_orakle_capabilities()

        # Register skills with the matcher
        for skill in self.capabilities["skills"]:
            self.matcher.register_skill(
                skill["name"],
                skill["description"],
                metadata={
                    "run_info": skill["run_info"],
                    "matcher_info": skill["matcher_info"],
                },
            )

    def process_stream(
        self, token_stream: Generator[str, None, None], chat_manager=None
    ) -> Generator[str, None, None]:
        """
        Process a stream of tokens, detecting, executing, and interpreting Orakle commands.

        Args:
            token_stream: Generator yielding tokens from the LLM
            chat_manager: Optional ChatManager instance to get chat history

        Yields:
            Processed tokens with executed and interpreted command results
        """
        buffer = ""
        command_buffer = ""
        in_command = False
        # PHP-style HEREDOC delimiters
        command_start_delimiter = "<<<ORAKLE"
        command_end_delimiter = "ORAKLE"

        for token in token_stream:
            if token is None:
                continue

            if in_command:
                command_buffer += token
                # Check if we've reached the end delimiter on a line by itself
                # This handles both "ORAKLE" and "ORAKLE;" endings
                if re.search(
                    r"(?:^|\n)"
                    + re.escape(command_end_delimiter)
                    + r"(?:;|\s*$)",
                    command_buffer,
                ):
                    # Extract the command content up to the end delimiter
                    match = re.search(
                        r"(.*?)(?:^|\n)"
                        + re.escape(command_end_delimiter)
                        + r"(?:;|\s*$)",
                        command_buffer,
                        re.DOTALL,
                    )
                    if match:
                        command_content = match.group(1).strip()

                        # Process the command and yield results
                        for chunk in self._process_command_content(
                            command_content, chat_manager
                        ):
                            yield chunk

                        # Find where the end delimiter ends
                        end_match = re.search(
                            r"(?:^|\n)"
                            + re.escape(command_end_delimiter)
                            + r"(?:;|\s*$)",
                            command_buffer,
                        )
                        end_pos = end_match.end()

                        # Yield any content after the end delimiter
                        remaining = command_buffer[end_pos:]
                        if remaining:
                            yield remaining

                        # Reset for next command
                        command_buffer = ""
                        in_command = False
            else:
                # Add token to buffer
                buffer += token

                # Check if buffer contains the start delimiter
                if command_start_delimiter in buffer:
                    # Extract everything up to the command
                    command_start = buffer.find(command_start_delimiter)
                    yield buffer[:command_start]

                    # Start collecting the command, excluding the start delimiter
                    after_delimiter = buffer[
                        command_start + len(command_start_delimiter):
                    ]
                    command_buffer = after_delimiter
                    buffer = ""
                    in_command = True
                elif len(buffer) > len(command_start_delimiter) + 10:
                    # Check if the end of the buffer could be the start of a delimiter
                    for i in range(
                        1, min(len(buffer), len(command_start_delimiter))
                    ):
                        if buffer.endswith(command_start_delimiter[:i]):
                            # Found a partial match at the end
                            yield buffer[:-i]
                            buffer = buffer[-i:]  # Keep only the partial match
                            break
                    else:
                        # No partial match found, safe to yield the entire buffer
                        yield buffer
                        buffer = ""

        # Yield any remaining content
        if buffer:
            yield buffer

        # Process any remaining command buffer
        if command_buffer and not in_command:
            yield command_buffer

    def _process_command_buffer(
        self, command_buffer: str, command_pattern: str, chat_manager=None
    ) -> Generator[str, None, None]:
        """
           Process a command buffer and yield results.

           Args:
            command_buffer: The buffer containing a potential command
            command_pattern: Regex pattern to match commands
            chat_manager: Optional ChatManager instance

        Yields:
            Processed command results or the original buffer if not a valid command
        """
        # Use re.DOTALL to make . match newlines as well
        match = re.search(command_pattern, command_buffer, re.DOTALL)
        if match:
            query = (
                match.group(1)
                .strip()
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )
            best_command = self._detect_command(query, chat_manager)
            skill_id = best_command["skill_id"]
            yield f"\nProcessing {skill_id}...\n\n"

            command_result = self._process_command(
                query, best_command, chat_manager
            )
            result = command_result.get("result", "No result")

            logger.info(f"ORAKLE command_result: {command_result}")

            # Get interpretation as a stream
            for interpretation_chunk in self.stream_command_interpretation(
                [result], query
            ):
                yield interpretation_chunk
        else:
            # Not a valid command, yield as-is
            yield command_buffer

    def _process_command_content(
        self, command_content: str, chat_manager=None
    ) -> Generator[str, None, None]:
        """
        Process command content extracted from HEREDOC format.

        Args:
            command_content: The command content between delimiters
            chat_manager: Optional ChatManager instance

        Yields:
            Processed command results
        """
        query = command_content.strip()
        best_command = self._detect_command(query, chat_manager)
        skill_id = best_command["skill_id"]
        yield f"\nProcessing {skill_id}...\n\n"

        command_result = self._process_command(
            query, best_command, chat_manager
        )
        result = command_result.get("result", "No result")

        logger.info(f"ORAKLE command_result: {command_result}")

        # Get interpretation as a stream
        for interpretation_chunk in self.stream_command_interpretation(
            [result], query
        ):
            yield interpretation_chunk

    def _detect_command(self, query: str, chat_manager=None) -> Dict[str, Any]:
        """
        Process an Orakle command query.

        Args:
            query: The query string from the ORAKLE command
            chat_manager: Optional ChatManager instance to get chat history

        Returns:
            Dictionary with command processing results
        """
        logger.info(f"ORAKLE Looking for matches for query: {query}")

        # Find matching skills using the matcher
        matches = self.matcher.match(query, threshold=0.05)

        if not matches:
            return {
                "skill_id": "error",
                "command": "none",
                "result": (
                    f"Request '{query}' didn't match any available skill."
                ),
                "command_type": "SKILL",
            }
        # logger.info("pformat:" + pprint.pformat(matches[0]))
        # Use the best matching skill
        return matches[0]

    def _process_command(
        self, query: str, best_match=Dict[str, Any], chat_manager=None
    ) -> Dict[str, Any]:
        skill_id = best_match["skill_id"]
        skill_description = best_match["description"]

        # Yield processing message before executing command
        # yield f"\nProcessing {skill_id}...\n\n"
        # logger.info(f"ORAKLE matches: {matches}")

        # Use LLM to convert natural language to structured parameters
        prompt = self.template_manager.render(
            "framework.chat_manager.orakle_prompt",
            {"skill_description": skill_description, "query": query},
        )

        logger.info(f"ORAKLE skill prompt: {prompt}")

        json_params = self.llm.chat(
            chat_history=self.llm.prepare_chat(
                system_message=self.system_message, new_message=prompt
            ),
            stream=False,
        )

        try:
            # Validate it's proper JSON
            params_dict = json.loads(json_params)
            # Determine if it's a SKILL or RECIPE from the ID
            cmd_type = (
                "SKILL" if not skill_id.startswith("recipe/") else "RECIPE"
            )

            # Format the command with the matched skill and LLM params
            command = f'{cmd_type}("{skill_id}", {json.dumps(params_dict)})'
        except json.JSONDecodeError:
            logger.error(f"LLM generated invalid JSON: {json_params}")
            # Fallback to simple query parameter
            cmd_type = (
                "SKILL" if not skill_id.startswith("recipe/") else "RECIPE"
            )
            command = f'{cmd_type}("{skill_id}", {{"query": "{query}"}})'
            # logger.error("PROCESS_COMMAND: {command}")

        result = self.execute_orakle_command(command, chat_manager)

        return {
            "skill_id": skill_id,
            "command": command,
            "result": result,
            "command_type": cmd_type,
        }

    def execute_orakle_command(
        self, command_block: str, chat_manager=None
    ) -> str:
        """
        Execute an Orakle command and return the result.

        Args:
            command_block: The formatted command string
            chat_manager: Optional ChatManager instance to get chat history

        Returns:
            Command execution result as a string
        """
        for server in self.orakle_servers:
            try:
                logger.info(f"ORAKLE Will execute command: {command_block}")
                # Extract command type and parameters
                match = re.match(
                    r'(SKILL|RECIPE)\("/?([^"]+)",\s*({.*})', command_block
                )
                if not match:
                    # logger.info("ORAKLE BAD COMMAND FORMAT")
                    return (
                        'Error: Invalid command format. Expected SKILL("name",'
                        ' {params}) or RECIPE("name", {params})'
                    )

                # logger.info("ORAKLE GOOD COMMAND FORMAT")

                cmd_type, cmd_name, params_str = match.groups()
                try:
                    params = json.loads(params_str)
                except json.JSONDecodeError as e:
                    # logger.info("ORAKLE JSON DECODE ERROR: " + params_str)
                    return f"Error: Invalid JSON parameters - {str(e)}"

                # Check if skill requires additional data
                cmd_name = cmd_name.strip("/")
                skill_info = self._get_skill_info(cmd_name)

                # Add chat history if the skill requires it and chat_manager is provided
                if chat_manager and any(
                    param.get("name") == "_chat_history"
                    for param in skill_info.get("parameters", [])
                ):
                    params = chat_manager.add_chat_history_to_params(
                        params, skill_info
                    )

                # logger.info(f"ORAKLE SKILL INFO: {skill_info}")
                # logger.info(f"ORAKLE PARAMS: {params}")

                # Make request to Orakle server
                endpoint_type = f"{cmd_type.lower()}s"
                endpoint = f"{server.rstrip('/')}/{endpoint_type}/{cmd_name}"

                # logger.info("ORAKLE WILL EXECUTE COMMAND IN " + endpoint)
                response = requests.post(endpoint, json=params, timeout=60)

                if response.status_code == 200:
                    try:
                        json_response = response.json()
                        if not json_response:
                            return "Empty response received"
                        if isinstance(json_response, str):
                            return json_response
                        return json.dumps(json_response, indent=2)
                    except json.JSONDecodeError:
                        text_response = response.text
                        return (
                            text_response
                            if text_response
                            else "Empty response"
                        )
                else:
                    error_msg = (
                        f"Error: Server returned {response.status_code}"
                    )
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

    def _get_skill_info(self, skill_id: str) -> dict:
        """
        Get information about a skill including its data requirements.

        Args:
            skill_id: The ID of the skill to look up

        Returns:
            Dictionary with skill information
        """
        # Look for the skill in our capabilities
        for skill in self.capabilities.get("skills", []):
            if skill["name"] == skill_id:
                return skill
        return {}

    def stream_command_interpretation(
        self, results: List[str], query: str
    ) -> Generator[str, None, None]:
        """
        Stream LLM interpretation of command results.

        Args:
            results: List of command result strings
            command_types: List of command type strings (SKILL/RECIPE)

        Yields:
            Chunks of the LLM interpretation as they become available
        """
        formatted_results = []
        for r in results:
            try:
                json.loads(r)
                formatted_results.append(f"```json\n{r}\n```")
            except json.JSONDecodeError:
                formatted_results.append(f"```text\n{r}\n```")

        interpretation_prompt = self.template_manager.render(
            "framework.chat_manager.command_interpretation",
            {
                "formatted_results": "\n".join(formatted_results),
                "query": query,
            },
        )

        logger.info(f"ORAKLE interpretation_prompt: {interpretation_prompt}")

        # Get interpretation as a stream
        interpretation_stream = self.llm.chat(
            chat_history=self.llm.prepare_chat(
                system_message=self.system_message,
                new_message=interpretation_prompt,
            ),
            stream=True,
        )

        # Yield each chunk as it comes
        for chunk in interpretation_stream:
            if chunk:
                yield chunk

    def _process_orakle_recipes(self, raw_capabilities: dict) -> List[dict]:
        """
        Process raw recipe capabilities into structured format.

        Args:
            raw_capabilities: Raw capabilities dictionary from Orakle server

        Returns:
            List of processed recipe dictionaries
        """
        recipes = []
        if "recipes" in raw_capabilities:
            for endpoint, recipe in raw_capabilities["recipes"].items():
                recipe_data = {
                    "name": endpoint,
                    "description": recipe.get("description", ""),
                    "parameters": recipe.get("parameters", []),
                }

                # Extract return type from flow if available
                if "flow" in recipe and recipe["flow"]:
                    last_step = recipe["flow"][-1]
                    recipe_data["return_type"] = last_step.get(
                        "output_type", ""
                    )

                recipes.append(recipe_data)
        return recipes

    def _process_orakle_skills(self, raw_capabilities: dict) -> List[dict]:
        """
        Process raw skill capabilities into structured format.

        Args:
            raw_capabilities: Raw capabilities dictionary from Orakle server

        Returns:
            List of processed skill dictionaries
        """
        skills = []
        if "skills" in raw_capabilities:
            for skill_name, skill_info in raw_capabilities["skills"].items():
                skill_data = {
                    "name": skill_name,
                    "description": (
                        skill_info.get("description", "").replace("\n", "")
                    ),
                    "matcher_info": (
                        skill_info.get("matcher_info", "").replace("\n", "")
                    ),
                    "run_info": skill_info.get("run", ""),
                    "parameters": [],
                }

                # Process parameters
                if skill_data["run_info"].get("parameters"):
                    run_info = skill_data["run_info"]
                    for param_name, param_info in run_info[
                        "parameters"
                    ].items():
                        param_data = {
                            "name": param_name,
                            "type": param_info.get("type", "any"),
                        }
                        skill_data["parameters"].append(param_data)

                skills.append(skill_data)
        return skills

    def get_orakle_capabilities(self) -> dict:
        """
        Query Orakle servers for capabilities and store them in structured format.

        Returns:
            Dictionary with processed capabilities
        """
        # capabilities = {"recipes": [], "skills": []}
        capabilities = {"skills": []}

        for server in self.orakle_servers:
            try:
                response = requests.get(f"{server}/capabilities", timeout=2)
                if response.status_code == 200:
                    raw_capabilities = response.json()

                    # Process recipes and skills
                    # capabilities["recipes"] = self._process_orakle_recipes(raw_capabilities)
                    capabilities["skills"] = self._process_orakle_skills(
                        raw_capabilities
                    )

                    return capabilities
            except requests.RequestException:
                continue

        logger.warning(
            "No Orakle capabilities found, is the Orakle server running?"
        )
        return capabilities
