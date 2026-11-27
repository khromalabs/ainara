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


import copy
import json
import logging
import os
import pprint
import re
import shutil
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Generator, List, Literal, Optional, Union

from pycountry import languages
from pygame import mixer

from ainara.framework.chat_memory import ChatMemory
from ainara.framework.config import config
from ainara.framework.deep_recall import DeepRecallEngine
from ainara.framework.green_memories import GREENMemories
from ainara.framework.loading_animation import LoadingAnimation
from ainara.framework.orakle_middleware import (OrakleCapabilityFetcher,
                                                OrakleMiddleware)
from ainara.framework.skills.register import register_service
from ainara.framework.storage.base import StorageBackend
from ainara.framework.template_manager import TemplateManager
from ainara.framework.tts.base import TTSBackend
from ainara.framework.utils import load_spacy_model, format_relative_time

# import pprint

# from ainara.framework.utils import format_orakle_command

logger = logging.getLogger(__name__)


class _GuardrailRetrySignal:
    """Internal signal to indicate a guardrail-triggered retry."""

    pass


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
        storage_backend: StorageBackend,
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
        self.processed_memories_for_template = None
        self.current_lang_code = None
        self.current_language = None
        self.storage_backend = storage_backend
        self.first_turn = True

        # Load spaCy model for sentence segmentation
        self.nlp = load_spacy_model()

        # Initialize template manager
        self.template_manager = TemplateManager()

        # Initialize chat memory
        self.chat_memory = chat_memory
        self.green_memories = green_memories
        self.user_profile_summary = user_profile_summary
        self.memory_enabled = config.get("memory.enabled", True)
        self.summary_enabled = config.get("memory.summary_enabled", True)
        self.notifications_enabled = config.get(
            "memory.notifications_enabled", True
        )
        self.notifications_prompt = ""

        # --- Session Topic (assistant-evaluated, decaying) ---
        # Detected in the background while the user composes their next
        # turn and applied atomically at the start of the next one (same
        # pattern as new_summary). Decays after session_topic_max_age
        # turns without confirmation so stale topics stop boosting
        # memory retrieval.
        self.session_topic_max_age = config.get(
            "memory.injection.session_topic.max_age_turns", 3
        )
        # Recent-exchange window for retrieval seeding. The session topic
        # carries the conversational continuity, so this only needs to
        # cover reference resolution ("what about the second option?").
        self.search_history_exchanges = config.get(
            "memory.injection.search_history_exchanges", 2
        )
        # Per-turn topic classifier (background LLM call). The session
        # topic is a GENERATED free-form label describing what the
        # conversation is about right now — never picked from the stored
        # topic vocabulary, which cannot abstain (any text scores ~0.5
        # against some label when the vocabulary is large).
        self.session_topic_classifier_enabled = config.get(
            "memory.injection.session_topic.classifier_enabled", True
        )
        self.session_topic_window = config.get(
            "memory.injection.session_topic.detection_window_messages", 10
        )
        # Per-message truncation inside the classifier window: topic
        # detection needs the gist, not message bodies (code blocks,
        # Deep Recall trails...). Bounds the window cost worst-case.
        self.session_topic_max_msg_chars = config.get(
            "memory.injection.session_topic.max_message_chars", 250
        )
        self.current_session_topic: Optional[str] = None
        self.new_session_topic: Optional[str] = None
        self.session_topic_age = 0
        self.session_topic_lock = threading.Lock()

        self.max_guardrail_retries = config.get("guardrails.max_retries", 2)
        self._orakle_trailing_text_violation = False
        # --- Memory Decay Tracking (persisted between sessions) ---
        self.memory_decay_interval = config.get(
            "memories.decay_interval_turns", 5
        )
        self.turn_counter = 0
        self.decay_in_progress = False
        self.decay_lock = threading.Lock()
        self.last_chat_timestamp = None
        self.last_chat_relative_time = None
        if (
            self.memory_enabled
            and self.green_memories
            and self.memory_decay_interval > 0
        ):
            self.turn_counter = self.green_memories.get_turn_counter()
            last_messages = self.storage_backend.get_messages(1)
            last_message_previous_chat = (
                last_messages[0] if last_messages else {}
            )
            self.last_chat_timestamp = last_message_previous_chat.get(
                "timestamp"
            )
            self.last_chat_relative_time = format_relative_time(
                self.last_chat_timestamp
            )
            logger.info(f"Last message: {self.last_chat_relative_time} / {self.last_chat_timestamp}")

        # Fetch capabilities first
        if capabilities:
            self.capabilities = capabilities
        else:
            fetcher = OrakleCapabilityFetcher(self.orakle_servers)
            self.capabilities = fetcher.fetch_capabilities()

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

        # Format skills descriptions as a comma-separated list for the ephemeral hint
        skills_names = []
        for skill in self.capabilities:
            skills_names.append(skill["name"])
        self.skills_hint_text = ", ".join(skills_names)

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

        # Compute static-per-session context for the system prompt
        # These values never change during the session → cache-friendly
        self.recent_memories_summary = None
        if self.memory_enabled and self.green_memories:
            self.recent_memories_summary = (
                self.green_memories.generate_recent_memories_summary()
            )
            if self.recent_memories_summary:
                logger.info("Recent memories summary computed at session init.")

        # Update system message with all static-per-session content
        if self.last_chat_timestamp and not self.first_turn:
            # Disable greeting advice after first turn
            self.last_chat_timestamp = ""

        self.system_message = self.template_manager.render(
            "framework.chat_manager.system_prompt",
            {
                "is_new_profile": is_new_profile,
                "skills_hint_text": self.skills_hint_text,
                "user_profile_summary": self.user_profile_summary or "",
                "recent_memories_summary": self.recent_memories_summary or "",
                "last_chat_timestamp": getattr(
                    self, "last_chat_relative_time", None
                ) or "",
            },
        )

        # Initialize Orakle middleware with the rendered system message
        self.orakle_middleware = OrakleMiddleware(
            llm=llm,
            orakle_servers=orakle_servers,
            system_message=self.system_message,
            capabilities=self.capabilities,
        )

        # Deep Recall engine (deliberative memory tier): registered so
        # the PyBridge REST surface (/framework/deep_recall) can serve
        # it; the engine resolves its LLM from the memory tier per run.
        self.deep_recall_engine = None
        if (
            self.memory_enabled
            and self.green_memories
            and self.chat_memory
        ):
            self.deep_recall_engine = DeepRecallEngine(
                self.green_memories, self.chat_memory
            )
            register_service("deep_recall_engine", self.deep_recall_engine)

        self.llm.add_msg(self.system_message, self.chat_history, "system")

        # Initialize executor if either summary or decay is enabled
        self.summary_executor = None
        if self.summary_enabled:
            self.summary_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="SummaryThread"
            )

        self.notification_executor = None
        if self.notifications_enabled:
            self.notification_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="NotificationThread"
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

        self.topic_executor = None
        if self.memory_enabled and self.green_memories:
            self.topic_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="TopicThread"
            )

        # Summary fields are created unconditionally: the manual /compact
        # command must work even when the automatic summary path
        # (memory.summary_enabled) is disabled.
        self.trimmed_messages_buffer = []
        # Lock specifically for buffer operations
        self.buffer_lock = threading.Lock()
        self.summary_in_progress = False
        self.current_summary = "-"

        if self.notifications_enabled:
            # Lock specifically for buffer operations
            self.notifications_lock = threading.Lock()
            self.notification_in_progress = False

    def update_llm(self, llm):
        self.llm = llm
        self.orakle_middleware.update_llm(llm)
        if self.green_memories:
            self.green_memories.update_llm(llm)

    def _initialize_memory_if_needed(self):
        """Initializes memory components if they haven't been already."""
        if self.chat_memory is None:
            logger.info("Initializing ChatMemory on-demand...")
            # TODO ahora esto necesita el storage
            self.chat_memory = ChatMemory(storage_backend=self.storage_backend)
            logger.info("Chat memory initialized.")

        if self.green_memories is None:
            logger.info("Initializing GREENMemories on-demand...")
            self.green_memories = GREENMemories(
                llm=self.llm,
                chat_memory=self.chat_memory,
            )
            logger.info("User Memories Manager initialized.")
            # Perform initial consolidation
            logger.info("Processing existing messages for GREEN memories...")
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

        if "_orakle_agent_progress_" in sentence:
            # Run-journal progress relay (issues #26/#35): a stage label
            # from a spawned agent's journal, carrying the run id (#35)
            # — the address the com-ring's Ctrl+C cancel command posts
            # against. Forwarded as a signal event so it never reaches
            # TTS/text output. Old format (label only) stays parseable.
            parts = sentence.strip().split("|", 2)
            run_id = parts[1].strip() if len(parts) > 2 else ""
            label = (
                parts[2].strip()
                if len(parts) > 2
                else (parts[1].strip() if len(parts) > 1 else "")
            )
            yield ndjson(
                "signal",
                "agent_progress",
                {"label": label, "run_id": run_id},
            )
            return

        if "_orakle_status_" in sentence:
            # Mechanical status pill (#37, #35): a framework-written
            # record — surface, never speech. Streamed as a display-only
            # event (audio: False, same shape as the no-TTS path) so
            # base.js renders the pill while TTS never speaks the
            # marker.
            cleaned_sentence = re.sub(
                r"^\[\d{1,2}:\d{2}\]\s*", "", sentence
            )
            if stream_type == "json":
                yield ndjson(
                    "message",
                    "stream",
                    {
                        "content": cleaned_sentence,
                        "flags": {"command": False, "audio": False},
                    },
                )
            else:
                print(cleaned_sentence)
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

        Returns:
            tuple: (generated summary text, fused session-topic label or
                None when the LLM did not emit a usable Topic line)
        """
        if not messages_to_summarize:
            return "", None

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
            # Fused session-topic detection: the summary pass is also
            # asked to name the current conversation topic, which becomes
            # the most authoritative session-topic update (Tier 1).
            "current_topic": self.current_session_topic or "none",
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

            # Extract the fused session-topic line BEFORE cleaning/truncating
            # (truncation could otherwise cut it off).
            topic_match = re.search(
                r"^topic:\s*(.+)$", summary, re.IGNORECASE | re.MULTILINE
            )
            session_topic = (
                topic_match.group(1).strip() if topic_match else None
            )
            if topic_match:
                summary = summary[: topic_match.start()].rstrip()

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
            return summary, session_topic
        except Exception as e:
            logger.error(f"Error generating conversation summary: {e}")
            # Fall back to template-based summary
            return self._create_template_summary(messages_to_summarize), None

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
                # Generate the summary (also fuses a session-topic label)
                new_summary, llm_topic = (
                    self._generate_conversation_summary(
                        messages_to_summarize
                    )
                )
                # Safely update the new_summary with the lock
                with self.buffer_lock:
                    self.new_summary = new_summary
                    self.summary_in_progress = False
                    logger.info(
                        f"Generated new summary: {new_summary[:50]}..."
                    )
                # Tier 1: the assistant-evaluated topic is the most
                # authoritative session-topic update; it is applied at
                # the start of the next turn alongside the summary.
                if llm_topic:
                    with self.session_topic_lock:
                        self.new_session_topic = llm_topic
                        logger.info(
                            "Fused session topic from summary pass:"
                            f" {llm_topic}"
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

    def _update_session_topic_in_background(self):
        """Trigger the background per-turn session-topic update.

        A small LLM call (in TopicThread, invisible to response latency)
        generates a free-form label for what the conversation is about
        RIGHT NOW, prioritizing the last messages: a topic switch in the
        latest exchange becomes the new topic on the next turn. It may
        reply NONE (greetings, small talk) — generation can abstain,
        selection from the stored topic vocabulary cannot. The heavier
        assistant-evaluated topic also arrives fused into the background
        summary pass whenever that fires; both feed the same pending slot
        and are applied atomically at the start of the next turn."""
        if not (self.memory_enabled and self.green_memories):
            return
        if not self.topic_executor or not self.session_topic_classifier_enabled:
            return

        window_msgs = [
            msg
            for msg in self.chat_history[-self.session_topic_window:]
            if isinstance(msg, dict)
            and msg.get("role") in ("user", "assistant")
            and msg.get("content")
        ]
        if not window_msgs:
            return
        window_lines = []
        for msg in window_msgs:
            content = " ".join(msg["content"].split())
            if len(content) > self.session_topic_max_msg_chars:
                content = (
                    content[: self.session_topic_max_msg_chars].rstrip()
                    + "…"
                )
            window_lines.append(f"{msg['role']}: {content}")

        template_context = {
            "previous_topic": self.current_session_topic or "none",
            "conversation_window": "\n".join(window_lines),
        }
        if self.current_summary and self.current_summary != "-":
            template_context["current_summary"] = self.current_summary
        prompt = self.template_manager.render(
            "framework.chat_manager.session_topic", template_context
        )

        def _background_topic_task():
            try:
                temp_history = []
                self.llm.add_msg(
                    "You are a helpful assistant.", temp_history, "system"
                )
                self.llm.add_msg(prompt, temp_history, "user")
                raw = self.llm.chat(chat_history=temp_history, stream=False)
                label = (raw or "").strip().strip("'\"")
                if re.fullmatch(
                    r"(none|n/?a|unknown|no( clear)? topic)[.!\"]*",
                    label,
                    re.IGNORECASE,
                ):
                    return
                if not label:
                    return
                # Skip if an unapplied update is already pending —
                # it is fresher (or the LLM-fused Tier 1 result).
                with self.session_topic_lock:
                    if self.new_session_topic is None:
                        self.new_session_topic = label[:60]
                        logger.info(
                            f"Background topic classifier: {label[:60]}"
                        )
            except Exception as e:
                logger.error(f"Error in background topic task: {e}")

        self.topic_executor.submit(_background_topic_task)

    def _update_notifications_in_background(self):
        """Trigger background task to update the notifications notification"""
        # Check if notification is already in progress without locking the buffer
        if self.notification_in_progress:
            return

        # Check if there are messages to summarize
        with self.notifications_lock:
            self.notification_in_progress = True

        def _background_notification_task():
            try:
                self.app.notification_manager.consolidate_events()
                pending_items = (
                    self.app.notification_manager.get_and_clear_notifications()
                )
                _notifications_prompt = ""
                for item in pending_items:
                    _notifications_prompt += (
                        f"- [{item['source']} - {item['timestamp']}]:"
                        f" {item['summary']}\n"
                    )
                # Safely update the notifications_prompt with the lock
                with self.notifications_lock:
                    if _notifications_prompt:
                        self.notifications_prompt = _notifications_prompt
                    self.notification_in_progress = False
                    logger.info(
                        "Generated new notifications:"
                        f" {self.notifications_prompt[:50]}..."
                    )

            except Exception as e:
                logger.error(f"Error in background notification task: {e}")
                with self.notifications_lock:
                    self.notification_in_progress = False
                    self.notifications_prompt = ""

        # Submit the task to our executor
        self.notification_executor.submit(_background_notification_task)

    def shutdown(self):
        """Saves persistent state and gracefully shuts down background threads."""
        logger.info("Shutting down thread executors")
        # Shutdown the thread executors
        if self.summary_executor:
            self.summary_executor.shutdown(wait=True)
        if self.decay_executor:
            self.decay_executor.shutdown(wait=True)
        if self.topic_executor:
            self.topic_executor.shutdown(wait=True)

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

    def get_context_usage(self):
        """Return current context-window usage for the active session.

        Uses the same accounting as trim_context: total tokens held in
        the live chat history (system message included) against the
        model's context window.
        """
        used_tokens = self._count_tokens_in_history()
        context_window = self.llm.get_context_window()
        percentage = None
        if context_window:
            percentage = round(used_tokens / context_window * 100, 1)
        return {
            "used_tokens": used_tokens,
            "context_window": context_window,
            "percentage": percentage,
        }

    def trim_context(self, max_tokens=None, reserved_tokens=0):
        """
        Trim the chat history to stay within token limits while preserving context.

        Args:
            max_tokens: Maximum tokens to allow (defaults to model's context window)
            reserved_tokens: Tokens to reserve for per-turn dynamic injections
                (e.g. system_hint content appended to the shadow copy)
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
        available_tokens = max_tokens - system_tokens - reserved_tokens

        logger.info(f"System message uses {system_tokens} tokens")
        if reserved_tokens > 0:
            logger.info(
                f"Reserving {reserved_tokens} tokens for per-turn"
                " dynamic hint injection"
            )
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

        # Always keep the last exchange (most recent) regardless of token
        # count. This MUST also cover the single-message case: dropping the
        # newest user turn would leave a system-only payload, which some
        # providers reject outright (e.g. Z.ai error 1214, "The messages
        # parameter is illegal") and which breaks the conversation anchor.
        # TODO Group messages by role for more flexible exchange handling
        if exchanges:
            # Assuming full exchanges come in pairs (user + assistant)
            take = 2 if len(exchanges) >= 2 else 1
            last_exchange = exchanges[-take:]

            logger.info("Keeping last exchange regardless of token count:")
            for msg in last_exchange:
                logger.info(
                    f"  - {msg.get('role', 'unknown')} message:"
                    f" {msg['tokens']} tokens"
                )
                tokens_used += msg["tokens"]
            # Prepend in original order (insert(0) per message would
            # reverse the pair, placing the newest user turn before the
            # assistant reply that preceded it)
            kept_exchanges = list(last_exchange) + kept_exchanges

            exchanges = exchanges[:-take]  # Remove from further consideration
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

            is_sticky = msg.get("sticky", False)
            if (
                is_sticky
                or system_tokens + tokens_used + msg_tokens <= available_tokens
            ):
                kept_exchanges.insert(0, msg)  # Add to front to maintain order
                tokens_used += msg_tokens
                kept_count += 1
                logger.info(
                    f"Keeping {msg.get('role', 'unknown')} message:"
                    f" {msg_tokens} tokens (Sticky: {is_sticky})"
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

    def _handle_test_tts_command(self, question: str, stream: str):
        parts = question.strip().split(" ", 1)
        if len(parts) < 1:
            usage_msg = "Usage: /testtts <content>"
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

        message = parts[1]
        if stream == "json":
            yield ndjson("signal", "loading", {"state": "start"})
            audio_file, duration = self.tts.generate_audio(message)
            event_data = self._create_audio_stream_event(
                audio_file=audio_file,
                text_content=message,
                duration=duration,
            )
            yield ndjson("message", "stream", event_data)
            yield ndjson("signal", "loading", {"state": "stop"})
            yield ndjson("signal", "completed", None)

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
                # Test surfaces behave as panels: re-running the test
                # command updates the singleton instead of stacking (#30)
                "mode": "panel",
                "panel_id": component_path,
            }
            # Create a descriptive message for the chat history
            history_message = f"_orakle_nexus_data_|{json.dumps(nexus_data)}"
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

    def _handle_test_user_ui_stream(self, command: str, stream: str):
        """Handles streaming for the /testuserui command."""
        parts = command.strip().split(" ", 2)
        usage_msg = "Usage: /testuserui <component_name> <json_data>"

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

        _command, component_name, data_json_str = parts

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

        component_path = f"/user_skills/components/{component_name}/index.html"

        if stream == "json":
            yield ndjson("signal", "loading", {"state": "start"})
            user_data = {
                "component_path": component_path,
                "data": data,
                "query": "User Skill Test",
                # Test surfaces behave as panels (#30)
                "mode": "panel",
                "panel_id": component_path,
            }
            history_message = f"_orakle_nexus_data_|{json.dumps(user_data)}"
            self.llm.add_msg(history_message, self.chat_history, "assistant")
            yield ndjson("ui", "renderNexus", user_data)
            yield ndjson("signal", "loading", {"state": "stop"})
            yield ndjson("signal", "completed", None)
        elif stream == "cli":
            print("\n--- User Skill Component ---")
            print(f"Path: {component_path}")
            print(f"Data: {pprint.pformat(data)}")
            print("----------------------------")

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
                self.user_profile_summary = ""
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

    def _handle_compact_command(
        self, command: str, stream: Optional[Literal["cli", "json"]]
    ):
        """Handles the /compact command.

        Manually trims the current session into the conversation summary:
        everything but the last two exchanges (plus any sticky messages,
        same contract as trim_context) is condensed into the summary,
        which is injected on the next turn via system_hint_content.
        Synchronous by design — the user asked for the window to be freed
        now — and independent of memory.summary_enabled, which gates only
        the automatic path.
        """
        # Fold any in-flight automatic summary first: wait for it and
        # apply its pending result before generating, so continuity
        # merging in _generate_conversation_summary sees it and the
        # pending new_summary cannot overwrite ours on the next turn.
        waited = 0.0
        while self.summary_in_progress and waited < 60.0:
            time.sleep(0.25)
            waited += 0.25

        to_summarize = []
        kept = []
        system_message = None
        with self.buffer_lock:
            if self.new_summary and self.new_summary != "-":
                self.current_summary = self.new_summary
                self.new_summary = "-"
            # Messages dropped by automatic trimming but not yet
            # summarized (e.g. a failed background pass put them back):
            # condense them too, oldest first, or their content would be
            # lost from the context window entirely.
            to_summarize.extend(self.trimmed_messages_buffer)
            self.trimmed_messages_buffer = []

            system_message = None
            body = []
            for msg in self.chat_history:
                if not isinstance(msg, dict):
                    continue
                if msg.get("role") == "system" and system_message is None:
                    system_message = msg
                else:
                    body.append(msg)

            # Keep the last two exchanges verbatim; sticky messages are
            # never summarized (same contract as trim_context: they must
            # persist verbatim) — they rejoin the tail in original order.
            keep_count = min(len(body), 4)
            tail_start = len(body) - keep_count
            dropped = body[:tail_start]
            to_summarize.extend(
                [m for m in dropped if not m.get("sticky")]
            )
            kept = (
                [m for m in dropped if m.get("sticky")]
                + body[tail_start:]
            )

        if not to_summarize:
            response = (
                "Nothing to compact: the session is already within the"
                " last two exchanges."
            )
            return self._compact_response(response, stream)

        tokens_before = self._count_tokens_in_history()
        summary, llm_topic = self._generate_conversation_summary(to_summarize)

        if summary:
            self.current_summary = summary

        # Fused session-topic from the summary pass: same discipline as
        # the background tasks — never clobber a pending update.
        if llm_topic:
            with self.session_topic_lock:
                if self.new_session_topic is None:
                    self.new_session_topic = llm_topic

        new_history = []
        if system_message is not None:
            new_history.append(system_message)
        new_history.extend(kept)
        self.chat_history = new_history

        tokens_after = self._count_tokens_in_history()
        summary_tokens = self.llm._get_token_count(summary, "user")
        logger.info(
            f"Manual compact: {len(to_summarize)} messages summarized,"
            f" {len(kept)} kept verbatim,"
            f" {tokens_before - tokens_after} tokens removed from history"
        )

        response = (
            f"Session compacted: {len(to_summarize)} messages condensed"
            f" into the conversation summary (~"
            f"{tokens_before - tokens_after} tokens freed, summary ~"
            f"{summary_tokens} tokens)."
        )
        return self._compact_response(response, stream)

    def _compact_response(
        self, response: str, stream: Optional[Literal["cli", "json"]]
    ):
        """Deliver a /compact result for all stream types."""
        if stream is None:
            return response

        def generator():
            if stream == "cli":
                print(response)
                return
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

    def _handle_test_user_ui_command(
        self, command: str, stream: Optional[Literal["cli", "json"]]
    ):
        """Handles the /testuserui command for all stream types."""
        if stream:  # cli or json
            return self._handle_test_user_ui_stream(command, stream)
        else:  # no stream
            parts = command.strip().split(" ", 2)
            usage_msg = "Usage: /testuserui <component_name> <json_data>"
            if len(parts) < 3:
                return usage_msg

            _command, component_name, data_json_str = parts
            component_path = f"/user_skills/components/{component_name}/index.html"
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

    def _handle_test_consent_stream(self, command: str, stream: str):
        """Handles streaming for the /testconsent command (issue #26 P2).

        Emits the exact consent_request signal the middleware emits at
        the mechanical trigger — but with a decision that is NOT
        registered in the ConsentRegistry. The card renders and the
        buttons work, yet any approval resolves against the real
        /consent/<decision_id> endpoint and comes back 'expired': the
        one-shot token validation is exercised fail-closed, and nothing
        can ever run off a fabricated card (the consent invariant,
        demonstrated live). A denial is answered 'denied' regardless —
        the user's act is the answer, and it fails closed by
        construction.
        """
        usage_msg = (
            "Usage: /testconsent — renders an inert consent card (any"
            " approval resolves as expired against the real endpoint;"
            " denials are always answered as denied)."
        )
        if stream != "json":
            print(usage_msg)
            return

        yield ndjson("signal", "loading", {"state": "start"})
        strings = self.orakle_middleware._offload_consent_strings()
        card = {
            "type": "consent_request",
            "decision_id": f"test_{uuid.uuid4().hex}",
            # Fabricated token: never registered, never resolvable.
            "token": "test-token-not-registered",
            "ttl": 600,
            # Generic decision surface, localized to the session
            # language. Quote is the mechanical estimate line (#37).
            "title": strings["title"],
            "quote": strings["estimate"].format(t=32074, c=4),
            "buttons": [
                {"id": "approve", "label": strings["yes"],
                 "style": "primary"},
                {"id": "deny", "label": strings["no"],
                 "style": "secondary"},
                {"id": "always_allow", "label": strings["always"],
                 "style": "ghost"},
            ],
            "note": strings["note"].format(m=10),
            "estimate": {
                "provider": config.get(
                    "llm.selected_provider", "test-provider"
                ),
                "payload_bytes": 48211,
                "est_input_tokens": 32074,
                "max_calls": 4,
            },
        }
        # Mirror the real turn's history marker (token never in history).
        self.llm.add_msg(
            f"\n_orakle_consent_card_|{card['decision_id']}\n",
            self.chat_history,
            "assistant",
        )
        yield ndjson("signal", "consent_request", card)
        yield ndjson("signal", "loading", {"state": "stop"})
        yield ndjson("signal", "completed", None)

    def _handle_test_consent_command(
        self, command: str, stream: Optional[Literal["cli", "json"]]
    ):
        """Handles the /testconsent command for all stream types."""
        return self._handle_test_consent_stream(command, stream)

    def _find_pending_consent_id(self) -> Optional[str]:
        """Latest consent-card marker in history whose decision is still
        pending in the middleware registry (#26 P2). Markers persist in
        history after resolution, so the registry — not the marker — is
        the source of truth; the scan just finds candidates newest-first.
        """
        if not self.chat_history:
            return None
        for msg in reversed(self.chat_history):
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", "")
            if "_orakle_consent_card_|" not in content:
                continue
            match = re.search(
                r"_orakle_consent_card_\|([A-Za-z0-9_]+)", content
            )
            if match and self.orakle_middleware.has_pending_consent(
                match.group(1)
            ):
                return match.group(1)
        return None

    def _handle_command(
        self, question: str, stream: Optional[Literal["cli", "json"]]
    ):
        """Checks for and handles special commands."""
        command = question.strip()
        if not command.startswith("/"):
            return None

        if command.lower() in ["/memory", "/nomemory"]:
            return self._handle_memory_command(command, stream)

        if command.lower() == "/compact":
            return self._handle_compact_command(command, stream)

        if command.lower().startswith("/testdocview"):
            return self._handle_test_doc_view_command(command, stream)

        if command.lower().startswith("/testnexus"):
            return self._handle_test_nexus_command(command, stream)

        if command.lower().startswith("/testuserui"):
            return self._handle_test_user_ui_command(command, stream)

        if command.lower().startswith("/testconsent"):
            return self._handle_test_consent_command(command, stream)

        if command.lower().startswith("/tts"):
            return self._handle_test_tts_command(command, stream)

        return None

    def _calculate_reasoning_level_heuristic(self, query: str) -> float:
        """
        Calculates a reasoning level based on linguistic analysis of the query using spaCy.
        This rule-based approach identifies linguistic features that suggest a need for
        reasoning, such as specific verbs, question structures, and comparative language.
        """
        # TEMP disable this heuristic in LiteLLM models
        # TODO(llm): re-enable for LiteLLM providers. The heuristic worked
        # well with Ollama (local models adapt effort to the query — great
        # speed/intelligence compromise). The LiteLLM side was disabled in
        # 2025-10 after providers rejecting `reasoning_effort` broke main
        # chat; the safe re-enable plan (get_supported_openai_params
        # preflight, client-side UnsupportedParamsError, per-call scoping)
        # is documented in the TODO block in llm/litellm.py chat().
        selected_provider_id = config.get("llm.selected_provider", "")
        if (
            not self.reasoning_heuristic_enabled
            or not selected_provider_id.startswith("ollama/")
        ):
            logger.info(
                "Skipping heuristic reasoning level calculation for provider"
                f" {selected_provider_id}"
            )
            return 0.0

        # Basic filter for very short queries that are unlikely to require reasoning
        if len(query.split()) <= 3:
            return 0.0

        doc = self.nlp(query.lower())
        score = 0.0

        # --- Define linguistic features and their weights ---
        # High-impact verbs that strongly suggest analysis, synthesis, or evaluation
        reasoning_verbs = {
            "analyze",
            "assess",
            "compare",
            "conduct",
            "contrast",
            "critique",
            "describe",
            "design",
            "develop",
            "differentiate",
            "evaluate",
            "explain",
            "find",
            "formulate",
            "investigate",
            "justify",
            "predict",
            "recommend",
            "suggest",
            "summarize",
            "synthesize",
            "write",
            "tell",
            "analysis",
            "scrutinize",
        }
        # Phrases that indicate hypothetical or causal reasoning
        hypothetical_phrases = [
            "what if",
            "what would",
            "what are",
            "what is",
            "would you",
        ]
        # Interrogatives that often require explanation
        explanatory_interrogatives = {"why", "how", "what"}

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
            score += 0.6
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
                    score += 0.4
                    logger.debug(
                        "Heuristic: Found non-root reasoning verb"
                        f" '{token.lemma_}' (+0.2)"
                    )
                    break

        # Rule 5: Check for comparatives/superlatives as a weaker signal
        has_comparative = any(tok.tag_ in ["JJR", "RBR"] for tok in doc)
        has_superlative = any(tok.tag_ in ["JJS", "RBS"] for tok in doc)
        if has_comparative or has_superlative:
            score += 0.20
            logger.debug("Heuristic: Found comparative/superlative (+0.15)")

        # --- Finalize heuristic value ---
        # Normalize score to be within [0, 1] and apply the configured max level
        heuristic_value = min(score, 1.0) * self.reasoning_max_level
        logger.info(
            f"Reasoning heuristic score: {score:.4f}, final value:"
            f" {heuristic_value:.4f}"
        )

        return heuristic_value

    def _process_thinking_markers(
        self, raw_stream: Generator[str, None, None]
    ) -> Generator[str, None, None]:
        """
        Processes a raw LLM stream to handle <think> blocks.

        It strips the content between <think> and </think> tags and replaces
        the tags themselves with special signal markers for the client.
        """
        buffer = ""
        in_thinking = False
        for chunk in raw_stream:
            if chunk is None:
                continue
            buffer += chunk
            while True:
                if not in_thinking:
                    start_pos = buffer.find("<think>")
                    if start_pos != -1:
                        yield buffer[:start_pos]
                        yield "\n_AINARA_THINKING_START_\n"
                        buffer = buffer[start_pos + len("<think>"):]
                        in_thinking = True
                    else:
                        yield buffer
                        buffer = ""
                        break
                if in_thinking:
                    end_pos = buffer.find("</think>")
                    if end_pos != -1:
                        yield "\n_AINARA_THINKING_STOP_\n"
                        buffer = buffer[end_pos + len("</think>"):]
                        in_thinking = False
                    else:
                        # Not enough data in buffer to find the end tag, wait for more chunks
                        break
        if buffer:
            yield buffer

    def _stream_and_process_with_guardrails(
        self,
        turn_chat_history: List[dict],
        reasoning_level_heuristic: float,
        memories: Optional[List[Dict]] = None,
    ) -> Generator[Union[str, dict, _GuardrailRetrySignal], None, None]:
        """
        Streams LLM response, checks for guardrail violations, and handles retries.

        This generator yields chunks of the response as they are generated. If a
        guardrail violation is detected, it yields a retry signal, stops the current
        stream, prepares for a retry, and continues the process.

        Args:
            turn_chat_history: The chat history for the current turn.
            reasoning_level_heuristic: The calculated reasoning level for the query.
            memories: Optional list of memory dictionaries for context

        Yields:
            Union[str, dict, _GuardrailRetrySignal]: Chunks of the processed LLM
            response, or a signal to indicate a retry is happening.
        """
        guardrail_retries = 0

        while guardrail_retries <= self.max_guardrail_retries:
            llm_response_stream = self.llm.chat(
                chat_history=turn_chat_history,
                stream=True,
                reasoning_level=reasoning_level_heuristic,
            )

            processed_stream = self._process_thinking_markers(
                llm_response_stream
            )

            stream_processor = self.orakle_middleware.process_stream(
                processed_stream,
                self.chat_history,
                reasoning_level_heuristic=reasoning_level_heuristic,
                current_language=self.current_language,
                memories=memories,
            )

            has_guardrail = False
            guardrail_message = ""

            for chunk in stream_processor:
                if (
                    isinstance(chunk, str)
                    and "[__AINARA_GUARDRAIL__]" in chunk
                ):
                    has_guardrail = True
                    guardrail_message += chunk
                    # Stop streaming to the client for this attempt
                    break
                else:
                    yield chunk

            if has_guardrail:
                guardrail_retries += 1
                logger.warning(
                    "Guardrail triggered (attempt"
                    f" {guardrail_retries}/{self.max_guardrail_retries}):"
                    f" {guardrail_message.strip()}"
                )

                if guardrail_retries > self.max_guardrail_retries:
                    logger.error("Max retries reached. Responding with error.")
                    error_message = guardrail_message.replace(
                        "[__AINARA_GUARDRAIL__]", ""
                    ).strip()
                    # Yield a final error message to the client
                    yield f"\n\nError: {error_message}\n\n"
                    break  # Exit retry loop
                else:
                    # Signal the caller that a retry is about to happen
                    yield _GuardrailRetrySignal()
                    # Add correction message for the next attempt and retry
                    self.llm.add_msg(
                        guardrail_message, turn_chat_history, "user"
                    )
                    continue  # Next attempt in the while loop
            else:
                # Success, no guardrail violation in this stream
                break  # Exit retry loop

        # Clean up any temporary guardrail messages from the main chat history
        # at the very end of all attempts.
        self.chat_history[:] = [
            msg
            for msg in self.chat_history
            if "[__AINARA_GUARDRAIL__]" not in msg.get("content", "")
        ]

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

        self.current_lang_code = config.get("stt.language", "en")
        self.current_language = languages.get(
            alpha_2=self.current_lang_code
        ).name or "English"
        logger.info("Will answer in language: " + self.current_language)

        # Handle legacy bool value for backward compatibility
        if isinstance(stream, bool):
            stream = "cli" if stream else None

        # --- Handle message flags ---
        save_to_memory = True
        is_sticky = False
        if "[__no_memory__]" in question:
            save_to_memory = False
            question = question.replace("[__no_memory__]", "").strip()
            logger.info("Message flagged with [__no_memory__].")

        if "[__sticky__]" in question:
            is_sticky = True
            question = question.replace("[__sticky__]", "").strip()
            logger.info("Message flagged with [__sticky__].")

        # Handle special commands
        command_response = self._handle_command(question, stream)
        if command_response is not None:
            # Delegate to the command's generator and then stop execution
            yield from command_response
            return

        # Calculate heuristic before any LLM call
        reasoning_level_heuristic = (
            self._calculate_reasoning_level_heuristic(question)
            if self.llm.thinking_available
            else 0
        )
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
            if self.memory_enabled and self.chat_memory and save_to_memory:
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
            if is_sticky:
                self.chat_history[-1]["sticky"] = True

            # --- Summary Update ---
            # Atomically check and apply any new summary
            if self.summary_enabled:
                with self.buffer_lock:  # Use the existing lock for consistency
                    if self.new_summary:
                        self.current_summary = self.new_summary
                        self.new_summary = (  # Clear it while holding the lock
                            "-"
                        )
                        logger.info("Retrieved new summary for application")

            # --- Session Topic (dynamic, updated by background thread) ---
            # Atomically apply the latest background-detected topic, then
            # age the current one: without fresh confirmation it decays so
            # stale topics stop boosting memory retrieval.
            with self.session_topic_lock:
                if self.new_session_topic:
                    self.current_session_topic = self.new_session_topic
                    self.new_session_topic = None
                    self.session_topic_age = 0
                    logger.info(
                        "Applied new session topic:"
                        f" {self.current_session_topic}"
                    )
                elif self.current_session_topic:
                    self.session_topic_age += 1
                    if self.session_topic_age > self.session_topic_max_age:
                        logger.info(
                            "Session topic expired after"
                            f" {self.session_topic_age} turns:"
                            f" {self.current_session_topic}"
                        )
                        self.current_session_topic = None
                        self.session_topic_age = 0

            # ============================================================
            # PHASE 1: Build system_hint_content (per-turn dynamic content)
            # ============================================================
            # Only content that changes per turn goes here. Static-per-
            # session content (user_profile_summary, recent_memories_summary,
            # last_chat_timestamp) is in the system prompt template.

            system_hint_content = ""

            # --- Skills Names Hint (compact per-turn enforcement) ---
            # TODO Apparently a good idea, but seems to confuse smaller models
            # if self.skills_hint_text:
            #     system_hint_content += (
            #         "These ORAKLE capabilities are available:"
            #         f" {self.skills_hint_text}. If the user query can be"
            #         " fulfilled using them, you must use the"
            #         " <orakle>full query intent</orakle>"
            #     )
            #     if self.first_turn:
            #         self.first_turn = False
            #         logger.info("SKILLS HINT injected (first turn)")

            # --- Conversation Summary (dynamic, updated by background
            # thread or the manual /compact command) ---
            # Injected whenever a summary exists, regardless of
            # summary_enabled: that flag gates the AUTOMATIC path only.
            if self.current_summary and self.current_summary != "-":
                system_hint_content += (
                    f"\n\n--- Conversation Summary ---\n"
                    f"{self.current_summary}"
                )

            # --- Context Memories (dynamic per turn) ---
            self.processed_memories_for_template = None
            if self.memory_enabled and self.green_memories:
                # Build search query from recent turns for semantic search.
                # Only enough turns for reference resolution: the session
                # topic carries the conversational continuity now.
                history_for_search = self.prepare_chat_history_for_skill()[
                    -(self.search_history_exchanges * 2):
                ]

                search_context_parts = []
                if self.current_summary and self.current_summary != "-":
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

                relevant_memories = self.green_memories.get_relevant_memories(
                    search_context,
                    session_topic=self.current_session_topic,
                )

                if relevant_memories:
                    # Pre-process memories to format the relevance score
                    self.processed_memories_for_template = []
                    for mem in relevant_memories:
                        processed_mem = mem.copy()
                        processed_mem["relevance_score"] = (
                            f"{processed_mem.get('relevance', 0.0):.2f}"
                        )
                        self.processed_memories_for_template.append(
                            processed_mem
                        )

                    logger.info(
                        "Injecting"
                        f" {len(self.processed_memories_for_template)}"
                        " dynamically retrieved memories into hint."
                    )
                    context_memories_prompt = self.template_manager.render(
                        "framework.chat_manager.user_memories_prompt",
                        {"memories": self.processed_memories_for_template},
                    )
                    system_hint_content += f"\n\n{context_memories_prompt}"
                else:
                    logger.info("No relevant memories found for this turn.")

            # --- Notifications (dynamic, fire-and-forget) ---
            notifications_snapshot = ""
            if (
                self.app
                and hasattr(self.app, "notification_manager")
                and self.notifications_enabled
                and self.notifications_prompt
            ):
                with self.notifications_lock:
                    notifications_snapshot = self.notifications_prompt
                    self.notifications_prompt = ""

                if notifications_snapshot:
                    logger.info(
                        "Injecting notifications into system hint"
                    )
                    system_hint_content += (
                        "\n\nIMPORTANT: The following are system"
                        " notifications that just arrived. They are NOT"
                        " part of the user's message above, report to the"
                        " user only those deserving important attention."
                        " Instructions: Notify the user just once about a"
                        " particular event.\n"
                        f"NOTIFICATIONS:\n{notifications_snapshot}"
                    )

            # --- ORAKLE Policy Guardrail (persistent after first violation) ---
            if self._orakle_trailing_text_violation:
                system_hint_content += (
                    "\n\nORAKLE POLICY REMINDER: In a previous turn, you"
                    " generated text after an Orakle query which was"
                    " discarded. Per policy, do not output any additional"
                    " text after orakle tags. All content after the last"
                    " closing </orakle> tag is ignored. Do not generate"
                    " explanations, summaries, or any other text after"
                    " your Orakle commands."
                )

            # --- Pending consent card (#26 P2 conversational close) ---
            # The last unanswered consent marker in history + a live
            # registry entry mean the card is still on screen. The model
            # must know the authorization rules: only the tap authorizes,
            # voice agreement is refused politely, and decline/defer/
            # change-of-subject closes the card via the mechanical tag
            # (the model proposes the close; the framework executes it
            # and kills the token server-side).
            pending_consent_id = self._find_pending_consent_id()
            if pending_consent_id:
                system_hint_content += (
                    "\n\nPENDING CONFIRMATION CARD: A confirmation card is"
                    " on screen (offer id: "
                    f"{pending_consent_id}) asking the user to authorize a"
                    " paid multi-step analysis. Authorization rules: ONLY"
                    " a tap on the card's button authorizes it — a spoken"
                    " or typed yes/agreement carries NO authority and must"
                    " never be treated as approval. If the user agrees or"
                    " tells you to go ahead, warmly insist that they tap"
                    " the confirmation button on the screen (you cannot"
                    " accept it by voice). If the user declines, defers it"
                    " (\"later\", \"not now\"), or clearly moves on to"
                    " something else, respond naturally and then close the"
                    " card by outputting exactly <consent_close>"
                    f"{pending_consent_id}</consent_close> as the very last"
                    " thing in your response."
                )

            # Wrap in <system_hint> tags if there's any content
            if system_hint_content.strip():
                system_hint_content = (
                    f"\n\n<system_hint>{system_hint_content}"
                    "\n</system_hint>"
                )

            # ============================================================
            # PHASE 2: Trim context with reserved budget for the hint
            # ============================================================
            hint_token_count = 0
            if system_hint_content:
                hint_token_count = self.llm._get_token_count(
                    system_hint_content, "user"
                )
                logger.info(
                    f"System hint will use {hint_token_count} tokens"
                )

            self.trim_context(reserved_tokens=hint_token_count)

            # ============================================================
            # PHASE 3: Build shadow copy and inject the hint
            # ============================================================
            shadow_history = copy.deepcopy(self.chat_history)

            if system_hint_content:
                if (
                    shadow_history
                    and shadow_history[-1]["role"] == "user"
                ):
                    shadow_history[-1]["content"] += system_hint_content
                    shadow_history[-1]["tokens"] = (
                        self.llm._get_token_count(
                            shadow_history[-1]["content"], "user"
                        )
                    )
                else:
                    logger.warning(
                        "Unexpected conversation format: last message is"
                        " not from user, injecting hint in system prompt"
                    )
                    shadow_history[0]["content"] += system_hint_content

            # Now, process and stream the final response (successful or error)
            processed_answer = ""
            text_buffer = ""
            parsing_mode = "text"
            doc_buffer = ""
            doc_format = "plaintext"

            stream_generator = self._stream_and_process_with_guardrails(
                shadow_history,
                reasoning_level_heuristic,
                memories=self.processed_memories_for_template,
            )

            for chunk in stream_generator:
                if isinstance(chunk, _GuardrailRetrySignal):
                    # Reset buffers for the retry. The client will see a pause,
                    # then new content will start streaming in.
                    processed_answer = ""
                    text_buffer = ""
                    parsing_mode = "text"
                    doc_buffer = ""
                    doc_format = "plaintext"
                    continue
                # for chunk in final_chunks:
                # # --- TOKEN DEBUG
                # logger.info(f"Chunk from Orakle Middleware: {repr(chunk)}")
                if "_AINARA_THINKING_START_" in chunk:
                    yield ndjson("signal", "thinking", {"state": "start"})
                    continue
                if "_AINARA_THINKING_STOP_" in chunk:
                    yield ndjson("signal", "thinking", {"state": "stop"})
                    continue
                if "_orakle_trailing_text_discarded_" in chunk:
                    self._orakle_trailing_text_violation = True
                    logger.info(
                        "ORAKLE POLICY: Trailing text violation detected,"
                        " hint will be injected in subsequent turns."
                    )
                    continue

                if (
                    isinstance(chunk, dict)
                    and chunk.get("type") == "consent_request"
                ):
                    # Consent card (#26 P2; #18 confirmation primitive
                    # pilot): the framework-rendered decision surface for
                    # the offload spend axis. The decision token rides
                    # only the signal channel to Polaris — history keeps
                    # a redacted decision-id marker so the model can
                    # never see, replay or fabricate the token.
                    yield ndjson("signal", "consent_request", chunk)
                    processed_answer += (
                        "\n_orakle_consent_card_|"
                        f"{chunk.get('decision_id', '')}\n"
                    )
                    continue

                if (
                    isinstance(chunk, dict)
                    and chunk.get("type") == "nexus_skill_result"
                ):
                    vendor = chunk.get("vendor")
                    bundle = chunk.get("bundle")
                    component = chunk.get("component")
                    query = chunk.get("query")
                    mode = chunk.get("mode", "view")
                    skill_data = chunk.get("data", {})

                    if not component:
                        logger.error(
                            "Nexus skill result received with incomplete"
                            f" component info: vendor='{vendor}',"
                            f" bundle='{bundle}', component='{component}'"
                        )
                        continue

                    if vendor and bundle:
                        component_path = (
                            f"/nexus/{vendor}/{bundle}/{component}/index.html"
                        )
                    else:
                        # User skills don't have vendor/bundle, use the user skills path
                        component_path = (
                            f"/user_skills/components/{component}/index.html"
                        )

                    # Panel identity (#30, docs/proposals/nexus-panel-mode.md
                    # §5): computed here once, vendor-agnostic — the frontend
                    # never re-derives it by path-splitting. Panels are
                    # singletons (component_path); views get one instance per
                    # skill-declared instance key, falling back to the query.
                    if mode == "panel":
                        panel_id = component_path
                    else:
                        instance_key = None
                        if isinstance(skill_data, dict):
                            instance_key = skill_data.pop(
                                "instance_key", None
                            )
                        if not instance_key:
                            instance_key = query or component
                        panel_id = f"{component_path}#{instance_key}"

                    # Lifecycle verb (#30): the skill asked to close its own
                    # panel. Nothing is rendered and no payload is inlined
                    # into the history — the interpretation text below is
                    # the conversation's record of the exchange.
                    if chunk.get("close"):
                        yield ndjson(
                            "ui",
                            "closeNexus",
                            {"panel_id": panel_id},
                        )
                        continue

                    nexus_data = {
                        "component_path": component_path,
                        "query": query,
                        "mode": mode,
                        "panel_id": panel_id,
                    }
                    if chunk.get("data_ref"):
                        # Render inline ceiling (#26 P2, §6.8): payload
                        # stored as a persistent render blob — the
                        # transcript carries the reference plus a small
                        # preview; Polaris hydrates by id at render
                        # time. ChatMemory never holds payload bytes.
                        nexus_data["data_ref"] = chunk["data_ref"]
                        nexus_data["preview"] = chunk.get("preview", "")
                    else:
                        nexus_data["data"] = skill_data

                    # Create a descriptive message for the chat history
                    history_message = (
                        f"_orakle_nexus_data_|{json.dumps(nexus_data)}"
                    )
                    processed_answer += f"\n{history_message}\n"

                    yield ndjson("ui", "renderNexus", nexus_data)
                    continue

                if not chunk:
                    continue

                # Run-journal progress relay (#26/#35): forward as a
                # signal event BEFORE the buffer machinery — the sentence
                # batching would delay, merge or swallow it, and the
                # marker must never reach the persisted answer or TTS.
                # The segment path (_stream_system_segment) has the same
                # interception; this is the main-flow counterpart.
                if (
                    isinstance(chunk, str)
                    and "_orakle_agent_progress_" in chunk
                ):
                    yield from self._process_streaming_sentence(
                        chunk.strip(), stream
                    )
                    continue

                # Agent report trail (#35): mechanical record — persisted
                # in the transcript, never streamed live, never spoken,
                # never routed through the doc-fence machinery (the body
                # is fenced and would otherwise flip the parse mode and
                # render the report as a document). Polaris renders it
                # from history after the turn, like the digest trail.
                if (
                    isinstance(chunk, str)
                    and "_orakle_agent_dossier_" in chunk
                ):
                    processed_answer += chunk
                    continue

                # Digest trail records (offload digestion and skill-side
                # analysis alike, one unified marker): mechanical record
                # — never streamed live, never spoken, never routed
                # through the doc-fence machinery; Polaris renders it
                # from history after the turn, like the other trail
                # records. Persisted wholesale (same doctrine as the
                # offload digest trail): Polaris renders trail records
                # from the persisted store, so without the body the
                # record would be a pill forever; GREEN's dedup absorbs
                # any derivative re-assimilation.
                if (
                    isinstance(chunk, str)
                    and "_orakle_offload_digest_" in chunk
                ):
                    processed_answer += chunk
                    continue

                processed_answer += chunk

                # Route chunk to the correct buffer based on current parsing mode
                if parsing_mode == "doc":
                    doc_buffer += chunk
                else:
                    text_buffer += chunk

                # --- Conversational consent close (#26 P2) ---
                # The model proposed dismissing the pending card via
                # <consent_close>id</consent_close> (instructed by the
                # pending-card hint). Strip the tag before it can reach
                # TTS or the doc/sentence machinery, invalidate the token
                # server-side (a closed card is a dead offer), and signal
                # Polaris to dissolve the card. The tag can straddle
                # chunks, hence the scan on the accumulated buffer.
                if parsing_mode == "text" and "<consent_close>" in (
                    text_buffer
                ):
                    close_match = re.search(
                        r"<consent_close>([A-Za-z0-9_]+)"
                        r"</consent_close>",
                        text_buffer,
                    )
                    if close_match:
                        decision_id = close_match.group(1)
                        text_buffer = (
                            text_buffer[: close_match.start()]
                            + text_buffer[close_match.end():]
                        )
                        processed_answer = re.sub(
                            r"\s*<consent_close>[A-Za-z0-9_]+"
                            r"</consent_close>",
                            "",
                            processed_answer,
                        )
                        self.orakle_middleware.invalidate_offload_consent(
                            decision_id
                        )
                        yield ndjson(
                            "signal",
                            "consent_closed",
                            {"decision_id": decision_id},
                        )

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
                # Log assistant response to chat memory.
                if self.memory_enabled and self.chat_memory and save_to_memory:
                    self.chat_memory.add_entry(processed_answer, "assistant")
            else:
                # If there's no processed answer, add a placeholder
                yield ndjson(
                    "signal", "error", {"message": "LLM is not answering"}
                )
                logger.warning("No answer from the LLM")
                self.llm.add_msg("-", self.chat_history, "assistant")
                if self.memory_enabled and self.chat_memory and save_to_memory:
                    self.chat_memory.add_entry("-", "assistant")

            # Stop loading animation
            if stream == "cli":
                loading.stop()
            elif stream == "json":
                yield ndjson("signal", "loading", {"state": "stop"})
                yield ndjson("signal", "completed", None)

            # Trigger background summary generation
            if self.summary_enabled:
                self._update_summary_in_background()

            if self.notifications_enabled:
                self._update_notifications_in_background()

            # Trigger background session-topic detection (runs every turn;
            # cheap embedding inference while the user composes the next one)
            self._update_session_topic_in_background()

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

    def _fetch_interpretation_memories(self, query: str):
        """Relevant GREEN memories for an out-of-band interpretation
        pass (#37) — the same dynamic retrieval the user-turn path
        performs, seeded with the offloaded query plus the recent
        history for reference resolution."""
        if not (self.memory_enabled and self.green_memories):
            return None
        history_tail = self.chat_history[-10:] if self.chat_history else []
        parts = [
            f"{m.get('role')}: {m.get('content', '')}"
            for m in history_tail
            if m.get("role") in ("user", "assistant")
        ]
        parts.append(query)
        relevant = self.green_memories.get_relevant_memories(
            "\n\n".join(parts),
            session_topic=self.current_session_topic,
        )
        if not relevant:
            return None
        processed = []
        for mem in relevant:
            mem_copy = mem.copy()
            mem_copy["relevance_score"] = (
                f"{mem_copy.get('relevance', 0.0):.2f}"
            )
            processed.append(mem_copy)
        return processed

    def consent_resume(
        self, decision_id: str, token: str, decision: str
    ) -> Generator[str, None, None]:
        """Stream the out-of-band digestion segment for an approved
        consent-card decision (issue #26 P2).

        Runs entirely outside the user-turn flow: the original turn
        already ended with the card. The middleware validates the one-shot
        decision token (an unknown, replayed or expired decision yields an
        'expired' consent_result signal — never an execution) and returns
        the segment stream: the digestion runs out-of-band, and the
        digest routes through the interpretation machinery (#37) so the
        spoken answer is an in-conversation delivery derived from the
        analysis — never the raw digest.
        """
        digest_stream = self.orakle_middleware.resume_offload_consent(
            decision_id,
            token,
            decision,
            memories_provider=self._fetch_interpretation_memories,
        )
        if digest_stream is None:
            yield ndjson(
                "signal",
                "consent_result",
                {"status": "expired", "decision_id": decision_id},
            )
            return
        logger.info(
            "CHAT: streaming approved offload digestion segment for"
            " decision %s.",
            decision_id,
        )
        yield ndjson(
            "signal",
            "consent_result",
            {"status": "approved", "decision_id": decision_id},
        )

        # Mechanical decision record (#26 P2) rides the segment: it
        # lands in the same history/memory entry as the digest it
        # authorized — one permanent trail: offer → decision → digest.
        # _stream_system_segment persists it but never speaks it.
        record = f"\n_orakle_consent_decision_|{decision_id}|approved\n\n"

        def _with_record():
            yield record
            yield from digest_stream

        yield from self._stream_system_segment(_with_record())

    def consent_denial_segment(
        self, decision_id: str, decision: str, entry: dict
    ) -> Generator[str, None, None]:
        """Stream the conversational outcome segment for a consumed
        deny decision (issue #37).

        The conversational layer of the offload path lives at the
        decision OUTCOME: the mechanical decision record is persisted
        separately (by the endpoint, before this segment starts — it
        must survive a client that never reads the stream), and the
        spoken layer is a free, bounded feedback comment — the model
        reacting to the outcome, never participating in the decision
        surface. Called only for 'deny'; 'dismiss' (Escape,
        put-it-away) stays silent: the user did not answer, commenting
        would be chatter.

        Failure posture (ratified): any feedback-generation failure —
        429, timeout, empty output — closes the segment silently. The
        record is already persisted, the card is already resolved in
        the UI, and silence after a decline is a normal conversational
        outcome. One attempt, no retries: the user just declined
        spend; burning retries on a nicety would be tone-deaf.

        `entry` is the snapshot returned by the middleware's
        deny_offload_consent (query, payload size, chat history) — the
        untrusted payload itself never enters the comment prompt.
        """
        def _segment():
            feedback = self.orakle_middleware.denial_feedback_text(
                query=entry.get("query", ""),
                payload_bytes=entry.get("payload_bytes", 0),
                chat_history=entry.get("chat_history"),
                memories=self._fetch_interpretation_memories(
                    entry.get("query", "")
                ),
            )
            if feedback:
                yield feedback

        yield from self._stream_system_segment(_segment())

    def record_consent_decision(self, decision_id: str, outcome: str) -> None:
        """Persist a consent-card decision as a mechanical record (issue
        #26 P2). Called by the PyBridge consent endpoint after a one-shot
        decision was actually consumed — never for unknown/expired tokens
        (a card that quietly died leaves no record: walked away).

        The marker entry gives the conversation a permanent account of
        the user's mechanical act and its outcome — the model channel
        can read it (the static prompt carries the key) but can never
        fabricate it (guardrail: the marker is a forbidden signal).
        Never TTS'd: it is a record, not an utterance.
        """
        marker = f"\n_orakle_consent_decision_|{decision_id}|{outcome}\n"
        self.llm.add_msg(marker, self.chat_history, "assistant")
        if self.memory_enabled and self.chat_memory:
            self.chat_memory.add_entry(marker, "assistant")
        logger.info(
            "CHAT: consent decision %s recorded as '%s'.",
            decision_id,
            outcome,
        )

    def _stream_system_segment(
        self, chunks: Generator, stream: Literal["cli", "json"] = "json"
    ) -> Generator[str, None, None]:
        """Stream a system-initiated answer segment (issue #26 P2).

        A focused version of chat_completion's output machinery for
        segments that start outside a user turn: same sentence/TTS
        batching and doc-fence state machine, but no user-turn handling
        and no guardrail loop (the segment's source is the framework's
        own digestion path, not a model channel). Run-journal progress
        chunks become signal events and are kept out of the persisted
        text. The accumulated text becomes the segment's assistant entry
        in history and chat memory.
        """
        yield ndjson("signal", "loading", {"state": "start"})
        processed_answer = ""
        text_buffer = ""
        doc_buffer = ""
        parsing_mode = "text"
        doc_format = "plaintext"

        try:
            for chunk in chunks:
                if not chunk:
                    continue
                if (
                    "_orakle_consent_decision_" in chunk
                    or "_orakle_offload_digest_" in chunk
                    or "_orakle_status_" in chunk
                    or "_orakle_agent_dossier_" in chunk
                ):
                    # Mechanical records (#26 P2 / #37 / #35): the consent
                    # decision, the offload digest, the status pills and
                    # the agent report trail ride the segment's transcript
                    # but are never spoken — they are records, not
                    # utterances.
                    processed_answer += chunk
                    continue
                if "_orakle_agent_progress_" in chunk or (
                    "_orakle_loading_signal_" in chunk
                ):
                    # Run-journal progress / loading signals: forwarded
                    # as signal events, never persisted as answer text.
                    yield from self._process_streaming_sentence(
                        chunk.strip(), stream
                    )
                    continue
                processed_answer += chunk

                # Route chunk to the correct buffer based on current
                # parsing mode (same state machine as chat_completion).
                if parsing_mode == "doc":
                    doc_buffer += chunk
                else:
                    text_buffer += chunk

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
                                    {
                                        "view": "document",
                                        "format": doc_format,
                                    },
                                )
                            parsing_mode = "doc"
                            doc_buffer = text_buffer[doc_start_match.end():]
                            text_buffer = ""
                            state_changed = True
                    elif parsing_mode == "doc":
                        doc_end_match = re.search(r"```", doc_buffer)
                        if doc_end_match:
                            doc_content = doc_buffer[
                                : doc_end_match.start()
                            ]
                            if stream == "json":
                                yield ndjson(
                                    "content",
                                    "full",
                                    {"content": doc_content},
                                )
                            parsing_mode = "text"
                            text_buffer = doc_buffer[doc_end_match.end():]
                            doc_buffer = ""
                            state_changed = True
                    if not state_changed:
                        break

                if parsing_mode == "text" and text_buffer:
                    sentences = self._extract_complete_sentences(text_buffer)
                    if sentences:
                        if stream == "json":
                            yield ndjson(
                                "signal", "loading", {"state": "stop"}
                            )
                        for sentence in sentences:
                            yield from self._process_streaming_sentence(
                                sentence, stream
                            )
                        last_sentence = sentences[-1]
                        last_pos = (
                            text_buffer.rfind(last_sentence)
                            + len(last_sentence)
                        )
                        text_buffer = text_buffer[last_pos:].strip()

            if text_buffer.strip():
                yield from self._process_regular_text(text_buffer, stream)
        except Exception as e:
            logger.error(f"Error streaming system segment: {e}")
            if stream == "json":
                yield ndjson("signal", "error", {"message": str(e)})
            processed_answer = f"Error: {str(e)}"
        finally:
            if processed_answer.strip():
                self.llm.add_msg(
                    processed_answer, self.chat_history, "assistant"
                )
                if self.memory_enabled and self.chat_memory:
                    self.chat_memory.add_entry(processed_answer, "assistant")
            else:
                logger.warning("System segment produced no answer")
                self.llm.add_msg("-", self.chat_history, "assistant")
            if stream == "json":
                yield ndjson("signal", "loading", {"state": "stop"})
                yield ndjson("signal", "completed", None)

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
