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


import json
import logging
import os
import pprint
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Generator, List, Literal, Optional, Union

from pygame import mixer

from ainara.framework.chat_memory import ChatMemory
from ainara.framework.utils import load_spacy_model
from ainara.framework.config import config
from ainara.framework.loading_animation import LoadingAnimation
from ainara.framework.orakle_middleware import OrakleMiddleware
from ainara.framework.template_manager import TemplateManager
from ainara.framework.tts.base import TTSBackend

# import pprint

# from ainara.framework.utils import format_orakle_command

logger = logging.getLogger(__name__)


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
        self.backup_file = backup_file
        self.tts = tts
        self.chat_history: List[str] = []
        self.orakle_servers = orakle_servers
        self.last_audio_file = None
        self.ndjson = ndjson
        self.new_summary = "-"

        # Load spaCy model for sentence segmentation
        self.nlp = load_spacy_model()

        # # Add a reentrant lock for thread safety
        # self.chat_lock = threading.RLock()

        # Initialize template manager
        self.template_manager = TemplateManager()

        # Initialize chat memory
        memory_enabled = config.get("memory.enabled", True)
        self.summary_enabled = config.get("summary.enabled", True)
        if memory_enabled:
            # Initialize chat memory using global config
            self.chat_memory = ChatMemory()
            logger.info("Chat memory initialized")
        else:
            self.chat_memory = None
            logger.info("Chat memory disabled")

        # Render the system message template
        current_date = datetime.now().date()
        self.system_message = self.template_manager.render(
            "framework.chat_manager.system_prompt",
            {
                "skills_description_list": (
                    ""
                ),  # Will be populated by middleware
                "current_date": current_date,
            },
        )

        # Initialize Orakle middleware
        if capabilities:
            self.capabilities = capabilities
        else:
            self.capabilities = []

        self.orakle_middleware = OrakleMiddleware(
            llm=llm,
            orakle_servers=orakle_servers,
            system_message=self.system_message,
            capabilities=capabilities,
        )

        # Get capabilities from middleware
        self.capabilities = self.orakle_middleware.capabilities

        # Update system message with skills descriptions
        skills_description_list = ""
        for skill in self.capabilities:
            skills_description_list += "\n - " + skill["description"]

        # Update system message with skills descriptions
        self.system_message = self.template_manager.render(
            "framework.chat_manager.system_prompt",
            {
                "skills_description_list": skills_description_list,
                "current_date": current_date,
            },
        )
        self.llm.add_msg(self.system_message, self.chat_history, "system")
        if self.summary_enabled:
            self.llm.add_msg(self.new_summary, self.chat_history, "system")
            # Summary generation fields
            self.trimmed_messages_buffer = []
            # Lock specifically for buffer operations
            self.buffer_lock = threading.Lock()
            self.summary_in_progress = False
            self.summary_executor = ThreadPoolExecutor(max_workers=1)
            self.current_summary = None

    def _cleanup_audio_file(self, filepath: str) -> None:
        """Delete temporary audio file after a delay to ensure it's been served"""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.debug(f"Cleaned up audio file: {filepath}")
        except Exception as e:
            logger.error(f"Error cleaning up audio file {filepath}: {e}")

    def _create_audio_stream_event(
        self,
        audio_file: str,
        text_content: str,
        duration: float,
        skill: Optional[bool] = False,
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
                        "skill": skill,
                    },
                    "audio": {
                        "url": f"/static/audio/{filename}",
                        "format": "wav",
                    },
                },
            }

    def _split_text_into_chunks(self, text: str) -> List[str]:
        """Split text into manageable chunks for better display and TTS processing.

        Splits text by line breaks first, then by sentence boundaries within each paragraph.
        """
        chunks = []

        if not text.strip():
            return chunks

        # First split by line breaks to handle lists and paragraphs
        paragraphs = text.strip().split("\n")

        for paragraph in paragraphs:
            if not paragraph.strip():
                continue

            # Then split each paragraph by sentence boundaries
            phrases = re.split(r"([.!?]\s+)", paragraph.strip())
            j = 0
            while j < len(phrases):
                if j + 1 < len(phrases):
                    phrase = phrases[j] + phrases[j + 1]
                    j += 2
                else:
                    phrase = phrases[j]
                    j += 1

                if phrase.strip():
                    chunks.append(phrase)

        return chunks

    def _extract_complete_sentences(self, text: str) -> List[str]:
        """Extract complete sentences from a text buffer.

        Returns a list of complete sentences, leaving incomplete sentences in the buffer.
        """
        if not text.strip():
            return []

        if not self.nlp:
            logger.error("spaCy model not available")
            raise RuntimeError("spacy model not available")

        # Function to check if paragraph contains special patterns that should be handled differently
        def contains_special_patterns(text):
            # Check for inline code: `code`
            if re.search(r"`([^`]+)`", text):
                return True
            # Check for code blocks: ```code```
            if re.search(r"```[^`]*```", text):
                return True
            # Check for bullet points or numbered lists
            if re.search(r"^\s*[\*\-\d]+\.?\s+", text, re.MULTILINE):
                return True
            # Check for numbered lists
            if re.search(
                r"^\s*(\d+\.\s+|\*\s+|-\s+|\+\s+).+", text, re.MULTILINE
            ):
                return True
            return False

        # Find paragraph boundaries (newlines)
        paragraph_ends = list(re.finditer(r"\n", text))

        if not paragraph_ends:
            return []

        sentences = []
        last_end = 0

        for match in paragraph_ends:
            end_pos = match.end()
            paragraph = text[last_end:end_pos].strip()
            if paragraph:
                if 0:  # contains_special_patterns(paragraph):
                    sentences.append(paragraph)
                else:
                    try:
                        # Use spaCy to split the paragraph into sentences
                        doc = self.nlp(paragraph)
                        paragraph_sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
                        sentences.extend(paragraph_sentences)
                    except Exception as e:
                        logger.error(f"spaCy sentence tokenization error: {e}")
                        logger.error(f"Error type: {type(e).__name__}")
                        logger.error(f"Error details: {str(e)}")
                        # Fallback to simple splitting
                        sentences.append(paragraph)
            last_end = end_pos

        return sentences

    def _process_streaming_sentence(
        self,
        sentence: str,
        stream_type: Optional[Literal["cli", "json"]] = None,
    ) -> Generator[str, None, None]:
        """Process and speak a single sentence for streaming output.

        Instead of collecting events, this now yields them immediately for better streaming.
        """
        if not sentence.strip():
            return

        if "_orakle_loading_signal_" in sentence:
            logger.info(f"PROCESSING: '{sentence}'")
            split_sentence = sentence.split("|")
            skill_id = split_sentence[1].strip("\n") if len(split_sentence) > 1 else "skill_id"
            yield ndjson("signal", "loading", {"state": "start", "type": "skill", "skill_id": skill_id})
            return

        try:
            audio_file, duration = self.tts.generate_audio(sentence)
            if stream_type == "json":
                event_data = self._create_audio_stream_event(
                    audio_file=audio_file,
                    text_content=sentence,
                    duration=duration,
                )
                yield ndjson("message", "stream", event_data)
            else:
                # logger.info("_process_streaming_sentence 4 '" + sentence + "'")
                char_delay = duration / len(sentence)
                if not self.tts.play_audio(audio_file):
                    raise RuntimeError("Failed to start audio playback")
                for char in sentence:
                    sys.stdout.write(char)
                    sys.stdout.flush()
                    time.sleep(char_delay)
                sys.stdout.write("\n")
                sys.stdout.flush()

                while mixer.music.get_busy():
                    time.sleep(0.001)

                # Clean up the audio file after playback
                self._cleanup_audio_file(audio_file)

        except Exception as e:
            logger.error(f"TTS error: {e}")
            print(sentence)

    def _process_regular_text(
        self, text: str, stream_type: Optional[Literal["cli", "json"]] = None
    ) -> Generator[str, None, None]:
        """Process and speak regular text content, yielding events as they're generated"""
        if not text.strip():
            return

        # Use the extracted method to split text into chunks
        chunks = self._split_text_into_chunks(text)

        for phrase in chunks:
            yield from self._process_streaming_sentence(phrase, stream_type)

    def _count_tokens_in_history(self, history=None):
        """Count tokens in the entire chat history using stored token counts when available"""
        history = history or self.chat_history
        total = 0
        role_counts = {"system": 0, "user": 0, "assistant": 0, "other": 0}

        for msg in history:
            if isinstance(msg, dict):
                role = msg["role"]
                tokens = msg["tokens"]
                total += tokens
                # Track tokens by role
                if role in role_counts:
                    role_counts[role] += tokens
                else:
                    role_counts["other"] += tokens

        # Log detailed breakdown
        logger.info(
            f"Token count breakdown - System: {role_counts['system']}, User:"
            f" {role_counts['user']}, Assistant: {role_counts['assistant']},"
            f" Other: {role_counts['other']}"
        )

        return total

    def _create_template_summary(self, messages):
        """Create a simple template-based summary as fallback"""
        user_msgs = [
            msg["content"] for msg in messages if msg.get("role") == "user"
        ]
        assistant_msgs = [
            msg["content"]
            for msg in messages
            if msg.get("role") == "assistant"
        ]

        summary = (
            f"The conversation included {len(user_msgs)} user messages and"
            f" {len(assistant_msgs)} assistant responses. "
        )

        # Add topics if we have them
        if user_msgs:
            # Extract potential topics from user messages
            topics = []
            for msg in user_msgs[
                :3
            ]:  # Use first few messages as topic indicators
                # Extract first sentence or up to 50 chars
                topic = msg.split(".")[0][:50].strip()
                if topic:
                    topics.append(topic)

            if topics:
                summary += f"Topics discussed: {'; '.join(topics)}"

        return summary

    def _generate_conversation_summary(self, messages_to_summarize):
        """Generate a summary of conversation messages using the LLM

        Args:
            messages_to_summarize: List of message dictionaries to summarize

        Returns:
            str: Generated summary text
        """
        if not messages_to_summarize:
            return ""

        # Format messages for the LLM
        formatted_messages = []
        for msg in messages_to_summarize:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            formatted_messages.append(f"{role}: {content}")

        conversation_text = "\n".join(formatted_messages)

        # Calculate maximum summary length (e.g., 5% of context window)
        context_window = self.llm.get_context_window()
        max_summary_tokens = int(context_window * 0.05)  # 5% of context window
        max_summary_chars = (
            max_summary_tokens * 4
        )  # Rough estimate: ~4 chars per token

        # Prepare template context
        template_context = {
            "conversation_text": conversation_text,
            "max_summary_tokens": max_summary_tokens,
            "max_summary_chars": max_summary_chars,
        }

        # If we already have a summary, include it to maintain continuity
        current_summary = self.chat_history[1]["content"]
        if current_summary:
            template_context["current_summary"] = current_summary
            prompt = self.template_manager.render(
                "framework.chat_manager.update_summary", template_context
            )
        else:
            prompt = self.template_manager.render(
                "framework.chat_manager.new_summary", template_context
            )

        # Use the LLM to generate a summary
        try:
            # Create a temporary chat history for this summary request
            temp_history = []
            self.llm.add_msg(
                "You are a helpful assistant that summarizes conversations.",
                temp_history,
                "system",
            )
            self.llm.add_msg(prompt, temp_history, "user")
            summary = self.llm.chat(chat_history=temp_history, stream=False)

            # Clean up the summary
            summary = summary.strip()
            if summary.startswith("Summary:"):
                summary = summary[8:].strip()
            if summary.startswith("Updated summary:"):
                summary = summary[16:].strip()

            # Apply hard cut if summary exceeds maximum length
            if len(summary) > max_summary_chars:
                logger.warning(
                    f"Summary exceeded maximum length ({len(summary)} >"
                    f" {max_summary_chars}). Truncating."
                )
                # Find the last sentence boundary before the cutoff
                cutoff_point = max_summary_chars
                last_period = summary.rfind(".", 0, cutoff_point)
                if last_period > 0:
                    summary = summary[: last_period + 1]  # Include the period
                else:
                    # If no sentence boundary found, just cut at the character limit
                    summary = summary[:cutoff_point]

            logger.info(f"Generated conversation summary: {summary[:50]}...")
            return summary
        except Exception as e:
            logger.error(f"Error generating conversation summary: {e}")
            # Fall back to template-based summary
            return self._create_template_summary(messages_to_summarize)

    def _update_summary_in_background(self):
        """Trigger background task to update the conversation summary"""
        # Check if summary is already in progress without locking the buffer
        if self.summary_in_progress:
            return

        # Check if there are messages to summarize
        with self.buffer_lock:
            if not self.trimmed_messages_buffer:
                return
            self.summary_in_progress = True
            # Get messages to summarize with minimal lock time
            messages_to_summarize = self.trimmed_messages_buffer.copy()
            self.trimmed_messages_buffer = []

        def _background_summary_task():
            try:
                # Generate the summary
                new_summary = self._generate_conversation_summary(
                    messages_to_summarize
                )
                # Safely update the new_summary with the lock
                with self.buffer_lock:
                    self.new_summary = new_summary
                    self.summary_in_progress = False
                    logger.info(
                        f"Generated new summary: {new_summary[:50]}..."
                    )

            except Exception as e:
                logger.error(f"Error in background summary task: {e}")
                with self.buffer_lock:
                    self.summary_in_progress = False
                # If there was an error, put the messages back in the buffer
                with self.buffer_lock:
                    self.trimmed_messages_buffer = (
                        messages_to_summarize + self.trimmed_messages_buffer
                    )

        # Submit the task to our executor
        self.summary_executor.submit(_background_summary_task)

    def trim_context(self, max_tokens=None):
        """
        Trim the chat history to stay within token limits while preserving context.

        Args:
            max_tokens: Maximum tokens to allow (defaults to model's context window)
        """
        if not self.chat_history:
            logger.info("No chat history to trim")
            return

        # Use model's context window if not specified
        if max_tokens is None:
            max_tokens = self.llm.get_context_window()
            logger.info(f"Using model's context window: {max_tokens} tokens")

        logger.info(
            f"Starting context trimming process. Target: {max_tokens} tokens"
        )
        logger.info(
            f"Current chat history length: {len(self.chat_history)} messages"
        )

        system_message = self.chat_history[0]
        summary_message = self.chat_history[1]
        system_tokens = system_message["tokens"] + summary_message["tokens"]
        available_tokens = max_tokens - system_tokens

        logger.info(f"System message uses {system_tokens} tokens")
        logger.info(
            f"Available tokens for conversation: {available_tokens} tokens"
        )

        current_tokens = self._count_tokens_in_history()
        logger.info(f"Current conversation uses {current_tokens} tokens")

        if current_tokens <= available_tokens:
            logger.info(
                "No trimming needed. Using"
                f" {current_tokens}/{available_tokens} tokens"
            )
            logger.info(f"chat history: {pprint.pformat(self.chat_history)}")
            return

        logger.info(f"Need to trim {current_tokens - available_tokens} tokens")

        # Get user-assistant exchanges (skip system message)
        exchanges = [
            msg
            for msg in self.chat_history
            if isinstance(msg, dict) and msg.get("role") != "system"
        ]

        logger.info(
            f"Found {len(exchanges)} messages (excluding system messages)"
        )

        # Keep most recent exchanges that fit within token limit
        kept_exchanges = []
        tokens_used = 0

        # Always keep the last exchange (most recent) regardless of token count
        # TODO Group messages by role for more flexible exchange handling
        if (
            len(exchanges) >= 2
        ):  # Assuming exchanges come in pairs (user + assistant)
            last_exchange = exchanges[
                -2:
            ]  # Last user question and assistant response

            logger.info("Keeping last exchange regardless of token count:")
            for msg in last_exchange:
                logger.info(
                    f"  - {msg.get('role', 'unknown')} message:"
                    f" {msg['tokens']} tokens"
                )
                kept_exchanges.insert(0, msg)
                tokens_used += msg["tokens"]

            exchanges = exchanges[
                :-2
            ]  # Remove the last exchange from consideration
            logger.info(f"Last exchange uses {tokens_used} tokens")
        else:
            logger.info("Not enough messages for a complete exchange")

        # Process remaining exchanges from newest to oldest
        logger.info(
            f"Processing {len(exchanges)} remaining messages from newest to"
            " oldest"
        )
        kept_count = 0
        skipped_count = 0

        for msg in reversed(exchanges):
            # Use stored token count if available, otherwise calculate
            if "tokens" in msg:
                msg_tokens = msg["tokens"]
            else:
                raise RuntimeError("Missing tokens")
            if system_tokens + tokens_used + msg_tokens <= available_tokens:
                kept_exchanges.insert(0, msg)  # Add to front to maintain order
                tokens_used += msg_tokens
                kept_count += 1
                logger.info(
                    f"Keeping {msg.get('role', 'unknown')} message:"
                    f" {msg_tokens} tokens"
                )
            else:
                # We can't fit any more messages
                skipped_count += 1
                logger.info(
                    f"Skipping {msg.get('role', 'unknown')} message:"
                    f" {msg_tokens} tokens (would exceed limit)"
                )
                # Add skipped message to the buffer for summarization
                with self.buffer_lock:
                    self.trimmed_messages_buffer.append(msg)
                break

        logger.info(
            f"Kept {kept_count} additional messages, skipped"
            f" {skipped_count} messages"
        )
        logger.info(
            f"Total tokens used so far: {tokens_used}/{available_tokens}"
        )

        # Rebuild chat history with system message and kept exchanges
        new_history = []
        new_history.append(system_message)
        new_history.append(summary_message)
        new_history.extend(kept_exchanges)
        logger.info(f"Added {len(kept_exchanges)} messages to new history")

        new_token_count = self._count_tokens_in_history(new_history)
        logger.info(
            f"Trimmed context from {current_tokens} to"
            f" {new_token_count} tokens"
            f" ({current_tokens - new_token_count} tokens removed)"
        )
        logger.info(f"New history has {len(new_history)} messages")

        logger.info(f"new_history: {pprint.pformat(new_history)}")

        self.chat_history = new_history

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

        # Check if spaCy model is available
        if not self.nlp:
            raise RuntimeError("spacy model not available")

        # Start loading animation for CLI mode or send start event for JSON mode
        loading = None
        if stream == "cli":
            loading = LoadingAnimation("")
            loading.start()
        elif stream == "json":
            yield ndjson("signal", "loading", {"state": "start"})

        processed_answer = ""
        try:
            if self.chat_memory:
                self.chat_memory.add_entry(question, {"role": "user"})

            # Check if the last message is from a user, and if so, log a warning
            if (
                self.chat_history
                and isinstance(self.chat_history[-1], dict)
                and self.chat_history[-1].get("role") == "user"
            ):
                logger.warning(
                    "Adding a user message when the last message was also from"
                    " a user"
                )

            self.llm.add_msg(question, self.chat_history, "user")
            # Atomically check and apply any new summary
            if self.summary_enabled:
                with self.buffer_lock:  # Use the existing lock for consistency
                    if self.new_summary:
                        new_summary_copy = self.new_summary
                        self.new_summary = (  # Clear it while holding the lock
                            "-"
                        )
                        logger.info("Retrieved new summary for application")

            # Token counting can happen outside the lock
            if "new_summary_copy" in locals():
                new_summary_tokens = self.llm._get_token_count(
                    new_summary_copy, "system"
                )
                self.chat_history[1]["content"] = new_summary_copy
                self.chat_history[1]["tokens"] = new_summary_tokens
                logger.info(f"Applied new summary: {new_summary_copy[:50]}...")
            self.trim_context()
            llm_response_stream = self.llm.chat(
                chat_history=self.chat_history, stream=True
            )

            processed_answer = ""
            text_buffer = ""

            # Process the stream through the Orakle middleware
            # This now handles command execution and interpretation internally
            for chunk in self.orakle_middleware.process_stream(
                llm_response_stream, self
            ):
                if not chunk:
                    continue

                processed_answer += chunk
                text_buffer += chunk

                # Process complete sentences for immediate TTS
                if self.tts:
                    sentences = self._extract_complete_sentences(text_buffer)
                    # if len(sentences) > 0:
                    #     logger.info(" --- SENTENCES --- ")
                    #     logger.info(pprint.pformat(sentences))
                    if stream == "cli":
                        loading.stop()
                    elif stream == "json":
                        yield ndjson("signal", "loading", {"state": "stop"})
                    for sentence in sentences:
                        if stream == "json":
                            yield from self._process_streaming_sentence(
                                sentence, stream
                            )
                        else:
                            # For CLI mode, just process without collecting events
                            for _ in self._process_streaming_sentence(
                                sentence, stream
                            ):
                                pass

                    # Keep any incomplete sentence in the buffer
                    if sentences:
                        last_sentence = sentences[-1]
                        last_pos = text_buffer.rfind(last_sentence) + len(
                            last_sentence
                        )
                        text_buffer = text_buffer[last_pos:].strip()
                elif stream == "cli":
                    # For CLI without TTS, print directly
                    print(chunk, end="", flush=True)

            # Process any remaining text in the buffer
            if text_buffer and self.tts:
                if stream == "json":
                    yield from self._process_regular_text(text_buffer, stream)
                else:
                    # For CLI mode, just process without collecting events
                    for _ in self._process_regular_text(text_buffer, stream):
                        pass

        except Exception as e:
            if loading:
                loading.stop()
            logger.error(f"Error during LLM response: {e}")
            if stream == "json":
                logger.error("Sending error yield signal")
                yield ndjson("signal", "error", {"message": str(e)})
            processed_answer = (  # Set a default error message
                f"Error: {str(e)}"
            )

        finally:
            # Always add the processed answer to chat history, even if it's empty or an error
            if processed_answer:
                # Add the processed answer to chat history
                self.llm.add_msg(
                    processed_answer, self.chat_history, "assistant"
                )

                # Log assistant response to chat memory
                if self.chat_memory:
                    self.chat_memory.add_entry(
                        processed_answer, {"role": "assistant"}
                    )
            else:
                # If there's no processed answer, add a placeholder
                logger.warning("No answer from the LLM, adding placeholder")
                self.llm.add_msg(
                    "No response generated", self.chat_history, "assistant"
                )
                if self.chat_memory:
                    self.chat_memory.add_entry(
                        "No response generated", {"role": "assistant"}
                    )

            # Stop loading animation
            if stream == "cli":
                loading.stop()
            elif stream == "json":
                yield ndjson("signal", "loading", {"state": "stop"})
                yield ndjson("signal", "completed", None)

            # Trigger background summary generation
            if self.summary_enabled:
                self._update_summary_in_background()

            # For non-streaming mode, return the processed answer
            if not stream:
                return processed_answer

    def add_chat_history_to_params(
        self, params: dict, skill_info: dict
    ) -> dict:
        """Add chat history to parameters if the skill requires it"""
        # Check if skill requires chat history
        if any(
            param.get("name") == "_chat_history"
            for param in skill_info.get("parameters", [])
        ):
            params["_chat_history"] = self.prepare_chat_history_for_skill()
        return params

    def prepare_chat_history_for_skill(self) -> list:
        """Prepare chat history in a format suitable for skills"""
        # If we have chat memory, use recent entries from it
        if self.chat_memory:
            recent_entries = self.chat_memory.get_recent_entries(
                20
            )  # Get more entries from memory
            formatted_history = []

            for entry in recent_entries:
                role = entry["metadata"].get("role")
                if role in ["user", "assistant"]:
                    formatted_history.append(
                        {"role": role, "content": entry["content"]}
                    )

            return formatted_history

        # Otherwise, fall back to the existing implementation
        formatted_history = []
        for msg in self.chat_history:
            # Only include user and assistant messages, skip system messages
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                if msg["role"] in ["user", "assistant"]:
                    formatted_history.append(
                        {"role": msg["role"], "content": msg["content"]}
                    )
        return formatted_history
