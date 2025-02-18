# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez http://www.khromalabs.org

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
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime
from typing import Any, Generator, List, Literal, Optional, Tuple, Union

import requests
from pygame import mixer

from ainara.framework.loading_animation import LoadingAnimation
from ainara.framework.matcher.orakle_matcher_transformers import \
    OrakleMatcherTransformers
from ainara.framework.tts.base import TTSBackend
from ainara.framework.utils import format_orakle_command

logger = logging.getLogger(__name__)

SYSTEM_MESSAGE = f"""
 I'm Ainara, an AI assistant that combines built-in knowledge with real-time
 capabilities through the ORAKLE("<request>") command.

 I use my built-in knowledge for:
 - Theoretical concepts
 - Historical facts
 - Definitions
 - General knowledge
 - Scientific principles
 - Explanations
 - Common knowledge

 I MUST use ORAKLE("<request>") for ANY:
 - Current data or information
 - Real-time tasks
 - Calculations
 - External services
 - Market prices
 - Weather information
 - News
 - Data retrieval
 - Task execution
 - Real world physical actions
 - Local system clipboard access
 - Explicit request of an ORAKLE command

 Examples:
 "What is quantum physics?" → I use my knowledge to explain
 "What's Bitcoin's price?" → ORAKLE("get current Bitcoin price")
 "Explain gravity" → I use my knowledge to explain
 "Calculate 15% tip" → ORAKLE("calculate 15 percent tip")
 "Define photosynthesis" → I use my knowledge to explain
 "What's the weather?" → ORAKLE("get current weather")

 I never guess or assume current information - if it's real-time or requires
 external data, I MUST use ORAKLE. If I use a ORAKLE command I NEVER provide
 any further explanation about it, I just use the ORAKLE command directly. I
 never request more than one ORAKLE command in the same answer, I just user an
 ORAKLE commmand once per answer. I don't do any comments towards the ORAKLE
 server, I don't thank receiving the results by the ORAKLE server, my comments
 are only towards the final user. If I receive the feedback that I don't have
 the capability of executing an ORAKLE command, I don't do any further comment
 about it.

 Today is: {datetime.now().strftime('%Y-%m-%d')}
"""


def ndjson(event_type: str, event_name: str, content: Any = None) -> str:
    """Create a standardized NDJSON event string.

    Args:
        event_type: Type of event (e.g. "llm_response", "loading", "interpretation")
        event_name: Name of event (e.g. "start", "token", "stop", "complete")
        content: Optional content payload

    Returns:
        NDJSON formatted string with newline
    """
    event = {"event": event_name, "type": event_type}
    if content is not None:
        event["content"] = content
    return json.dumps(event) + "\n"


class ChatManager:
    """Manages chat interactions, command processing, and TTS functionality"""

    def __init__(
        self,
        llm,
        orakle_servers: List[str],
        flask_app=None,
        backup_file: Optional[str] = None,
        tts: Optional[TTSBackend] = None,
        capabilities: Optional[dict] = None,
    ):
        self.app = flask_app
        self.llm = llm
        self.system_message = SYSTEM_MESSAGE
        self.backup_file = backup_file
        self.tts = tts
        self.chat_history: List[str] = []
        self.orakle_servers = orakle_servers
        self.matcher = OrakleMatcherTransformers()
        self.last_audio_file = None
        if capabilities:
            self.capabilities = capabilities
        else:
            self.capabilities = {"recipes": [], "skills": []}
            self.capabilities = self.get_orakle_capabilities()
        for skill in self.capabilities["skills"]:
            self.matcher.register_skill(skill["name"], skill["description"])

    def backup(self, content: str) -> None:
        """Backup chat content to file if backup is enabled"""
        if self.backup_file:
            with open(self.backup_file, "a") as f:
                f.write(content + "\n")

    def format_chat_messages(self, new_message: str) -> List[dict]:
        """Format chat history and new message for LLM processing"""
        messages = [{"role": "system", "content": self.system_message}]

        for i in range(0, len(self.chat_history), 2):
            messages.append({"role": "user", "content": self.chat_history[i]})
            if i + 1 < len(self.chat_history):
                messages.append(
                    {"role": "assistant", "content": self.chat_history[i + 1]}
                )

        messages.append({"role": "user", "content": new_message})
        return messages

    def get_llm_response(
        self, question: str, stream: bool = True, suppress_output: bool = False
    ) -> str:
        """Get initial LLM response"""
        answer = ""
        response = self.llm.process_text(
            text=question,
            system_message=self.system_message,
            chat_history=self.chat_history,
            stream=stream,
        )

        try:
            for chunk in response:
                if chunk:
                    if not suppress_output:
                        print(chunk, end="", flush=True)
                    answer += chunk
        except Exception as e:
            logger.error(f"Error during streaming: {e}")
        return answer

    def process_orakle_commands(
        self, text: str
    ) -> Tuple[str, List[str], List[str]]:
        """Process Orakle commands in text"""
        if hasattr(text, "__iter__") and not isinstance(text, (str, bytes)):
            text = "".join(list(text))

        results = []
        command_types = []

        def replace_command(match):
            query = match.group(1).strip()
            # Find matching skills using the matcher
            matches = self.matcher.match(query)

            if not matches:
                result = (
                    "I apologize, but I don't have the capability to"
                    f" '{query}'. This action is not available among my"
                    " current skills."
                )
                results.append(result)
                # Return just the error message without command formatting
                return f"\n{result}\n"

            # Use the best matching skill
            best_match = matches[0]
            skill_id = best_match["skill_id"]
            skill_description = best_match["description"]

            # Use LLM to convert natural language to structured parameters
            prompt = f"""Based on this skill description: "{skill_description}"
            Convert this natural language query: "{query}"
            into a JSON parameters object following the skill's requirements.
            Pay special attention to the args (arguments) description, which
            you must interprete according to this schema:
            Args:
                <param_arg_name_1>: <param_arg_description_1>
                <param_arg_name_2>: <param_arg_description_2>
                etc
            Return ONLY the JSON object, no backticks, nothing else."""

            json_params = self.llm.process_text(
                text=prompt,
                stream=False,
            )

            try:
                # Validate it's proper JSON
                params_dict = json.loads(json_params)
                # Determine if it's a SKILL or RECIPE from the ID
                cmd_type = (
                    "SKILL" if not skill_id.startswith("recipe/") else "RECIPE"
                )
                command_types.append(cmd_type)

                # Format the command with the matched skill and LLM params
                command = (
                    f'{cmd_type}("{skill_id}", {json.dumps(params_dict)})'
                )
                # print(f"Cmd: {command}")
            except json.JSONDecodeError:
                logger.error(f"LLM generated invalid JSON: {json_params}")
                # Fallback to simple query parameter
                command = f'{cmd_type}("{skill_id}", {{"query": "{query}"}})'

            result = self.execute_orakle_command(command)
            results.append(result)

            return f"__COMMAND_START__{skill_id}__COMMAND_DISPLAY__{command}\n\nResult:\n```json\n{result}\n```__COMMAND_END__"

        # Look for ORAKLE commands
        pattern = r'ORAKLE\("([^"]+)"\)'
        processed_text = re.sub(
            pattern, replace_command, text, flags=re.DOTALL
        )
        return processed_text, results, command_types

    def execute_orakle_command(self, command_block: str) -> str:
        """Execute an Orakle command and return the result"""
        for server in self.orakle_servers:
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
                cmd_name = cmd_name.strip("/")
                endpoint_type = f"{cmd_type.lower()}s"
                endpoint = f"{server.rstrip('/')}/{endpoint_type}/{cmd_name}"

                response = requests.post(endpoint, json=params, timeout=30)

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

    def _cleanup_audio_file(self, filepath: str) -> None:
        """Delete temporary audio file after a delay to ensure it's been served"""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.debug(f"Cleaned up audio file: {filepath}")
        except Exception as e:
            logger.error(f"Error cleaning up audio file {filepath}: {e}")

    def _create_audio_stream_event(
        self, audio_file: str, text_content: str, duration: float,
        skill: Optional[bool] = False
    ) -> dict:
        """Create a standardized audio stream event with audio URL."""
        filename = os.path.basename(audio_file)

        with self.app.app_context():
            static_audio_dir = os.path.join(self.app.static_folder, "audio")
            target_path = os.path.join(static_audio_dir, filename)

            os.makedirs(static_audio_dir, exist_ok=True)

            # Copy the new audio file
            shutil.copy2(audio_file, target_path)

            # Clean up original file
            try:
                os.remove(audio_file)
            except Exception as e:
                logger.error(f"Error cleaning up original audio file: {e}")

            return {
                "message": "stream",
                "content": {
                    "content": text_content + "\n",
                    "flags": {
                        "command": False,
                        "audio": True,
                        "duration": duration,
                        "skill": skill
                    },
                    "audio": {
                        "url": f"/static/audio/{filename}",
                        "format": "wav",
                    },
                },
            }

    def _process_regular_text(
        self, text: str, stream_type: Optional[Literal["cli", "json"]] = None
    ) -> List[str]:
        """Process and speak regular text content"""
        logger.info("_process_regular_text 1")
        logger.info(text)
        events = []

        if not text.strip():
            return events

        logger.info("_process_regular_text 2")

        logger.info(text)
        phrases = re.split(r"([.!?]\s+)", text.strip())
        j = 0
        while j < len(phrases):
            if j + 1 < len(phrases):
                phrase = phrases[j] + phrases[j + 1]
                j += 2
            else:
                phrase = phrases[j]
                j += 1

            logger.info("_process_regular_text 3")

            if not phrase.strip():
                continue

            logger.info("_process_regular_text 4")

            try:
                logger.info("_process_regular_text 5")
                audio_file, duration = self.tts.generate_audio(phrase)
                if stream_type == "json":
                    logger.info("_process_regular_text 6")
                    event_data = self._create_audio_stream_event(
                        audio_file=audio_file,
                        text_content=phrase,
                        duration=duration,
                    )
                    events.append(ndjson("message", "stream", event_data))
                else:
                    char_delay = duration / len(phrase)
                    if not self.tts.play_audio(audio_file):
                        raise RuntimeError("Failed to start audio playback")
                    for char in phrase:
                        sys.stdout.write(char)
                        sys.stdout.flush()
                        time.sleep(char_delay)
                    sys.stdout.write("\n")
                    sys.stdout.flush()

                    while mixer.music.get_busy():
                        time.sleep(0.001)

                    # Clean up the audio file after playback
                    self._cleanup_audio_file(audio_file)

                logger.info("_process_regular_text 6")

            except Exception as e:
                logger.error(f"TTS error: {e}")
                print(phrase)

            logger.info("_process_regular_text 7")


        logger.info("_process_regular_text 8")
        return events

    def _process_command(
        self,
        cmd_name: str,
        cmd_type: str,
        cmd: Optional[str],
        next_part: str,
        stream_type: Optional[Literal["cli", "json"]] = None,
    ) -> List[str]:
        """Process and speak command-related content"""
        events = []
        try:
            phrase = f"Requesting {cmd_type} {cmd_name}"
            if stream_type == "json":
                events.append(ndjson("signal", "command", {"name": cmd_name}))
                audio_file, duration = self.tts.generate_audio(phrase)
                event_data = self._create_audio_stream_event(
                    audio_file=audio_file,
                    text_content=phrase,
                    duration=duration,
                    skill=True
                )
                events.append(ndjson("message", "stream", event_data))
            else:
                self.tts.speak(phrase)

            if cmd and not stream_type == "cli":
                # Pretty printed command name / parameters
                # if stream_type == "json":
                #     events.append(
                #         ndjson(
                #             "signal",
                #             "command",
                #             {"name": f"{format_orakle_command(cmd)}"},
                #         )
                #     )
                # else:
                print(f"Executing:\n{format_orakle_command(cmd)}")

            # Extract and print result
            result_match = re.search(
                r"Result:\n```json\n(.*?)\n```", next_part, re.DOTALL
            )
            if result_match:
                logger.info("HAVE MATCH IN RESULT")
                result = "Here's the result: " + result_match.group(1)
                if stream_type == "json":
                    audio_file, duration = self.tts.generate_audio(result)
                    event_data = self._create_audio_stream_event(
                        audio_file=audio_file,
                        text_content=result,
                        duration=duration,
                    )
                    events.append(ndjson("message", "stream", event_data))
                else:
                    print(result)
                    self.tts.speak(result)
            else:
                logger.info("NO MATCH IN RESULT")

        except Exception as e:
            logger.error(f"TTS error during command processing: {e}")

        return events

    def tts_response_output(
        self,
        processed_answer: str,
        stream_type: Optional[Literal["cli", "json"]] = None,
    ) -> List[str]:
        """Process structured response with text-to-speech and streaming output"""
        logger.info("Starting tts_response_output")
        events = []

        if not self.tts:
            return events

        # Split the text by command markers
        parts = re.split(
            r"__COMMAND_START__(.+?)__COMMAND_DISPLAY__.*?__COMMAND_END__",
            processed_answer,
            flags=re.DOTALL,
        )

        cmda = re.split(
            r"__COMMAND_START__.+?__COMMAND_DISPLAY__(.*?)__COMMAND_END__",
            processed_answer,
            flags=re.DOTALL,
        )

        try:
            cmd = cmda[1].split("\n")[0]
            cmd_type = re.search(r"\b\w+\b", cmda[1]).group(0)
            if cmd == "none":
                return events
        except (IndexError, AttributeError):
            cmd = None

        for i, part in enumerate(parts):
            if i % 2 == 0:  # Regular text
                events.extend(self._process_regular_text(part, stream_type))
                logger.info("tts_response_output 1")
            else:  # Command name and result
                cmd_name = part
                next_part = parts[i + 1] if i + 1 < len(parts) else ""
                events.extend(
                    self._process_command(
                        cmd_name, cmd_type, cmd, next_part, stream_type
                    )
                )

        logger.info("tts_response_output 2")
        return events

    def get_command_interpretation(
        self,
        results: List[str],
        command_types: List[str],
        stream: Optional[Literal["cli", "json"]] = "cli",
    ) -> Generator[str, None, None]:
        """Get LLM interpretation of command results"""
        formatted_results = []
        for r in results:
            try:
                json.loads(r)
                formatted_results.append(f"```json\n{r}\n```")
            except json.JSONDecodeError:
                formatted_results.append(f"```text\n{r}\n```")

        instruction = (
            "This was a RECIPE command. Please reproduce the command result"
            " verbatim in your response, maintaining all formatting and"
            " structure. Add a brief introduction explaining what the recipe"
            " did:"
            if command_types and command_types[0] == "RECIPE"
            else (
                "This was a SKILL command. Don't reproduce the command result"
                " verbatim in your next answer, instead write your"
                " interpretation about the result in the context of the"
                " conversation. Only reproduce the command result verbatim if"
                " the user explicitly asks for that:"
            )
        )

        interpretation_prompt = (
            "Based on the Orakle command results:\n"
            + "\n".join(formatted_results)
            + "\n\n"
            + instruction
            + "\n"
        )
        return self.llm.process_text(
            text=interpretation_prompt,
            system_message=self.system_message,
            chat_history=self.chat_history,
            stream=stream if isinstance(stream, bool) else (stream == "cli"),
        )

    def chat_completion(
        self, question: str, stream: Optional[Literal["cli", "json"]] = "cli"
    ) -> Union[str, Generator[str, None, None], dict]:
        """Main chat completion function

        Args:
            question: User's input question
            stream: Stream mode:
                - None: No streaming, returns complete response
                - "cli": CLI streaming with prints and loading animation
                - "json": Streams JSON events in NDJSON format
        """
        # Handle legacy bool value for backward compatibility
        if isinstance(stream, bool):
            stream = "cli" if stream else None

        # Start loading animation for CLI mode or send start event for JSON mode
        loading = None
        if stream == "cli":
            loading = LoadingAnimation("")
            loading.start()
        elif stream == "json":
            yield ndjson("signal", "loading", {"state": "start"})

        try:
            # Get initial response
            answer = ""
            response = self.llm.process_text(
                text=question,
                system_message=self.system_message,
                chat_history=self.chat_history,
                stream=True,
            )

            for chunk in response:
                if chunk:
                    answer += chunk
                    if stream == "cli" and not self.tts:
                        print(chunk, end="", flush=True)

            if stream == "cli":
                loading.stop()
            elif stream == "json":
                yield ndjson("signal", "loading", {"state": "stop"})

            if not answer:
                logger.info("NO ANSWER")
                return {} if stream == "json" else ""

        except Exception as e:
            if loading:
                loading.stop()
            logger.error(f"Error during LLM response: {e}")
            if stream == "json":
                yield ndjson("signal", "error", {"message": str(e)})
            return "" if stream != "json" else {}

        # Process any Orakle commands
        processed_answer, results, command_types = (
            self.process_orakle_commands(answer)
        )

        logger.info("processed_answer: " + processed_answer)

        # Process initial response with TTS and streaming
        logger.info("PRE tts_response_output")
        events = self.tts_response_output(processed_answer, stream)
        logger.info("POST tts_response_output")
        for event in events:
            if stream == "json":
                logger.info("YIELD EVENT")
                yield event
        logger.info("POST tts_response_output")

        if results:
            final_answer = ""
            for chunk in self.get_command_interpretation(
                results, command_types, stream
            ):
                if chunk:
                    if self.tts:
                        final_answer += chunk
                    else:
                        print(chunk, end="", flush=True)
                        final_answer += chunk

            if final_answer:
                separator = "\n\nResult:\n"
                processed_answer += f"{separator}{final_answer}\n"
                # Process command interpretation with TTS and streaming
                if self.tts:
                    events = self.tts_response_output(final_answer, stream)
                    if stream == "json":
                        logger.info(f"Yielding {len(list(events))} final TTS events")
                        for event in events:
                            logger.info(f"Yielding event: {event[:100]}...")
                            yield event


        if stream == "json":
            yield ndjson("signal", "completed", None)

        return processed_answer

    def get_orakle_capabilities(self):
        """Query Orakle servers for capabilities and store them in structured format"""
        print("Retrieving Orakle server capabilities...")
        self.capabilities = {"recipes": [], "skills": []}

        for server in self.orakle_servers:
            try:
                response = requests.get(f"{server}/capabilities", timeout=2)
                if response.status_code == 200:
                    raw_capabilities = response.json()

                    # Process recipes
                    if "recipes" in raw_capabilities:
                        for endpoint, recipe in raw_capabilities[
                            "recipes"
                        ].items():
                            recipe_data = {
                                "name": endpoint,
                                "description": recipe.get("description", ""),
                                "parameters": recipe.get("parameters", []),
                                "return_type": "",
                            }

                            # Extract return type from flow if available
                            if "flow" in recipe and recipe["flow"]:
                                last_step = recipe["flow"][-1]
                                recipe_data["return_type"] = last_step.get(
                                    "output_type", ""
                                )

                            self.capabilities["recipes"].append(recipe_data)

                    # Process skills
                    if "skills" in raw_capabilities:
                        for skill_name, skill_info in raw_capabilities[
                            "skills"
                        ].items():
                            if "run" in skill_info:
                                run_info = skill_info["run"]
                                skill_data = {
                                    "name": skill_name,
                                    "description": run_info.get(
                                        "description", ""
                                    ),
                                    "return_type": run_info.get(
                                        "return_type", ""
                                    ),
                                    "parameters": [],
                                }

                                # Process parameters
                                if run_info.get("parameters"):
                                    for param_name, param_info in run_info[
                                        "parameters"
                                    ].items():
                                        param_data = {
                                            "name": param_name,
                                            "type": param_info.get(
                                                "type", "any"
                                            ),
                                            "description": param_info.get(
                                                "description", ""
                                            ),
                                        }
                                        skill_data["parameters"].append(
                                            param_data
                                        )

                                self.capabilities["skills"].append(skill_data)

                        logger.info("...capabilities loaded successfully:")
                        return self.capabilities
            except requests.RequestException:
                continue

        logger.warning(
            "No Orakle capabilities found, is the Orakle server running?"
        )
        return self.capabilities
