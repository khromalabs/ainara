import json
import re
import sys
import time
# from datetime import datetime
from typing import Generator, List, Optional, Tuple

import requests
from pygame import mixer

from ainara.framework.loading_animation import LoadingAnimation
from ainara.framework.logging_setup import logging_manager
from ainara.framework.tts.base import TTSBackend

logger = logging_manager.logger


class ChatManager:
    """Manages chat interactions, command processing, and TTS functionality"""

    def __init__(
        self,
        llm,
        system_message: str,
        orakle_servers: List[str],
        backup_file: Optional[str] = None,
        tts: Optional[TTSBackend] = None,
    ):
        self.llm = llm
        self.system_message = system_message
        self.backup_file = backup_file
        self.tts = tts
        self.chat_history: List[str] = []
        self.orakle_servers = orakle_servers

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
        """Process Orakle command blocks in text"""
        if hasattr(text, "__iter__") and not isinstance(text, (str, bytes)):
            text = "".join(list(text))

        results = []
        command_types = []

        def replace_command(match):
            command = match.group(1).strip()
            cmd_type_match = re.match(r"(SKILL|RECIPE)", command)
            if cmd_type_match:
                command_types.append(cmd_type_match.group(1))

            result = self.execute_orakle_command(command)
            results.append(result)
            return f"{command}\n\nResult:\n```json\n{result}\n```"

        pattern = r"```oraklecmd\n(.*?)\n```"
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

    def handle_tts(self, processed_answer: str) -> None:
        """Handle text-to-speech output with synchronized text display"""
        if not self.tts:
            return

        sections = re.split(r"(```.*?```)", processed_answer, flags=re.DOTALL)
        for section in sections:
            if not section.startswith("```"):
                phrases = re.split(r"([.!?]\s+)", section.strip())

                i = 0
                while i < len(phrases):
                    if i + 1 < len(phrases):
                        phrase = phrases[i] + phrases[i + 1]
                        i += 2
                    else:
                        phrase = phrases[i]
                        i += 1

                    if not phrase.strip():
                        continue

                    try:
                        audio_file, duration = self.tts.generate_audio(phrase)
                        char_delay = duration / len(phrase)

                        if not self.tts.play_audio(audio_file):
                            raise RuntimeError(
                                "Failed to start audio playback"
                            )

                        for char in phrase:
                            sys.stdout.write(char)
                            sys.stdout.flush()
                            time.sleep(char_delay)
                        sys.stdout.write("\n")
                        sys.stdout.flush()

                        while mixer.music.get_busy():
                            time.sleep(0.001)

                    except Exception as e:
                        logger.error(f"TTS error: {e}")
                        print(phrase)

    def get_command_interpretation(
        self, results: List[str], command_types: List[str], stream: bool = True
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
            " did."
            if command_types and command_types[0] == "RECIPE"
            else (
                "This was a SKILL command. Don't reproduce the command result"
                " verbatim in your next answer, instead write your"
                " interpretation about the result in the context of the"
                " conversation. Only reproduce the command result verbatim if"
                " the user explicitly asks that"
            )
        )

        interpretation_prompt = (
            "Based on the Orakle command results:\n"
            + "\n".join(formatted_results)
            + "\n\n"
            + instruction
        )
        print()
        return self.llm.process_text(
            text=interpretation_prompt,
            system_message=self.system_message,
            chat_history=self.chat_history,
            stream=stream,
        )

    def chat_completion(self, question: str, stream: bool = True) -> str:
        """Main chat completion function"""
        # Start loading animation
        loading = LoadingAnimation("")
        loading.start()

        try:
            # Get initial response
            answer = self.get_llm_response(
                question, stream=True, suppress_output=bool(self.tts)
            )
            loading.stop()

            if not answer:
                return ""
        except Exception as e:
            loading.stop()
            logger.error(f"Error during LLM response: {e}")
            return ""

        # Process any Orakle commands
        processed_answer, results, command_types = (
            self.process_orakle_commands(answer)
        )

        # Handle TTS for initial response
        self.handle_tts(processed_answer)

        # Handle command interpretation if there were results
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
                separator = "\n\nResult:\n" + "=" * 40 + "\n"
                processed_answer += f"{separator}{final_answer}\n" + "=" * 40
                # Handle TTS for command interpretation
                if self.tts:
                    self.handle_tts(final_answer)

        self.backup(processed_answer)
        self.chat_history.extend([question.strip(), processed_answer.strip()])

        return processed_answer
