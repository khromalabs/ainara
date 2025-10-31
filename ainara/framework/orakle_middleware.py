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


import importlib
import inspect
import json
# import pprint
import logging
# import re
import os
from typing import Generator, List, Optional, Union

import requests
from statemachine import State, StateMachine

from ainara.framework.config import ConfigManager
from ainara.framework.matcher.transformers import OrakleMatcherTransformers
from ainara.framework.system_skills.base import BaseSystemSkill
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
        config_manager: Optional[ConfigManager] = None,
    ):
        """
        Initialize the OrakleMiddleware.

        Args:
            llm: The LLM instance to use for parameter generation
            orakle_servers: List of Orakle server URLs
            system_message: System message for LLM context
            capabilities: Optional pre-loaded capabilities dictionary
            config_manager: Optional ConfigManager instance
        """
        self.llm = llm
        self.orakle_servers = orakle_servers
        self.system_message = system_message
        self.template_manager = TemplateManager()
        self.config_manager = config_manager or ConfigManager()

        # --- Matcher Configuration ---
        # Use transformer matcher
        matcher_model = self.config_manager.get(
            "orakle.matcher.model", "sentence-transformers/all-mpnet-base-v2"
        )
        self.matcher = OrakleMatcherTransformers(model_name=matcher_model)
        # Get threshold and top_k from config or use defaults
        self.matcher_threshold = self.config_manager.get(
            "orakle.matcher.threshold", 0.15
        )
        self.matcher_top_k = self.config_manager.get("orakle.matcher.top_k", 5)
        self.reasoning_effort_limit = self.config_manager.get(
            "orakle.reasoning_effort_limit", 1.0
        )
        logger.info(
            "Initialized OrakleMiddleware with Transformer Matcher:"
            f" model={matcher_model}, threshold={self.matcher_threshold},"
            f" top_k={self.matcher_top_k}"
        )
        logger.info(
            "OrakleMiddleware reasoning effort limit set to:"
            f" {self.reasoning_effort_limit}"
        )

        # Initialize capabilities
        if capabilities:
            self.capabilities = capabilities
        else:
            self.capabilities = []
            self.capabilities = self.get_orakle_capabilities()

        # --- System Skills ---
        # Load system skills from the framework's system_skills directory
        self.system_skills = {}
        self._load_system_skills()

        # Register skills with the matcher
        for skill in self.capabilities:
            self.matcher.register_skill(
                skill["name"],
                skill["description"],
                metadata={
                    "run_info": skill["run_info"],
                    "matcher_info": skill["matcher_info"],
                    "embeddings_boost_factor": skill.get("embeddings_boost_factor", 1.0),
                },
            )

        # logger.info("-----------------")
        # logger.info(pprint.pformat(skill))

    def _get_correction_message(self) -> str:
        """Returns a guardrail message for malformed ORAKLE commands."""
        logger.info("GUARDRAIL correction message generated")
        return (
            "\n\n[AINARA GUARDRAIL] Error: Malformed ORAKLE command detected. "
            "The `<<<ORAKLE` and `ORAKLE` delimiters must be on their own "
            "lines with no surrounding text. The command was not executed. "
            "Please try again with the correct format.\n\n"
        )

    def update_llm(self, llm):
        self.llm = llm

    class _OrakleParser(StateMachine):
        """A state machine to parse ORAKLE commands from a stream."""

        # States
        streaming_text = State(initial=True)
        buffering_command = State()

        def __init__(self, middleware, chat_manager, reasoning_level_heuristic=0.0):
            self.middleware = middleware
            self.chat_manager = chat_manager
            self.command_buffer = ""
            self.start_delimiter = "<<<ORAKLE"
            self.end_delimiter = "ORAKLE"
            self.reasoning_level_heuristic = reasoning_level_heuristic
            super().__init__()

        def process_line(self, line: str) -> Generator[str, None, None]:
            """Process a single line of input from the stream."""
            stripped_line = line.strip()

            if self.current_state == self.streaming_text:
                # Check for single-line command first
                if (
                    stripped_line != self.start_delimiter
                    and stripped_line.startswith(self.start_delimiter)
                ) and (
                    stripped_line.endswith(self.end_delimiter)
                    or stripped_line.endswith(self.end_delimiter + ";")
                ):
                    end_len = len(self.end_delimiter)
                    if stripped_line.endswith(";"):
                        end_len += 1
                    command_content = stripped_line[
                        len(self.start_delimiter): -end_len
                    ].strip()
                    yield from self._execute_command(command_content)
                    # Preserve the newline from the original line
                    if line.endswith("\n"):
                        yield "\n"
                elif stripped_line == self.start_delimiter:
                    self.start_command()
                elif (
                    self.start_delimiter in stripped_line
                    or self.end_delimiter in stripped_line
                ):
                    yield line
                    yield self.middleware._get_correction_message()
                else:
                    yield line
            elif self.current_state == self.buffering_command:
                if (
                    stripped_line == self.end_delimiter
                    or stripped_line == self.end_delimiter + ";"
                ):
                    yield from self.end_command()
                    # Preserve the newline from the original line
                    if line.endswith("\n"):
                        yield "\n"
                elif self.end_delimiter in stripped_line:
                    yield self.command_buffer
                    yield line
                    yield self.middleware._get_correction_message()
                    self.malformed_end()
                else:
                    self.command_buffer += line

        # Transitions
        start_command = streaming_text.to(buffering_command)
        end_command = buffering_command.to(streaming_text, on="_on_end_command")
        malformed_end = buffering_command.to(streaming_text, on="_reset_buffer")

        # Transition Actions
        def _on_end_command(self) -> Generator[str, None, None]:
            """Action to execute when a command block is properly closed."""
            command_to_process = self.command_buffer.strip()
            self._reset_buffer()
            yield from self._execute_command(command_to_process)

        def _reset_buffer(self):
            """Reset the command buffer."""
            self.command_buffer = ""

        def _execute_command(self, command: str) -> Generator[str, None, None]:
            """Wrapper to call the middleware's processing method."""
            logger.info(f"ORAKLE command to process: '{command}'")
            if command:
                yield from self.middleware._process_orakle_request(
                    command,
                    self.chat_manager,
                    reasoning_level_heuristic=self.reasoning_level_heuristic,
                )

    def process_stream(
        self,
        token_stream: Generator[str, None, None],
        chat_manager=None,
        reasoning_level_heuristic: float = 0.0,
    ) -> Generator[Union[str, dict], None, None]:
        """
        Process a stream of tokens using a state machine to handle Orakle commands.

        Args:
            token_stream: Generator yielding tokens from the LLM
            chat_manager: Optional ChatManager instance to get chat history
            reasoning_level_heuristic: A reasoning level calculated by a heuristic
                                       based on the user's query.

        Yields:
            Processed tokens, including command results and guardrail messages.
        """
        parser = self._OrakleParser(self, chat_manager, reasoning_level_heuristic)
        buffer = ""

        for token in token_stream:
            if token is None:
                continue
            # # --- TOKEN DEBUG
            # logger.info(f"ORAKLE Middleware received token: {repr(token)}")

            buffer += token

            while "\n" in buffer:
                line_end_pos = buffer.find("\n")
                # Include the newline in the processed line
                line = buffer[: line_end_pos + 1]
                buffer = buffer[line_end_pos + 1:]
                yield from parser.process_line(line)

        # After the loop, process any remaining content in the buffer as a final line.
        if buffer:
            yield from parser.process_line(buffer)

        # After all processing, if the parser is still in a command state, it's unterminated.
        if parser.current_state == parser.buffering_command:
            yield parser.command_buffer
            logger.info("GUARDRAIL generated: unterminated ORAKLE command")
            yield (
                "\n\n[AINARA GUARDRAIL] Error: Stream ended with an"
                " unterminated ORAKLE command.\n\n"
            )

    def _process_orakle_request(
        self,
        query: str,
        chat_manager=None,
        reasoning_level_heuristic: float = 0.0,
    ) -> Generator[Union[str, dict], None, None]:
        """
        Process an Orakle request from the user.

        This method:
        1. Finds matching skills using the transformer matcher
        2. Uses LLM to select the best skill and extract parameters
        3. Executes the skill with the extracted parameters
        4. Interprets the results using LLM

        Args:
            query: The natural language query from the user
            chat_manager: Optional ChatManager instance to get chat history
            reasoning_level_heuristic: A reasoning level calculated by a heuristic
                                       based on the user's query.

        Yields:
            Processed results as a stream
        """
        logger.info(f"ORAKLE Processing request: {query}")

        # Pre-filter matching skills using the embeddings matcher
        matches = self.matcher.match(
            query, threshold=self.matcher_threshold, top_k=self.matcher_top_k
        )

        if not matches:
            error_msg = f"Request '{query}' didn't match any available skill."
            logger.warning(f"ORAKLE: {error_msg}")
            yield f"\nError: {error_msg}\n\n"
            return

        # Format candidate skills for the LLM
        candidate_skills_text = ""
        for i, match in enumerate(matches, 1):
            skill_id = match["skill_id"]
            score = match["score"]

            # Get full skill info including parameters
            skill_info = self._get_skill_info(skill_id)
            if not skill_info:
                logger.warning(
                    f"Could not find detailed info for skill {skill_id}"
                )
                continue

            # Format skill description with parameters
            skill_desc = (
                f"## Skill id {i}: {skill_id} (match score: {score:.2f})\n\n"
            )
            skill_desc += (
                "Description:"
                f" {skill_info.get('full_description', skill_info.get('description', 'No description'))}\n"
            )
            skill_desc += (
                # Add only the first paragraph
                f" {skill_info.get('matcher_info', '').split('\n\n')[0]}\n\n"
            )

            # Add parameters with descriptions
            skill_desc += "Parameters:\n"
            for param_name, param_info in (
                skill_info.get("run_info", {}).get("parameters", {}).items()
            ):
                param_type = param_info.get("type", "any")
                param_desc = param_info.get("description", "No description")
                param_required = (
                    "Required"
                    if param_info.get("required", False)
                    else "Optional"
                )
                param_default = param_info.get("default", "None")

                skill_desc += (
                    f"- {param_name} ({param_type}, {param_required}):"
                    f" {param_desc}"
                )
                if not param_info.get("required", False):
                    skill_desc += f" Default: {param_default}"
                skill_desc += "\n"

            skill_desc += "\n"

            # # Add parameters if available
            # if skill_info.get("parameters"):
            #     skill_desc += "Parameters:\n"
            #     for param in skill_info.get("parameters", []):
            #         param_name = param.get("name", "unknown")
            #         param_type = param.get("type", "any")
            #         param_desc = param.get("description", "No description")
            #         skill_desc += (
            #             f"- {param_name} ({param_type}): {param_desc}\n"
            #         )

            candidate_skills_text += skill_desc + "\n---\n\n"

        # Use LLM to select the best skill and extract parameters
        prompt = self.template_manager.render(
            "framework.chat_manager.orakle_select_and_params",
            {"query": query, "candidate_skills": candidate_skills_text},
        )

        logger.info(f"ORAKLE skill selection prompt: {prompt}")

        selection_response = self.llm.chat(
            chat_history=self.llm.prepare_chat(
                system_message=self.system_message, new_message=prompt
            ),
            stream=False,
        )

        logger.info(f"ORAKLE selection_response: {selection_response}")

        try:
            # Parse the LLM response to get skill_id and parameters
            selection_data = json.loads(selection_response)
            selected_skill_id = selection_data.get("skill_id")
            parameters = selection_data.get("parameters", {})
            skill_intention = selection_data.get("skill_intention", "Processing...")
            frustration_level = selection_data.get("frustration_level", 0.0)
            frustration_reason = selection_data.get("frustration_reason", "")

            # Prioritize reasoning level from Orakle, fall back to heuristic
            orakle_reasoning_level = selection_data.get("reasoning_level")
            if orakle_reasoning_level is not None:
                reasoning_level = orakle_reasoning_level
                logger.info(
                    f"ORAKLE: Reasoning level from skill selection: {reasoning_level}"
                )
            else:
                reasoning_level = reasoning_level_heuristic
                logger.info(
                    f"ORAKLE: Reasoning level from heuristic: {reasoning_level}"
                )

            # Apply the global reasoning effort limit
            final_reasoning_level = min(reasoning_level, self.reasoning_effort_limit)
            if final_reasoning_level < reasoning_level:
                logger.info(
                    f"ORAKLE: Capping reasoning level from {reasoning_level} to"
                    f" {final_reasoning_level} due to global limit."
                )

            logger.info(
                f"ORAKLE: Detected frustration level: {frustration_level:.2f}. "
                f"Reason: '{frustration_reason}'. Query: '{query}'"
            )

            if not selected_skill_id:
                if selection_data.get("error_msg"):
                    error_msg = selection_data.get("error_msg")
                else:
                    error_msg = "Failed to select a skill from candidates."
                logger.error(
                    f"ORAKLE: {error_msg} LLM response: {selection_response}"
                )
                yield f"\nError: {error_msg}\n\n"
                return

            logger.info(
                f"ORAKLE Selected skill: {selected_skill_id} with parameters:"
                f" {parameters}"
            )

            # --- Handle System Skills ---
            if selected_skill_id in self.system_skills:
                logger.info(
                    f"ORAKLE: Executing system skill: {selected_skill_id}"
                )
                yield f"\n{skill_intention}\n\n"
                yield f"\n_orakle_loading_signal_|{selected_skill_id}\n"

                skill_instance = self.system_skills[selected_skill_id]
                result = skill_instance.run(query, parameters, chat_manager)

                chat_context = self._get_chat_context(chat_manager)
                for chunk in self.stream_command_interpretation(
                    result,
                    query,
                    chat_context=chat_context,
                    reasoning_level=final_reasoning_level,
                ):
                    yield chunk
                return  # Stop processing, as we've handled this system skill

            # --- Handle Regular Skills ---
            # Yield processing message
            yield f"\n{skill_intention}\n\n"
            yield f"\n_orakle_loading_signal_|{selected_skill_id}\n"

            # Get skill info to check its type
            skill_info = self._get_skill_info(selected_skill_id)

            # Execute the selected skill with parameters
            result = self.execute_orakle_command(
                selected_skill_id, parameters, chat_manager
            )

            # If the skill is a nexus skill with a UI, yield the component data directly
            if skill_info and skill_info.get("type") == "nexus" and skill_info.get("ui"):
                component_name = skill_info.get("ui", {}).get("component")
                try:
                    result_data = json.loads(result)
                    # Yield the special dictionary for ChatManager with a flat structure
                    yield {
                        "type": "nexus_skill_result",
                        "vendor": skill_info.get("vendor"),
                        "bundle": skill_info.get("bundle"),
                        "component": component_name,
                        "query": query,
                        "data": result_data,
                    }
                except json.JSONDecodeError:
                    error_msg = f"Nexus skill '{selected_skill_id}' did not return valid JSON data."
                    logger.error(f"ORAKLE: {error_msg} Data: {result}")
                    yield f"\nError: {error_msg}\n\n"
                    return
            else:
                chat_context = self._get_chat_context(chat_manager)
                # Get interpretation as a stream for regular skills
                for interpretation_chunk in self.stream_command_interpretation(
                    [result],
                    query,
                    chat_context=chat_context,
                    reasoning_level=final_reasoning_level,
                ):
                    yield interpretation_chunk

        except json.JSONDecodeError:
            error_msg = "Failed to parse skill selection response."
            logger.error(
                f"ORAKLE: {error_msg} LLM response: {selection_response}"
            )
            yield f"\nError: {error_msg}\n\n"

    # def ndjson(event_type: str, event_name: str, content: Any = None) -> str:
    #     """Create a standardized NDJSON event string.
    #
    #     Args:
    #         event_type: Type of event (e.g. "llm_response", "loading", "interpretation")
    #         event_name: Name of event (e.g. "start", "token", "stop", "complete")
    #         content: Optional content payload
    #
    #     Returns:
    #         NDJSON formatted string with newline
    #     """
    #     event = {"event": event_name, "type": event_type}
    #     if content is not None:
    #         event["content"] = content
    #     return json.dumps(event) + "\n"

    def execute_orakle_command(
        self, skill_id: str, params: dict, chat_manager=None
    ) -> str:
        """
        Execute an Orakle command and return the result.

        Args:
            skill_id: The ID of the skill to execute
            params: Dictionary of parameters for the skill
            chat_manager: Optional ChatManager instance to get chat history

        Returns:
            Command execution result as a string
        """
        for server in self.orakle_servers:
            try:
                logger.info(
                    f"ORAKLE Executing skill '{skill_id}' with params:"
                    f" {params}"
                )

                # Check if skill requires additional data
                skill_info = self._get_skill_info(skill_id)

                if not skill_info:
                    logger.error(
                        f"Could not find skill info for {skill_id} before"
                        " execution."
                    )
                    return (
                        f"Error: Skill '{skill_id}' not found or unavailable."
                    )

                # Add chat history if the skill requires it and chat_manager is provided
                if chat_manager and any(
                    param.get("name") == "_chat_history"
                    for param in skill_info.get("parameters", [])
                ):
                    params = chat_manager.add_chat_history_to_params(
                        params, skill_info
                    )
                    logger.debug(
                        f"Added chat history to params for skill {skill_id}"
                    )

                # Make request to Orakle server
                endpoint = f"{server.rstrip('/')}/run/{skill_id}"

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
        for skill in self.capabilities:
            if skill["name"] == skill_id:
                return skill
        return {}

    def _load_system_skills(self):
        """Dynamically loads system skills from the system_skills directory."""
        skills_dir = os.path.join(os.path.dirname(__file__), "system_skills")
        if not os.path.isdir(skills_dir):
            logger.warning(f"System skills directory not found: {skills_dir}")
            return

        for filename in os.listdir(skills_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                module_name = f"ainara.framework.system_skills.{filename[:-3]}"
                try:
                    module = importlib.import_module(module_name)
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if (
                            issubclass(obj, BaseSystemSkill)
                            and obj is not BaseSystemSkill
                        ):
                            skill_instance = obj()
                            skill_definition = skill_instance.get_definition()
                            self.capabilities.append(skill_definition)
                            self.system_skills[
                                skill_instance.name
                            ] = skill_instance
                            logger.info(
                                f"Loaded system skill: {skill_instance.name}"
                            )
                except Exception as e:
                    logger.error(
                        f"Failed to load system skill from {filename}: {e}"
                    )

    def _get_chat_context(self, chat_manager) -> dict:
        """Extracts relevant context from the ChatManager."""
        chat_context = {}
        if not chat_manager:
            return chat_context

        # User profile summary
        if hasattr(chat_manager, "user_profile_summary") and getattr(
            chat_manager, "user_profile_summary"
        ):
            chat_context["user_profile_summary"] = getattr(
                chat_manager, "user_profile_summary"
            )

        # Conversation summary
        if hasattr(chat_manager, "current_summary") and getattr(
            chat_manager, "current_summary"
        ):
            chat_context["conversation_summary"] = getattr(
                chat_manager, "current_summary"
            )

        # Recent chat history (e.g., last 4 messages / 2 rounds)
        if hasattr(chat_manager, "chat_history") and getattr(
            chat_manager, "chat_history"
        ):
            history_text = ""
            # Take last 4 messages
            recent_messages = getattr(chat_manager, "chat_history")[-4:]
            for msg in recent_messages:
                # Skip system messages to avoid redundant context
                if msg.get("role") == "system":
                    continue
                role = msg.get("role", "unknown").capitalize()
                content = msg.get("content", "")
                history_text += f"{role}: {content}\n"
            if history_text:
                chat_context["recent_history"] = history_text.strip()
        return chat_context

    def _strip_think_blocks_from_stream(
        self, raw_stream: Generator[str, None, None]
    ) -> Generator[str, None, None]:
        """Strips <think>...</think> blocks from a stream of text chunks."""
        buffer = ""
        in_thinking = False
        for chunk in raw_stream:
            buffer += chunk
            while True:
                if not in_thinking:
                    start_pos = buffer.find("<think>")
                    if start_pos != -1:
                        yield buffer[:start_pos]
                        buffer = buffer[start_pos + len("<think>"):]
                        in_thinking = True
                    else:
                        yield buffer
                        buffer = ""
                        break
                if in_thinking:
                    end_pos = buffer.find("</think>")
                    if end_pos != -1:
                        buffer = buffer[end_pos + len("</think>"):]
                        in_thinking = False
                    else:
                        break  # Wait for more chunks
        if buffer:
            yield buffer

    def stream_command_interpretation(
        self,
        results: List[str],
        query: str,
        chat_context: Optional[dict] = None,
        reasoning_level: float = 0.0,
    ) -> Generator[str, None, None]:
        """
        Stream LLM interpretation of command results.

        Args:
            results: List of command result strings
            query: The natural language query that triggered the command
            chat_context: Optional dictionary with conversational context

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
                "chat_context": chat_context or {},
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
            reasoning_level=reasoning_level,
        )

        # Wrap the stream to strip out <think> blocks
        cleaned_stream = self._strip_think_blocks_from_stream(interpretation_stream)

        # Yield each chunk as it comes
        for chunk in cleaned_stream:
            if chunk:
                yield chunk

    def _process_orakle_skills(self, raw_capabilities: dict) -> List[dict]:
        """
        Process raw skill capabilities into structured format.

        Args:
            raw_capabilities: Raw capabilities dictionary from Orakle server

        Returns:
            List of processed skill dictionaries
        """
        skills = []
        for skill_name, skill_info in raw_capabilities.items():
            # logger.info(f"skill_info: {pprint.pformat(skill_info)}")
            skill_name = skill_name.strip("/")
            skill_data = {
                "name": skill_name,
                "description": (
                    skill_info.get("description", "").replace("\n", "")
                ),
                "matcher_info": (
                    skill_info.get("matcher_info", "").replace("\n", "")
                ),
                "run_info": skill_info.get("run_info", ""),
                # Attempt to get full description (e.g., from docstring)
                # Adjust the key based on actual capabilities response structure
                "full_description": (
                    skill_info.get("run", {}).get(
                        "docstring", skill_info.get("description", "")
                    )
                ),
                "embeddings_boost_factor": skill_info.get("embeddings_boost_factor", 1.0),
                "type": skill_info.get("type"),
                "ui": skill_info.get("ui"),
                "vendor": skill_info.get("vendor"),
                "bundle": skill_info.get("bundle"),
                "parameters": [],
            }

            # Process parameters
            if skill_data["run_info"].get("parameters"):
                run_info = skill_data["run_info"]
                for param_name, param_info in run_info.get(
                    "parameters", {}
                ).items():
                    param_data = {
                        "name": param_name,
                        "type": param_info.get("type", "any"),
                        "description": param_info.get("description", ""),
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
        capabilities = []

        for server in self.orakle_servers:
            try:
                response = requests.get(f"{server}/capabilities", timeout=2)
                if response.status_code == 200:
                    raw_capabilities = response.json()

                    # Process skills
                    capabilities = self._process_orakle_skills(
                        raw_capabilities
                    )

                    logger.info(
                        "Successfully loaded"
                        f" {len(capabilities)} skills from Orakle"
                        f" server: {server}"
                    )
                    return capabilities
            except requests.RequestException as e:
                logger.warning(
                    f"Failed to connect to Orakle server {server}: {str(e)}"
                )
                continue

        logger.warning(
            "No Orakle capabilities found, is the Orakle server running?"
        )
        return capabilities
