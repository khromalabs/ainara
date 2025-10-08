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
from typing import Any, Generator, List, Literal, Optional, Union

from pygame import mixer

from ainara.framework.chat_memory import ChatMemory
from ainara.framework.config import config
from ainara.framework.green_memories import GREENMemories
from ainara.framework.loading_animation import LoadingAnimation
from ainara.framework.orakle_middleware import OrakleMiddleware
from ainara.framework.template_manager import TemplateManager
from ainara.framework.tts.base import TTSBackend
from ainara.framework.utils import load_spacy_model

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
        green_memories: GREENMemories,
        flask_app=None,
        backup_file: Optional[str] = None,
        tts: Optional[TTSBackend] = None,
        chat_memory: Optional[ChatMemory] = None,
        user_profile_summary: Optional[str] = None,
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
        self.nexus_test = 0

        # Load spaCy model for sentence segmentation
        self.nlp = load_spacy_model()

        # Initialize template manager
        self.template_manager = TemplateManager()

        # Initialize chat memory
        self.chat_memory = chat_memory
        self.green_memories = green_memories
        self.user_profile_summary = user_profile_summary
        self.memory_enabled = config.get("memory.enabled", False)
        self.summary_enabled = config.get("memory.summary_enabled", True)

        self.max_guardrail_retries = config.get("guardrails.max_retries", 2)
        # --- Memory Decay Tracking (persisted between sessions) ---
        self.memory_decay_interval = config.get(
            "memories.decay_interval_turns", 5
        )
        self.turn_counter = 0
        self.decay_in_progress = False
        self.decay_lock = threading.Lock()
        if (
            self.memory_enabled
            and self.green_memories
            and self.memory_decay_interval > 0
        ):
            self.turn_counter = self.green_memories.get_turn_counter()

        # Render the system message template
        self.system_message = self.template_manager.render(
            "framework.chat_manager.system_prompt",
            {
                "skills_description_list": (
                    ""
                ),  # Will be populated by middleware
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

        # --- Reasoning Level Heuristic ---
        self.reasoning_heuristic_enabled = config.get(
            "reasoning_heuristic.enabled", True
        )
        # TODO Add this parameter to wizard configuration
        if self.reasoning_heuristic_enabled:
            self.reasoning_max_level = config.get(
                "reasoning_heuristic.max_level", 0.6
            )
            logger.info("Reasoning level heuristic enabled.")

        # Get capabilities from middleware
        self.capabilities = self.orakle_middleware.capabilities

        # Update system message with skills descriptions
        skills_description_list = ""
        for skill in self.capabilities:
            skills_description_list += "\n - " + skill["description"]

        # Check if the user profile is new to show an onboarding message
        user_memories_empty = (
            self.green_memories and self.green_memories.is_empty()
        )
        has_prior_user_messages = any(
            msg.get("role") == "user" for msg in self.chat_history[:-1]
        )  # Check all but the current one
        if not has_prior_user_messages and user_memories_empty:
            is_new_profile = True
            logger.info(
                "User profile is empty. Will display onboarding message."
            )
        else:
            is_new_profile = False

        # Update system message with skills descriptions
        self.system_message = self.template_manager.render(
            "framework.chat_manager.system_prompt",
            {
                "skills_description_list": skills_description_list,
                "is_new_profile": is_new_profile,
            },
        )
        self.llm.add_msg(self.system_message, self.chat_history, "system")

        # Initialize executor if either summary or decay is enabled
        self.summary_executor = None
        if self.summary_enabled:
            self.summary_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="SummaryThread"
            )

        self.decay_executor = None
        if (
            self.memory_enabled
            and self.green_memories
            and self.memory_decay_interval > 0
        ):
            self.decay_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="DecayThread"
            )

        if self.summary_enabled:
            # Summary generation fields
            self.trimmed_messages_buffer = []
            # Lock specifically for buffer operations
            self.buffer_lock = threading.Lock()
            self.summary_in_progress = False
            self.current_summary = "-"

    def update_llm(self, llm):
        self.llm = llm
        self.orakle_middleware.update_llm(llm)
        if self.green_memories:
            self.green_memories.update_llm(llm)

    def _initialize_memory_if_needed(self):
        """Initializes memory components if they haven't been already."""
        if self.chat_memory is None:
            logger.info("Initializing ChatMemory on-demand...")
            self.chat_memory = ChatMemory()
            logger.info("Chat memory initialized.")

        if self.green_memories is None:
            logger.info("Initializing GREENMemories on-demand...")
            self.green_memories = GREENMemories(
                llm=self.llm,
                chat_memory=self.chat_memory,
            )
            logger.info("User Memories Manager initialized.")
            # Perform initial consolidation
            logger.info("Processing existing messages for user profile...")
            self.green_memories.process_new_messages_for_update()
            logger.info("Message processing complete.")

        # Always regenerate summary when enabling memory
        if self.green_memories:
            self.user_profile_summary = (
                self.green_memories.generate_user_profile_summary()
            )
            if self.user_profile_summary:
                logger.info("User profile summary generated/updated.")

        # Initialize decay components if needed
        if self.memory_decay_interval > 0 and self.decay_executor is None:
            logger.info("Initializing Memory Decay executor on-demand...")
            self.turn_counter = self.green_memories.get_turn_counter()
            self.decay_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="DecayThread"
            )
            logger.info("Memory Decay executor initialized.")

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
                        paragraph_sentences = [
                            sent.text.strip()
                            for sent in doc.sents
                            if sent.text.strip()
                        ]
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
            skill_id = (
                split_sentence[1].strip("\n")
                if len(split_sentence) > 1
                else "skill_id"
            )
            yield ndjson(
                "signal",
                "loading",
                {"state": "start", "type": "skill", "skill_id": skill_id},
            )
            return

        try:
            cleaned_sentence = re.sub(r"^\[\d{1,2}:\d{2}\]\s*", "", sentence)
            audio_file, duration = self.tts.generate_audio(cleaned_sentence)
            if stream_type == "json":
                event_data = self._create_audio_stream_event(
                    audio_file=audio_file,
                    text_content=cleaned_sentence,
                    duration=duration,
                )
                yield ndjson("message", "stream", event_data)
            else:
                # logger.info("_process_streaming_sentence 4 '" + sentence + "'")
                char_delay = (
                    duration / len(cleaned_sentence) if cleaned_sentence else 0
                )
                if not self.tts.play_audio(audio_file):
                    raise RuntimeError("Failed to start audio playback")
                for char in cleaned_sentence:
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

        # Handle non-TTS streaming directly to avoid sentence splitting logic
        if not self.tts:
            cleaned_text = re.sub(
                r"^\[\d{1,2}:\d{2}\]\s*", "", text, flags=re.MULTILINE
            )
            if stream_type == "json":
                event_data = {
                    "content": cleaned_text,
                    "flags": {"command": False, "audio": False},
                }
                yield ndjson("message", "stream", event_data)
                return
            elif stream_type == "cli":
                print(cleaned_text, end="", flush=True)
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
        current_summary = self.current_summary
        if current_summary and current_summary != "-":
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

    def shutdown(self):
        """Saves persistent state and gracefully shuts down background threads."""
        logger.info("Shutting down thread executors")
        # Shutdown the thread executors
        if self.summary_executor:
            self.summary_executor.shutdown(wait=True)
        if self.decay_executor:
            self.decay_executor.shutdown(wait=True)

    def _trigger_memory_decay_in_background(self):
        """Trigger background task to decay memory relevance."""
        with self.decay_lock:
            if self.decay_in_progress:
                logger.debug(
                    "Memory decay task already in progress. Skipping."
                )
                return
            self.decay_in_progress = True
            logger.info("Submitting memory decay task to background executor.")

        self.decay_executor.submit(self._background_decay_task)

    def _background_decay_task(self):
        """Background worker to decay memory relevance."""
        try:
            logger.info("Background task started: Decaying memory relevance.")
            self.green_memories.decay_all_memories()
            logger.info("Background task finished: Memory decay complete.")
        except Exception as e:
            logger.error(f"Error in background memory decay task: {e}")
        finally:
            with self.decay_lock:
                self.decay_in_progress = False

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
        system_tokens = system_message["tokens"]
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

    def _handle_test_doc_view_stream(self, question: str, stream: str):
        parts = question.strip().split(" ", 1)
        if len(parts) < 2 or "," not in parts[1]:
            usage_msg = "Usage: /testdocview <format>,<content>"
            if stream == "cli":
                print(usage_msg)
            else:  # json stream
                yield ndjson("signal", "loading", {"state": "start"})
                yield ndjson(
                    "message",
                    "stream",
                    {
                        "content": usage_msg,
                        "flags": {"command": False, "audio": False},
                    },
                )
                yield ndjson("signal", "loading", {"state": "stop"})
                yield ndjson("signal", "completed", None)
                logger.info("_handle_test_doc_view_stream 4")
            return

        command_body = parts[1]
        doc_format, doc_content = command_body.split(",", 1)

        if stream == "json":
            yield ndjson("signal", "loading", {"state": "start"})
            yield ndjson(
                "ui",
                "setView",
                {"view": "document", "format": doc_format},
            )
            yield ndjson("content", "full", {"content": doc_content})
            yield ndjson("signal", "loading", {"state": "stop"})
            yield ndjson("signal", "completed", None)
        elif stream == "cli":
            print(f"\n--- Document (format: {doc_format}) ---")
            print(doc_content)
            print("---------------------------------")

    def _handle_test_nexus_stream(self, command: str, stream: str):
        """Handles streaming for the /testnexus command."""
        parts = command.strip().split(" ", 2)
        usage_msg = (
            "Usage: /testnexus <vendor>,<bundle>,<component> <json_data>"
        )

        if len(parts) < 3:
            if stream == "cli":
                print(usage_msg)
            else:  # json stream
                yield ndjson("signal", "loading", {"state": "start"})
                yield ndjson(
                    "message",
                    "stream",
                    {
                        "content": usage_msg,
                        "flags": {"command": False, "audio": False},
                    },
                )
                yield ndjson("signal", "loading", {"state": "stop"})
                yield ndjson("signal", "completed", None)
            return

        _command, ui_parts_str, data_json_str = parts
        ui_parts = ui_parts_str.split(",")

        if len(ui_parts) != 3:
            if stream == "cli":
                print(usage_msg)
            else:  # json stream
                yield ndjson("signal", "loading", {"state": "start"})
                yield ndjson(
                    "message",
                    "stream",
                    {
                        "content": usage_msg,
                        "flags": {"command": False, "audio": False},
                    },
                )
                yield ndjson("signal", "loading", {"state": "stop"})
                yield ndjson("signal", "completed", None)
            return

        vendor, bundle, component = ui_parts

        try:
            data = json.loads(data_json_str)
        except json.JSONDecodeError:
            error_msg = "Error: Invalid JSON data provided."
            if stream == "cli":
                print(error_msg)
            else:  # json stream
                yield ndjson("signal", "loading", {"state": "start"})
                yield ndjson("signal", "error", {"message": error_msg})
                yield ndjson("signal", "loading", {"state": "stop"})
                yield ndjson("signal", "completed", None)
            return

        component_path = f"/nexus/{vendor}/{bundle}/{component}/index.html"

        if stream == "json":
            yield ndjson("signal", "loading", {"state": "start"})
            nexus_data = {
                "component_path": component_path,
                "data": data,
                # "query": f"Test #{self.nexus_test} {vendor}/{bundle}/{component}",
                "query": f"Test #{self.nexus_test}",
            }
            # Create a descriptive message for the chat history
            history_message = (
                "Nexus component data was generated and sent to the UI. "
                f"Data: {json.dumps(nexus_data)}"
            )
            self.llm.add_msg(history_message, self.chat_history, "assistant")
            yield ndjson("ui", "renderNexus", nexus_data)
            yield ndjson("signal", "loading", {"state": "stop"})
            yield ndjson("signal", "completed", None)
            self.nexus_test = self.nexus_test + 1
        elif stream == "cli":
            print("\n--- Nexus Component ---")
            print(f"Path: {component_path}")
            print(f"Data: {pprint.pformat(data)}")
            print("-----------------------")

    def _handle_memory_command(
        self, command: str, stream: Optional[Literal["cli", "json"]]
    ):
        """Handles /memory and /nomemory commands, updating the config."""
        response = ""
        command_lower = command.strip().lower()
        state_changed = False
        new_state = self.memory_enabled

        if command_lower == "/memory":
            if not self.memory_enabled:
                self.memory_enabled = True
                if "memory" not in config.config:
                    config.config["memory"] = {}
                config.config["memory"]["enabled"] = True
                config.save()
                self._initialize_memory_if_needed()
                response = "Memory enabled"
                state_changed = True
                new_state = True
            else:
                response = "Memory is already enabled."
        elif command_lower == "/nomemory":
            if self.memory_enabled:
                self.memory_enabled = False
                if "memory" not in config.config:
                    config.config["memory"] = {}
                config.config["memory"]["enabled"] = False
                config.save()
                response = "Memory disabled"
                state_changed = True
                new_state = False
            else:
                response = "Memory disabled"

        if stream is None:
            return response

        def generator():
            if stream == "cli":
                print(response)
                return

            if state_changed:
                yield ndjson("ui", "setMemoryState", {"enabled": new_state})
            yield ndjson("signal", "infoMessage", {"message": response})

        return generator()

    def _handle_test_nexus_command(
        self, command: str, stream: Optional[Literal["cli", "json"]]
    ):
        """Handles the /testnexus command for all stream types."""
        if stream:  # cli or json
            return self._handle_test_nexus_stream(command, stream)
        else:  # no stream
            parts = command.strip().split(" ", 2)
            usage_msg = (
                "Usage: /testnexus <vendor>,<bundle>,<component> <json_data>"
            )
            if len(parts) < 3:
                return usage_msg

            _command, ui_parts_str, data_json_str = parts
            ui_parts = ui_parts_str.split(",")
            if len(ui_parts) != 3:
                return usage_msg

            vendor, bundle, component = ui_parts
            component_path = f"/nexus/{vendor}/{bundle}/{component}/index.html"
            return f"<nexus path=\"{component_path}\" data='{data_json_str}'/>"

    def _handle_test_doc_view_command(
        self, command: str, stream: Optional[Literal["cli", "json"]]
    ):
        """Handles the /testdocview command for all stream types."""
        if stream:  # cli or json
            return self._handle_test_doc_view_stream(command, stream)
        else:  # no stream
            parts = command.strip().split(" ", 1)
            if len(parts) < 2 or "," not in parts[1]:
                return "Usage: /testdocview <format>,<content>"

            command_body = parts[1]
            doc_format, doc_content = command_body.split(",", 1)
            return f"```{doc_format}\n{doc_content}```"

    def _handle_command(
        self, question: str, stream: Optional[Literal["cli", "json"]]
    ):
        """Checks for and handles special commands."""
        command = question.strip()
        if not command.startswith("/"):
            return None

        if command.lower() in ["/memory", "/nomemory"]:
            return self._handle_memory_command(command, stream)

        if command.lower().startswith("/testdocview"):
            return self._handle_test_doc_view_command(command, stream)

        if command.lower().startswith("/testnexus"):
            return self._handle_test_nexus_command(command, stream)

        return None

    def _calculate_reasoning_level_heuristic(self, query: str) -> float:
        """
        Calculates a reasoning level based on linguistic analysis of the query using spaCy.
        This rule-based approach identifies linguistic features that suggest a need for
        reasoning, such as specific verbs, question structures, and comparative language.
        """
        if not self.reasoning_heuristic_enabled:
            return 0.0

        # Basic filter for very short queries that are unlikely to require reasoning
        if len(query.split()) <= 3:
            return 0.0

        doc = self.nlp(query.lower())
        score = 0.0

        # --- Define linguistic features and their weights ---
        # High-impact verbs that strongly suggest analysis, synthesis, or evaluation
        reasoning_verbs = {
            "analyze", "assess", "compare", "conduct", "contrast", "critique",
            "describe", "design", "develop", "differentiate", "evaluate",
            "explain", "find", "formulate", "investigate", "justify",
            "predict", "recommend", "suggest", "summarize", "synthesize",
            "write",
        }
        # Phrases that indicate hypothetical or causal reasoning
        hypothetical_phrases = [
            "what if", "what would", "what are the", "what is the",
        ]
        # Interrogatives that often require explanation
        explanatory_interrogatives = {"why", "how"}

        # --- Rule-based scoring ---
        # Rule 1: Check for high-impact reasoning verbs (especially as the root)
        root_verb = ""
        for token in doc:
            if token.dep_ == "ROOT" and token.pos_ == "VERB":
                root_verb = token.lemma_
                if token.lemma_ in reasoning_verbs:
                    score += 1.0
                    logger.debug(
                        "Heuristic: Found root reasoning verb"
                        f" '{token.lemma_}' (+1.0)"
                    )
                break

        # Rule 2: Check for explanatory interrogatives at the start
        if doc[0].lemma_ in explanatory_interrogatives:
            score += 0.4
            logger.debug(
                f"Heuristic: Found explanatory interrogative '{doc[0].text}'"
                " (+0.4)"
            )

        # Rule 3: Check for hypothetical phrases
        for phrase in hypothetical_phrases:
            if phrase in doc.text:
                score += 1.0
                logger.debug(
                    f"Heuristic: Found hypothetical phrase '{phrase}' (+1.0)"
                )
                break  # Avoid double counting

        # Rule 4: Check for any reasoning verb, even if not the root
        if score < 0.5:  # Only apply if a strong signal hasn't been found
            for token in doc:
                if (
                    token.lemma_ in reasoning_verbs
                    and token.lemma_ != root_verb
                ):
                    score += 0.2
                    logger.debug(
                        "Heuristic: Found non-root reasoning verb"
                        f" '{token.lemma_}' (+0.2)"
                    )
                    break

        # Rule 5: Check for comparatives/superlatives as a weaker signal
        has_comparative = any(tok.tag_ in ["JJR", "RBR"] for tok in doc)
        has_superlative = any(tok.tag_ in ["JJS", "RBS"] for tok in doc)
        if has_comparative or has_superlative:
            score += 0.15
            logger.debug("Heuristic: Found comparative/superlative (+0.15)")

        # --- Finalize heuristic value ---
        # Normalize score to be within [0, 1] and apply the configured max level
        heuristic_value = min(score, 1.0) * self.reasoning_max_level
        logger.info(
            f"Reasoning heuristic score: {score:.4f}, final value:"
            f" {heuristic_value:.4f}"
        )

        return heuristic_value

    def chat_completion(
        self, question: str, stream: Optional[Literal["cli", "json"]] = "cli"
    ) -> Union[str, Generator[str, None, None], dict]:
        # user_message_id = None
        # assistant_message_id = None
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

        # Handle special commands
        command_response = self._handle_command(question, stream)
        if command_response is not None:
            # Delegate to the command's generator and then stop execution
            yield from command_response
            return

        # Calculate heuristic before any LLM call
        reasoning_level_heuristic = self._calculate_reasoning_level_heuristic(
            question
        ) if self.llm.thinking_available else 0
        logger.info(
            "chat_completion: Estimated reasoning_level_heuristic:"
            f" {reasoning_level_heuristic}, query:\n> {question}"
        )

        # Check if spaCy model is available
        if not self.nlp:
            raise RuntimeError("spacy model not available")

        # Start loading animation for CLI mode or send start event for JSON mode
        loading = None
        if stream == "cli":
            loading = LoadingAnimation("")
            loading.start()
        elif stream == "json":
            yield ndjson(
                "signal",
                "loading",
                {"state": "start", "reasoning": reasoning_level_heuristic},
            )

        processed_answer = ""
        try:
            if self.memory_enabled and self.chat_memory:
                self.chat_memory.add_entry(question, "user")

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

            # --- Summary and Memory Injection ---
            turn_chat_history = self.chat_history

            # Atomically check and apply any new summary
            if self.summary_enabled:
                with self.buffer_lock:  # Use the existing lock for consistency
                    if self.new_summary:
                        self.current_summary = self.new_summary
                        self.new_summary = (  # Clear it while holding the lock
                            "-"
                        )
                        logger.info("Retrieved new summary for application")

            # Prepare combined system prompt content
            final_system_content = self.system_message
            if (
                self.summary_enabled
                and self.current_summary
                and self.current_summary != "-"
            ):
                final_system_content += (
                    f"\n\n--- Conversation Summary ---\n{self.current_summary}"
                )

            # --- User Profile Injection (from cached summary) ---
            if self.memory_enabled and self.user_profile_summary:
                # final_system_content += f"\n\n--- Next paragraph contains key information about the user, possibly including the user's name, which I MUST take into account:\n{self.user_profile_summary}"
                final_system_content += (
                    "\n\n--- IMPORTANT: The following is key information"
                    " about the user you are talking to. You MUST use this"
                    " information, such as their name, to personalize your"
                    f" responses. ---\n{self.user_profile_summary}"
                )

            # --- Recent Memories Summary Injection ---
            if self.memory_enabled and self.green_memories:
                recent_memories_summary = (
                    self.green_memories.generate_recent_memories_summary()
                )
                if recent_memories_summary:
                    final_system_content += (
                        "\n\n--- This is a summary of topics and facts that"
                        " have been discussed recently. Use this to maintain"
                        " conversation continuity."
                        f" ---\n{recent_memories_summary}"
                    )

            # --- Context Memories ---
            if self.memory_enabled and self.green_memories:
                # 1. Create a search query from the last few turns for better context
                history_for_search = self.prepare_chat_history_for_skill()[
                    -10:
                ]  # Last 5 exchanges

                search_context_parts = []
                if self.current_summary and self.current_summary != "-":
                    # add the current conversation summary as the first element
                    # of the search_context dict
                    summary_text = (
                        "This is a summary of the conversation so far:"
                        f" {self.current_summary}"
                    )
                    search_context_parts.append(summary_text)

                history_text = "\n".join(
                    [
                        f"{msg['role']}: {msg['content']}"
                        for msg in history_for_search
                    ]
                )
                search_context_parts.append(history_text)
                search_context = "\n\n".join(search_context_parts)

                # logger.info(f"search_context: {search_context}")

                relevant_memories = self.green_memories.get_relevant_memories(
                    search_context
                )
                # logger.info(f"relevant_memories: {relevant_memories}")

                if relevant_memories:
                    # Pre-process memories to format the relevance score for display
                    processed_memories_for_template = []
                    for mem in relevant_memories:
                        processed_mem = mem.copy()
                        processed_mem["relevance_score"] = (
                            f"{processed_mem.get('relevance', 0.0):.2f}"
                        )
                        processed_memories_for_template.append(processed_mem)

                    logger.info(
                        "Injecting"
                        f" {len(processed_memories_for_template)} dynamically"
                        " retrieved memories into context."
                    )
                    context_memories_prompt = self.template_manager.render(
                        "framework.chat_manager.user_memories_prompt",
                        {"memories": processed_memories_for_template},
                    )
                    final_system_content += f"\n\n{context_memories_prompt}"
                    # logger.info(f"context_memories_prompt: {context_memories_prompt}")
                else:
                    logger.info("No relevant memories found to be injected.")

            # Update the single system message
            self.chat_history[0]["content"] = final_system_content
            self.chat_history[0]["tokens"] = self.llm._get_token_count(
                final_system_content, "system"
            )
            logger.info("Updated system prompt with summary and memories.")

            # Trim context *after* injecting memories to ensure we are within limits
            self.trim_context()

            guardrail_retries = 0
            final_chunks = []

            while guardrail_retries <= self.max_guardrail_retries:
                # --- LLM Call ---
                llm_response_stream = self.llm.chat(
                    chat_history=turn_chat_history,
                    stream=True,
                    reasoning_level=reasoning_level_heuristic,
                )

                def _stream_with_thinking_markers(raw_stream):
                    buffer = ""
                    in_thinking = False
                    for chunk in raw_stream:
                        buffer += chunk
                        while True:
                            if not in_thinking:
                                start_pos = buffer.find("<think>")
                                if start_pos != -1:
                                    yield buffer[:start_pos]
                                    yield "\n_AINARA_THINKING_START_\n"
                                    buffer = buffer[
                                        start_pos + len("<think>"):
                                    ]
                                    in_thinking = True
                                else:
                                    yield buffer
                                    buffer = ""
                                    break
                            if in_thinking:
                                end_pos = buffer.find("</think>")
                                if end_pos != -1:
                                    yield "\n_AINARA_THINKING_STOP_\n"
                                    buffer = buffer[
                                        end_pos + len("</think>"):
                                    ]
                                    in_thinking = False
                                else:
                                    break
                    if buffer:
                        yield buffer

                # Buffer response to check for guardrails before streaming to client
                stream_processor = self.orakle_middleware.process_stream(
                    _stream_with_thinking_markers(llm_response_stream),
                    self,
                    reasoning_level_heuristic=reasoning_level_heuristic,
                )
                buffered_chunks = list(stream_processor)

                guardrail_message = ""
                has_guardrail = False
                for chunk in buffered_chunks:
                    if (
                        isinstance(chunk, str)
                        and "[AINARA GUARDRAIL]" in chunk
                    ):
                        guardrail_message += chunk
                        has_guardrail = True

                if has_guardrail:
                    guardrail_retries += 1
                    logger.warning(
                        "Guardrail triggered (attempt"
                        f" {guardrail_retries}/{self.max_guardrail_retries + 1}):"
                        f" {guardrail_message.strip()}"
                    )
                    if guardrail_retries > self.max_guardrail_retries:
                        logger.error(
                            "Max retries reached. Responding with error."
                        )
                        if stream == "json":
                            error_content = guardrail_message.replace(
                                "[AINARA GUARDRAIL]", ""
                            ).strip()
                            yield ndjson(
                                "signal", "error", {"message": error_content}
                            )
                            final_chunks = []
                        else:
                            final_chunks = [guardrail_message]
                        break  # Exit retry loop
                    else:
                        # Add correction message for the next attempt and retry
                        self.llm.add_msg(
                            guardrail_message, self.chat_history, "user"
                        )
                        continue  # Next attempt
                else:
                    # Success
                    final_chunks = buffered_chunks
                    break  # Exit retry loop

            # Clean up any temporary guardrail messages from history
            self.chat_history = [
                msg
                for msg in self.chat_history
                if "[AINARA GUARDRAIL]" not in msg.get("content", "")
            ]

            # Now, process and stream the final response (successful or error)
            processed_answer = ""
            text_buffer = ""
            parsing_mode = "text"
            doc_buffer = ""
            doc_format = "plaintext"

            for chunk in final_chunks:
                # # --- TOKEN DEBUG
                # logger.info(f"Chunk from Orakle Middleware: {repr(chunk)}")
                if "_AINARA_THINKING_START_" in chunk:
                    yield ndjson("signal", "thinking", {"state": "start"})
                    continue
                if "_AINARA_THINKING_STOP_" in chunk:
                    yield ndjson("signal", "thinking", {"state": "stop"})
                    continue

                if (
                    isinstance(chunk, dict)
                    and chunk.get("type") == "nexus_skill_result"
                ):
                    vendor = chunk.get("vendor")
                    bundle = chunk.get("bundle")
                    component = chunk.get("component")
                    query = chunk.get("query")
                    skill_data = chunk.get("data", {})

                    if not all([vendor, bundle, component]):
                        logger.error(
                            "Nexus skill result received with incomplete"
                            f" component info: vendor='{vendor}',"
                            f" bundle='{bundle}', component='{component}'"
                        )
                        continue

                    component_path = (
                        f"/nexus/{vendor}/{bundle}/{component}/index.html"
                    )

                    nexus_data = {
                        "component_path": component_path,
                        "data": skill_data,
                        "query": query,
                    }

                    # Create a descriptive message for the chat history
                    history_message = (
                        "Nexus component data was generated and sent to the"
                        f" UI. Data: {json.dumps(nexus_data)}"
                    )
                    self.llm.add_msg(
                        history_message, self.chat_history, "assistant"
                    )

                    yield ndjson("ui", "renderNexus", nexus_data)
                    continue

                if not chunk:
                    continue

                processed_answer += chunk

                # Route chunk to the correct buffer based on current parsing mode
                if parsing_mode == "doc":
                    doc_buffer += chunk
                else:
                    text_buffer += chunk

                # --- State Machine for Parsing ---
                # Loop to handle multiple state transitions within a single chunk (e.g., <doc>...</doc>)
                while True:
                    state_changed = False
                    if parsing_mode == "text":
                        doc_start_match = re.search(
                            r"```([\w\d_.-]*)\n", text_buffer
                        )
                        if doc_start_match:
                            pre_doc_text = text_buffer[
                                : doc_start_match.start()
                            ]
                            if pre_doc_text.strip():
                                yield from self._process_regular_text(
                                    pre_doc_text, stream
                                )

                            doc_format = (
                                doc_start_match.group(1) or "plaintext"
                            )
                            if stream == "json":
                                yield ndjson(
                                    "ui",
                                    "setView",
                                    {"view": "document", "format": doc_format},
                                )

                            parsing_mode = "doc"
                            doc_buffer = text_buffer[doc_start_match.end():]
                            text_buffer = ""
                            state_changed = True

                    elif parsing_mode == "doc":
                        doc_end_match = re.search(r"```", doc_buffer)
                        if doc_end_match:
                            doc_content = doc_buffer[: doc_end_match.start()]
                            if stream == "json":
                                yield ndjson(
                                    "content", "full", {"content": doc_content}
                                )

                            parsing_mode = "text"
                            text_buffer = doc_buffer[doc_end_match.end():]
                            doc_buffer = ""
                            state_changed = True

                    if not state_changed:
                        break

                # --- Regular Text Processing ---
                if parsing_mode == "text" and text_buffer:
                    if self.tts:
                        sentences = self._extract_complete_sentences(
                            text_buffer
                        )
                        if sentences:
                            if stream == "cli":
                                loading.stop()
                            elif stream == "json":
                                yield ndjson(
                                    "signal", "loading", {"state": "stop"}
                                )
                            for sentence in sentences:
                                yield from self._process_streaming_sentence(
                                    sentence, stream
                                )

                            last_sentence = sentences[-1]
                            last_pos = text_buffer.rfind(last_sentence) + len(
                                last_sentence
                            )
                            text_buffer = text_buffer[last_pos:].strip()
                    elif text_buffer:  # Non-TTS streaming
                        (
                            print(text_buffer, end="", flush=True)
                            if stream == "cli"
                            else None
                        )
                        text_buffer = ""

            # Process any remaining text in the buffer
            if text_buffer.strip():
                yield from self._process_regular_text(text_buffer, stream)

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
                if self.memory_enabled and self.chat_memory:
                    self.chat_memory.add_entry(processed_answer, "assistant")
            else:
                # If there's no processed answer, add a placeholder
                logger.warning("No answer from the LLM, adding placeholder")
                self.llm.add_msg(
                    "No response generated", self.chat_history, "assistant"
                )
                if self.memory_enabled and self.chat_memory:
                    self.chat_memory.add_entry(
                        "No response generated", "assistant"
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

            # --- Memory Decay ---
            if self.memory_enabled and self.memory_decay_interval > 0:
                self.turn_counter += 1
                if self.turn_counter >= self.memory_decay_interval:
                    logger.info(
                        f"decay turn counter {self.turn_counter} over "
                        "limit, triggering decay"
                    )
                    self._trigger_memory_decay_in_background()
                    self.green_memories.reset_turn_counter()
                    self.turn_counter = 0  # Reset in-memory counter
                logger.info(f"Saving turn counter state: {self.turn_counter}")
                if self.green_memories:
                    self.green_memories.save_turn_counter(self.turn_counter)

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
        formatted_history = []
        for msg in self.chat_history:
            # Only include user and assistant messages, skip system messages
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                if msg["role"] in ["user", "assistant"]:
                    formatted_history.append(
                        {"role": msg["role"], "content": msg["content"]}
                    )
        return formatted_history
