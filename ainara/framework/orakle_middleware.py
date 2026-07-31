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
import logging
import os
import re
import time
from typing import Dict, Generator, List, Optional, Union

import requests

from ainara.framework.config import ConfigManager
from ainara.framework.llm import create_llm_backend
from ainara.framework.matcher.transformers import OrakleMatcherTransformers
from ainara.framework.orakle_client import call_skill
from ainara.framework.system_skills.base import BaseSystemSkill
from ainara.framework.template_manager import TemplateManager

# from ainara.framework.utils import format_orakle_command

logger = logging.getLogger(__name__)


class OrakleCapabilityFetcher:
    """Utility class to fetch and process capabilities from Orakle servers."""

    def __init__(self, orakle_servers: List[str]):
        self.orakle_servers = orakle_servers

    def fetch_capabilities(self) -> List[dict]:
        """Query Orakle servers for capabilities and store them in structured format."""
        capabilities = []
        max_attempts = 10
        attempts = 0

        while not capabilities:
            for server in self.orakle_servers:
                try:
                    response = requests.get(
                        f"{server}/capabilities", timeout=2
                    )
                    if response.status_code == 200:
                        raw_capabilities = response.json()
                        capabilities = self._process_orakle_skills(
                            raw_capabilities
                        )
                        if capabilities:
                            logger.info(
                                f"Successfully loaded {len(capabilities)}"
                                f" skills from Orakle server: {server}"
                            )
                            return capabilities
                        else:
                            attempts += 1
                            if attempts > max_attempts:
                                logger.warning(
                                    "Max attempts reached. No Orakle"
                                    " capabilities found."
                                )
                                return []
                            time.sleep(2)
                except requests.RequestException as e:
                    time.sleep(2)
                    logger.warning(
                        f"Failed to connect to Orakle server {server}:"
                        f" {str(e)}"
                    )
                    attempts += 1
                    if attempts > max_attempts:
                        logger.warning(
                            "Max attempts reached. No Orakle capabilities"
                            " found."
                        )
                        return []
                    continue

        if self.orakle_servers:
            logger.warning(
                "No Orakle capabilities found, is the Orakle server running?"
            )
        return capabilities

    def _process_orakle_skills(self, raw_capabilities: dict) -> List[dict]:
        """Process raw skill capabilities into structured format."""
        skills = []
        for skill_name, skill_info in raw_capabilities.items():
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
                "full_description": (
                    skill_info.get("run", {}).get(
                        "docstring", skill_info.get("description", "")
                    )
                ),
                "embeddings_boost_factor": skill_info.get(
                    "embeddings_boost_factor", 1.0
                ),
                "type": skill_info.get("type"),
                "ui": skill_info.get("ui"),
                "vendor": skill_info.get("vendor"),
                "bundle": skill_info.get("bundle"),
                "parameters": [],
            }

            if skill_data["run_info"].get("parameters"):
                for param_name, param_info in (
                    skill_data["run_info"].get("parameters", {}).items()
                ):
                    skill_data["parameters"].append(
                        {
                            "name": param_name,
                            "type": param_info.get("type", "any"),
                            "description": param_info.get("description", ""),
                        }
                    )

            skills.append(skill_data)
        return skills


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
        system_message: Optional[str] = None,
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
        self.system_message = system_message or ""
        self.template_manager = TemplateManager()
        self.config_manager = config_manager or ConfigManager()
        self.current_language = None
        self._match_llm_cache = {}
        self._blacklisted_match_providers = set()

        # --- Matcher Configuration ---
        # Use transformer matcher
        matcher_model = self.config_manager.get(
            "orakle.matcher.model",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )
        self.matcher = OrakleMatcherTransformers(model_name=matcher_model)
        # Get threshold and top_k from config or use defaults
        self.matcher_threshold = self.config_manager.get(
            "orakle.matcher.threshold", 0.0001
        )
        self.matcher_top_k = self.config_manager.get(
            "orakle.matcher.top_k", 10
        )
        self.reasoning_effort_limit = self.config_manager.get(
            "orakle.reasoning_effort_limit", 1.0
        )
        self.enable_agent_spawn = self.config_manager.get(
            "orakle.enable_agent_spawn", False
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
        if capabilities is not None:
            self.capabilities = capabilities
        else:
            fetcher = OrakleCapabilityFetcher(self.orakle_servers)
            self.capabilities = fetcher.fetch_capabilities()

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
                    "embeddings_boost_factor": skill.get(
                        "embeddings_boost_factor", 1.0
                    ),
                },
            )

        # logger.info("-----------------")
        # logger.info(pprint.pformat(skill))

    def _get_correction_message(self) -> str:
        """Returns a guardrail message for malformed orakle tags."""
        logger.info("GUARDRAIL correction message generated")
        return (
            "\n\n[__AINARA_GUARDRAIL__] Error: Malformed orakle tag detected."
            " Use the format: <orakle>your query here</orakle>. The tag must"
            " be properly closed. Please try again with the correct"
            " format.\n\n"
        )

    def _get_typo_correction_message(self, wrong_tag: str) -> str:
        """Returns a guardrail message for misspelled orakle tags."""
        logger.info(f"GUARDRAIL typo correction generated for: {wrong_tag}")
        return (
            "\n\n[__AINARA_GUARDRAIL__] Error: Invalid tag detected. You used"
            f" '{wrong_tag}' but the correct tag is 'orakle'. Please retry"
            " using <orakle>your query</orakle>.\n\n"
        )

    def _get_unclosed_tag_message(self) -> str:
        """Returns a guardrail message for unclosed orakle tags."""
        logger.info("GUARDRAIL unclosed tag message generated")
        return (
            "\n\n[__AINARA_GUARDRAIL__] Error: Unclosed orakle tag detected."
            " You opened <orakle> but did not close it with </orakle>."
            " Please try again with a properly closed tag.\n\n"
        )

    def _get_attribute_rejection_message(self) -> str:
        """Returns a guardrail message for orakle tags with invalid attributes."""
        logger.info("GUARDRAIL invalid attribute rejection message generated")
        return (
            "\n\n[__AINARA_GUARDRAIL__] Error: Orakle tags only accept the"
            " 'query' attribute. Use the format:"
            ' <orakle query="your intent">your data</orakle> or'
            " <orakle>your query</orakle>."
            " Please try again with the correct format.\n\n"
        )

    def _get_self_closing_rejection_message(self) -> str:
        """Returns a guardrail message for self-closing orakle tags."""
        logger.info("GUARDRAIL self-closing rejection message generated")
        return (
            "\n\n[__AINARA_GUARDRAIL__] Error: Self-closing orakle tags are"
            " not allowed. Use the format: <orakle>your query here</orakle>."
            " Please try again with a properly opened and closed tag.\n\n"
        )

    def _get_nested_tags_rejection_message(self) -> str:
        """Returns a guardrail message for nested orakle tags."""
        logger.info("GUARDRAIL nested tags rejection message generated")
        return (
            "\n\n[__AINARA_GUARDRAIL__] Error: Nested orakle tags are not"
            " allowed. Use only one <orakle>query</orakle> at a time."
            " Please try again without nesting tags.\n\n"
        )

    def _normalize_query_content(self, content: str) -> str:
        """Normalize query content by collapsing whitespace and newlines."""
        normalized = re.sub(r"\s+", " ", content)
        return normalized.strip()

    def _check_for_invalid_attributes(self, text: str) -> bool:
        """Check if any orakle tag contains attributes other than 'query'.

        Returns True if invalid attributes are detected.
        """
        # Match <orakle with attributes
        attr_pattern = r"<orakle\s+([^>]*)>"
        for match in re.finditer(attr_pattern, text, re.IGNORECASE):
            attrs_str = match.group(1)
            # Strip a trailing / in case of self-closing (handled elsewhere)
            attrs_str = attrs_str.rstrip("/")
            if not attrs_str:
                continue
            # Allow only query="..." or query='...'
            # After removing a valid query attribute, nothing should remain
            cleaned = re.sub(r"""query\s*=\s*(['"])(.*?)\1""", "", attrs_str)
            if cleaned.strip():
                return True
        return False

    def _check_for_self_closing(self, text: str) -> bool:
        """Check for self-closing orakle tags.

        Returns True if self-closing syntax is detected.
        """
        # Match <orakle/> or <orakle .../>
        pattern = r"<orakle[^>]*/>"
        return bool(re.search(pattern, text, re.IGNORECASE))

    def _has_potential_tag(self, text: str) -> bool:
        """Check if text contains a full or partial opening tag."""
        text_lower = text.lower()
        if "<orakle" in text_lower:
            return True
        # Check for unclosed '<' near the end of the buffer
        last_open = text.rfind("<")
        if last_open != -1 and text.find(">", last_open) == -1:
            # Only consider it a potential tag if the characters after '<'
            # match the start of 'orakle' (case-insensitive)
            after_open = text[last_open + 1:].lower()
            if after_open == "":
                return True
            keyword = "orakle"
            # Check if after_open starts with 'orakle', an slice of it, or is empty
            while True:
                if keyword == "":
                    break
                if after_open == keyword:
                    return True
                keyword = keyword[:-1]
        return False

    def _check_for_nested_tags(self, text: str) -> bool:
        """Check for nested orakle tags.

        Returns True if nested tags are detected.
        """
        # Find all opening tags
        open_pattern = r"<orakle(?:\s[^>]*)?>"
        opens = list(re.finditer(open_pattern, text, re.IGNORECASE))

        if len(opens) < 2:
            return False

        # Find all closing tags
        close_pattern = r"</orakle>"
        closes = list(re.finditer(close_pattern, text, re.IGNORECASE))

        # Check if second open comes before first close
        if len(closes) >= 1:
            if opens[1].start() < closes[0].start():
                return True

        return False

    def update_llm(self, llm):
        self.llm = llm

    def _check_for_typo_tags(self, text: str) -> Optional[str]:
        """Check for common typo variants of orakle tags.

        Returns the typo tag name if found, None otherwise.
        """
        typo_patterns = [
            r"<(oracle)[^>]*>",
            r"<(oragle)[^>]*>",
            r"</(oracle)>",
            r"</(oragle)>",
        ]
        for pattern in typo_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _extract_orakle_tags(self, text: str) -> tuple[
        List[tuple[int, int, str, Optional[str]]],
        bool,
        Optional[str],
        Optional[str],
    ]:
        """Extract all valid orakle tags from text.

        Returns:
            - List of tuples (start_pos, end_pos, intent, data)
              intent: the query for the matcher (from query attr or tag content)
              data: the tag content when query attr is present, None otherwise
            - Boolean indicating if there's an unclosed tag
            - Typo tag name if found, None otherwise
            - Guardrail type if violation detected ('attribute', 'self_closing', 'nested'), None otherwise
        """
        # First check for typos
        typo = self._check_for_typo_tags(text)
        if typo:
            return [], False, typo, None

        # Check for self-closing tags
        if self._check_for_self_closing(text):
            return [], False, None, "self_closing"

        # Check for invalid attributes (anything other than query)
        if self._check_for_invalid_attributes(text):
            return [], False, None, "attribute"

        # Check for nested tags
        if self._check_for_nested_tags(text):
            return [], False, None, "nested"

        tags = []

        # Pattern for <orakle query="...">...</orakle> (with query attribute)
        attr_pattern = (
            r"""<orakle\s+query\s*=\s*(['"])(.*?)\1\s*>(.*?)</orakle>"""
        )
        for match in re.finditer(
            attr_pattern, text, re.IGNORECASE | re.DOTALL
        ):
            intent = self._normalize_query_content(match.group(2))
            data = match.group(3).strip() if match.group(3).strip() else None
            tags.append((match.start(), match.end(), intent, data))

        # Pattern for simple <orakle>...</orakle> (no attributes)
        simple_pattern = r"<orakle>(.*?)</orakle>"
        for match in re.finditer(
            simple_pattern, text, re.IGNORECASE | re.DOTALL
        ):
            # Skip if this region was already matched by the attr pattern
            already_matched = any(
                t[0] <= match.start() and match.end() <= t[1] for t in tags
            )
            if not already_matched:
                intent = self._normalize_query_content(match.group(1))
                tags.append((match.start(), match.end(), intent, None))

        # Sort by position
        tags.sort(key=lambda t: t[0])

        # Check for unclosed tag
        open_pattern = r"<orakle(?:\s[^>]*)?>|<orakle>"
        close_pattern = r"</orakle>"

        open_matches = list(re.finditer(open_pattern, text, re.IGNORECASE))
        close_matches = list(re.finditer(close_pattern, text, re.IGNORECASE))

        has_unclosed = len(open_matches) > len(close_matches)

        return tags, has_unclosed, None, None

    def process_stream(
        self,
        token_stream: Generator[str, None, None],
        chat_history: Optional[List[Dict]] = None,
        reasoning_level_heuristic: float = 0.0,
        current_language: str = None,
        memories: Optional[List[Dict]] = None,
        agentic_mode: bool = False,
    ) -> Generator[Union[str, dict], None, None]:
        """
        Process a stream of tokens to detect and handle orakle tags.

        Args:
            token_stream: Generator yielding tokens from the LLM
            chat_history: Optional chat history list for context
            reasoning_level_heuristic: A reasoning level calculated by a heuristic
                                       based on the user's query.
            current_language: Language code for responses.
            memories: Optional list of memory dictionaries for context

        Yields:
            Processed tokens, including command results and guardrail messages.
        """
        # TODO: [Refactor] Implement explicit State Machine for stream processing.
        # The current implementation uses an implicit state machine (buffer + booleans + if/else blocks)
        # which makes tracing edge cases (typos, nested tags, partial streams) difficult.
        #
        # Proposed Architecture (Separation of Concerns):
        # 1. Create an Enum for states: TEXT, POTENTIAL_TAG, INSIDE_TAG.
        # 2. Extract the lexing/parsing logic into a separate generator (e.g., `_tokenize_stream`).
        #    This tokenizer should ONLY handle buffer management and state transitions, yielding
        #    tuples like ("TEXT", "safe text") or ("TAG", "<orakle>query</orakle>").
        # 3. Simplify `process_stream` to act purely as an Executor that consumes the tokenizer's
        #    output and routes it to `yield` (for TEXT) or `_process_orakle_request` (for TAG).

        buffer = ""
        found_orakle = False  # Track if we've found at least one orakle tag

        # Guardrail buffer for forbidden signals
        signal_check_buffer = ""
        forbidden_signal = "_orakle_loading_signal_"

        self.current_language = (
            current_language if current_language is not None else "English"
        )
        logger.info(f"OrakleMiddleware: current_language: {current_language}")

        for token in token_stream:
            if token is None:
                continue

            # --- Guardrail: Check for forbidden internal signal ---
            signal_check_buffer += token
            if len(signal_check_buffer) > len(forbidden_signal) + 20:
                signal_check_buffer = signal_check_buffer[
                    -(len(forbidden_signal) + 20):
                ]

            if forbidden_signal in signal_check_buffer:
                logger.warning(
                    "GUARDRAIL: LLM generated forbidden internal signal."
                )
                yield (
                    "\n\n[__AINARA_GUARDRAIL__] Error: You generated a system"
                    f" signal ('{forbidden_signal}') which is forbidden."
                    " DO NOT SIMULATE THE EXECUTION OF SKILLS. Use"
                    " <orakle>your query</orakle> to run commands.\n\n"
                )
                return

            buffer += token

            # Check for typo tags in the current buffer
            typo = self._check_for_typo_tags(buffer)
            if typo:
                # Output buffer content before the typo, then guardrail
                yield buffer
                yield self._get_typo_correction_message(typo)
                buffer = ""
                continue

            # Try to extract complete orakle tags
            tags, has_unclosed, _, guardrail_type = self._extract_orakle_tags(
                buffer
            )

            if guardrail_type:
                yield buffer
                if guardrail_type == "attribute":
                    yield self._get_attribute_rejection_message()
                elif guardrail_type == "self_closing":
                    yield self._get_self_closing_rejection_message()
                elif guardrail_type == "nested":
                    yield self._get_nested_tags_rejection_message()
                return

            if tags:
                # Process each found tag
                last_end = 0
                for start, end, query, data in tags:
                    # Yield text before this tag (only if we haven't found orakle yet)
                    if not found_orakle:
                        pre_text = buffer[last_end:start]
                        if pre_text:
                            yield pre_text
                    else:
                        # Inter-tag text is being discarded; signal if it
                        # contains alphabetic characters
                        inter_text = buffer[last_end:start]
                        if inter_text and any(
                            c.isalpha() for c in inter_text
                        ):
                            logger.info(
                                "ORAKLE GUARD: Ignoring inter-tag text:"
                                f" '{inter_text.strip()}'"
                            )
                            yield "\n_orakle_trailing_text_discarded_\n"

                    found_orakle = True

                    # Execute the orakle command
                    logger.info(f"ORAKLE command to process: '{query}'")
                    if query:
                        yield from self._process_orakle_request(
                            query,
                            chat_history,
                            reasoning_level_heuristic=reasoning_level_heuristic,
                            orakle_data=data,
                            memories=memories,
                            agentic_mode=agentic_mode,
                        )

                    last_end = end

                # Keep any remaining text after the last tag
                buffer = buffer[last_end:]

                # After finding orakle, ignore non-orakle text
                if found_orakle and buffer.strip():
                    # Check if remaining buffer might contain another tag
                    if not self._has_potential_tag(buffer):
                        logger.info(
                            "ORAKLE GUARD: Ignoring trailing text after"
                            f" command: '{buffer.strip()}'"
                        )
                        # Signal trailing text violation if it contains
                        # alphabetic characters (actual generated content)
                        if any(c.isalpha() for c in buffer):
                            yield "\n_orakle_trailing_text_discarded_\n"
                        buffer = ""

            # If buffer is getting large and no complete tag found,
            # yield content up to potential tag start
            elif len(buffer) > 1000 and not self._has_potential_tag(buffer):
                if not found_orakle:
                    yield buffer
                buffer = ""

        # Process any remaining buffer content
        if buffer:
            tags, has_unclosed, typo, guardrail_type = (
                self._extract_orakle_tags(buffer)
            )

            if guardrail_type:
                yield buffer
                if guardrail_type == "attribute":
                    yield self._get_attribute_rejection_message()
                elif guardrail_type == "self_closing":
                    yield self._get_self_closing_rejection_message()
                elif guardrail_type == "nested":
                    yield self._get_nested_tags_rejection_message()
            elif typo:
                yield buffer
                yield self._get_typo_correction_message(typo)
            elif has_unclosed:
                yield buffer
                logger.info("GUARDRAIL generated: unclosed orakle tag")
                yield self._get_unclosed_tag_message()
            elif tags:
                # Process remaining tags
                last_end = 0
                for start, end, query, data in tags:
                    if not found_orakle:
                        pre_text = buffer[last_end:start]
                        if pre_text:
                            yield pre_text
                    else:
                        # Inter-tag text is being discarded; signal if it
                        # contains alphabetic characters
                        inter_text = buffer[last_end:start]
                        if inter_text and any(
                            c.isalpha() for c in inter_text
                        ):
                            logger.info(
                                "ORAKLE GUARD: Ignoring inter-tag text:"
                                f" '{inter_text.strip()}'"
                            )
                            yield "\n_orakle_trailing_text_discarded_\n"

                    found_orakle = True
                    logger.info(f"ORAKLE command to process: '{query}'")
                    if query:
                        yield from self._process_orakle_request(
                            query,
                            chat_history,
                            reasoning_level_heuristic=reasoning_level_heuristic,
                            orakle_data=data,
                            memories=memories,
                            agentic_mode=agentic_mode,
                        )
                    last_end = end

                # Any remaining text after tags
                remaining = buffer[last_end:]
                if remaining and not found_orakle:
                    yield remaining
                elif remaining and found_orakle:
                    if any(c.isalpha() for c in remaining):
                        logger.info(
                            "ORAKLE GUARD: Ignoring trailing text after"
                            f" command: '{remaining.strip()}'"
                        )
                        yield "\n_orakle_trailing_text_discarded_\n"
            elif not found_orakle:
                # No tags found, yield remaining buffer
                yield buffer

    def _process_orakle_request(
        self,
        query: str,
        chat_history: Optional[List[Dict]] = None,
        reasoning_level_heuristic: float = 0.0,
        orakle_data: Optional[str] = None,
        memories: Optional[List[Dict]] = None,
        agentic_mode: Optional[bool] = False,
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
            chat_history: Optional chat history list for context
            reasoning_level_heuristic: A reasoning level calculated by a heuristic
                                       based on the user's query.
            orakle_data: Optional data payload from the orakle tag content
                         when query attribute form is used.
            memories: Optional list of memory dictionaries for context
            agentic_mode: Optional Orakle is being executed in agentic mode

        Yields:
            Processed results as a stream
        """

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
            source_tag = "[USER]" if skill_id.startswith("user_") else "[SYSTEM]"
            skill_desc = (
                f"## Skill id {skill_id} {source_tag} (match score: {score:.2f})\n\n"
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
        template = (
            "framework.chat_manager.orakle_select_and_params"
            if self.enable_agent_spawn
            else "framework.chat_manager.orakle_select_and_params_old"
        )
        prompt = self.template_manager.render(
            template,
            {
                "query": query,
                "candidate_skills": candidate_skills_text,
                "language": self.current_language or "English",
                "orakle_data": orakle_data,
                "agentic_mode": agentic_mode,
            },
        )

        logger.debug(f"ORAKLE skill selection prompt: {prompt}")

        # --- Guardrail: Retry loop for skill selection ---
        valid_skill_ids = [m["skill_id"] for m in matches]

        if not self.system_message:
            raise ValueError(
                "system_message is not initialized in OrakleMiddleware"
            )

        select_prompt = """
You are an expert data analyist. You combine built-in knowledge with real-time capabilities through the ORAKLE query system. ORAKLE connects with external API servers to access real-time data; these capabilities are called skills. Task is to identify from a query in natural language the skill and parameters matching the query intention. If no match can be found return an empty skill_id next to a descriptive error about why none of the possible candidates fits. Search carefully among the available skills.

IMPORTANT: If multiple skills seem equally relevant for the user's intent, always prefer skills marked as [USER] over those marked as [SYSTEM].
"""
        match_providers = self.config_manager.get("orakle.match_providers", [])
        llm_config = self.config_manager.get("llm", {})

        selection_data = {}
        selection_response = ""
        max_attempts = 3

        providers_to_try = match_providers + [None]

        for provider_name in providers_to_try:
            if provider_name in self._blacklisted_match_providers:
                continue

            try:
                if provider_name:
                    if provider_name not in self._match_llm_cache:
                        self._match_llm_cache[provider_name] = (
                            create_llm_backend(
                                llm_config, selected_provider=provider_name
                            )
                        )
                    current_llm = self._match_llm_cache[provider_name]
                else:
                    current_llm = self.llm
            except Exception as e:
                logger.warning(
                    f"Failed to initialize provider '{provider_name}': {e}"
                )
                if provider_name is not None:
                    logger.warning(
                        f"ORAKLE: Blacklisting provider: {provider_name} (p1)"
                    )
                    self._blacklisted_match_providers.add(provider_name)
                continue

            # Reset chat history for this provider
            current_chat_history = current_llm.prepare_chat(
                system_message=select_prompt,
                new_message=prompt,
            )

            provider_success = False

            for attempt in range(max_attempts):
                try:
                    selection_response = current_llm.chat(
                        chat_history=current_chat_history,
                        stream=False,
                        # Enforce low level reasoning if available
                        reasoning_level=0.3,
                    )
                except Exception as e:
                    logger.warning(
                        f"ORAKLE provider '{provider_name or 'default'}'"
                        f" exception: {e}"
                    )
                    break  # Break attempt loop on hard exception

                logger.info(
                    "ORAKLE selection_response (provider:"
                    f" {provider_name or 'default'}, attempt {attempt + 1}):"
                    f" {selection_response}"
                )

                try:
                    selection_data = json.loads(selection_response)
                    selected_skill_id = selection_data.get("skill_id")

                    # Validation
                    if not selected_skill_id:
                        # Valid: No skill selected
                        provider_success = True
                        break

                    if selected_skill_id in valid_skill_ids:
                        # Valid: Selected skill is in candidates
                        provider_success = True
                        break

                    # Invalid: Hallucination
                    logger.warning(
                        f"ORAKLE: Hallucinated skill_id '{selected_skill_id}'"
                    )
                    if attempt < max_attempts - 1:
                        current_chat_history.append(
                            {
                                "role": "assistant",
                                "content": selection_response,
                            }
                        )
                        current_chat_history.append(
                            {
                                "role": "user",
                                "content": (
                                    "Error: The skill_id"
                                    f" '{selected_skill_id}' is not in the"
                                    " available candidates. Please choose one"
                                    f" of: {', '.join(valid_skill_ids)} or"
                                    " return null."
                                ),
                            }
                        )

                except json.JSONDecodeError:
                    logger.warning(
                        "ORAKLE: JSONDecodeError in selection response"
                    )
                    if attempt < max_attempts - 1:
                        current_chat_history.append(
                            {
                                "role": "assistant",
                                "content": selection_response,
                            }
                        )
                        current_chat_history.append(
                            {
                                "role": "user",
                                "content": (
                                    "Error: Invalid JSON format. Please return"
                                    " ONLY a valid JSON object."
                                ),
                            }
                        )

            if provider_success:
                break  # Break provider loop on success
            else:
                logger.warning(
                    f"Provider '{provider_name or 'default'}' failed to"
                    " produce valid selection."
                )
                if provider_name is not None:
                    logger.warning(
                        f"ORAKLE: Blacklisting provider: {provider_name} (p2)"
                    )
                    self._blacklisted_match_providers.add(provider_name)

        try:
            frustration_level = selection_data.get("frustration_level", 0.0)
            frustration_reason = selection_data.get("frustration_reason", "")
            if frustration_level > 0:
                logger.info(
                    "ORAKLE: Detected frustration level:"
                    f" {frustration_level:.2f}. Reason:"
                    f" '{frustration_reason}'. Query: '{query}'"
                )

            # Prioritize reasoning level from Orakle, fall back to heuristic
            orakle_reasoning_level = selection_data.get("reasoning_level")
            if orakle_reasoning_level is not None:
                reasoning_level = orakle_reasoning_level
                logger.info(
                    "ORAKLE: Reasoning level from skill selection:"
                    f" {reasoning_level}"
                )
            else:
                reasoning_level = reasoning_level_heuristic
                logger.info(
                    "ORAKLE: Reasoning level from heuristic:"
                    f" {reasoning_level}"
                )
            # Apply the global reasoning effort limit
            final_reasoning_level = min(
                reasoning_level, self.reasoning_effort_limit
            )
            if final_reasoning_level < reasoning_level:
                logger.info(
                    "ORAKLE: Capping reasoning level from"
                    f" {reasoning_level} to {final_reasoning_level} due to"
                    " global limit."
                )

            skill_intention = selection_data.get("skill_intention", "")

            # Handle agent requirement
            if selection_data.get("requires_agent", False):
                logger.info(
                    f"ORAKLE: Query requires agent processing: '{query}'"
                )
                if skill_intention:
                    yield f"\n{skill_intention}\n\n"
                yield "\n_orakle_loading_signal_|spawn_agent\n"

                # Spawn ephemeral agent via Bureau
                agent_result = self._spawn_ephemeral_agent(
                    query=query,
                    chat_history=chat_history,
                    reasoning_level=final_reasoning_level,
                )

                if agent_result:
                    yield agent_result
                else:
                    yield (
                        "\nI encountered an issue processing that request."
                        " Please try again.\n\n"
                    )
                return

            # Use the data from the retry loop
            # If retries failed (e.g. persistent hallucination),
            # we force invalid ID to None
            selected_skill_id = selection_data.get("skill_id")
            if selected_skill_id and selected_skill_id not in valid_skill_ids:
                logger.error(
                    "ORAKLE: Persistent hallucination of skill_id"
                    f" '{selected_skill_id}' after retries."
                )
                selected_skill_id = None
                selection_data["skill_id"] = None

            if selected_skill_id:
                parameters = selection_data.get("parameters", {})

            if not selected_skill_id:
                if selection_data.get("error_msg"):
                    error_msg = selection_data.get("error_msg")
                else:
                    error_msg = "couldn't find a skill matching the query"
                logger.error(
                    f"ORAKLE: {error_msg} LLM response: {selection_response}"
                )
                if agentic_mode:
                    yield f"\nOrakle error: {error_msg}\n\n"
                else:
                    yield f"\nI'm sorry, {error_msg}\n\n"
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
                if skill_intention and not agentic_mode:
                    yield f"\n{skill_intention}\n\n"
                yield f"\n_orakle_loading_signal_|{selected_skill_id}\n"

                skill_instance = self.system_skills[selected_skill_id]
                result = skill_instance.run(query, parameters, chat_history)

                chat_context = self._get_chat_context(chat_history)
                for chunk in self.stream_command_interpretation(
                    result,
                    query,
                    chat_context=chat_context,
                    reasoning_level=final_reasoning_level,
                    agentic_mode=agentic_mode,
                ):
                    yield chunk
                return  # Stop processing, as we've handled this system skill

            # --- Handle Regular Skills ---
            # Yield processing message
            if skill_intention and not agentic_mode:
                yield f"\n{skill_intention}\n\n"
            # Needed so agent class recognizes skill execution
            yield f"\n_orakle_loading_signal_|{selected_skill_id}\n"

            # Get skill info to check its type
            skill_info = self._get_skill_info(selected_skill_id)

            # Execute the selected skill with parameters
            result = self.execute_orakle_command(
                selected_skill_id, parameters, chat_history
            )

            # If the skill is a nexus skill with a UI, yield the component data directly
            if (
                skill_info
                and (skill_info.get("type") == "nexus" or skill_info.get("type") == "user_skill")
                and skill_info.get("ui")
            ):
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
                    error_msg = (
                        f"Nexus or user skill '{selected_skill_id}' did not return"
                        " valid JSON data."
                    )
                    logger.error(f"ORAKLE: {error_msg} Data: {result}")
                    yield f"\nError: {error_msg}\n\n"
                    return
            # In agentic_mode don't interpret data
            elif agentic_mode:
                result_data = json.loads(result)
                yield f"\nOrakle query '{query}' result:\n{result_data}\n"
            else:
                chat_context = self._get_chat_context(chat_history, memories)
                # Get interpretation as a stream for regular skills
                for interpretation_chunk in self.stream_command_interpretation(
                    [result],
                    query,
                    chat_context=chat_context,
                    reasoning_level=final_reasoning_level,
                    agentic_mode=agentic_mode,
                ):
                    yield interpretation_chunk

        except json.JSONDecodeError:
            error_msg = "Failed to parse skill selection response."
            logger.error(
                f"ORAKLE: {error_msg} LLM response: {selection_response}"
            )
            if provider_name is not None:
                logger.warning(
                    f"ORAKLE: Blacklisting provider: {provider_name} (p3)"
                )
                self._blacklisted_match_providers.add(provider_name)
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
        self,
        skill_id: str,
        params: dict,
        chat_history: Optional[List[Dict]] = None,
    ) -> str:
        """
        Execute an Orakle command and return the result.

        Args:
            skill_id: The ID of the skill to execute
            params: Dictionary of parameters for the skill
            chat_history: Optional chat history list for context

        Returns:
            Command execution result as a string
        """
        logger.info(
            f"ORAKLE Executing skill '{skill_id}' with params: {params}"
        )

        # Check if skill requires additional data
        skill_info = self._get_skill_info(skill_id)

        if not skill_info:
            logger.error(
                f"Could not find skill info for {skill_id} before execution."
            )
            return f"Error: Skill '{skill_id}' not found or unavailable."

        # Add chat history if the skill requires it
        if chat_history and any(
            param.get("name") == "_chat_history"
            for param in skill_info.get("parameters", [])
        ):
            formatted_history = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in chat_history
                if msg.get("role") in ["user", "assistant"]
            ]
            params["_chat_history"] = formatted_history
            logger.debug(f"Added chat history to params for skill {skill_id}")

        return call_skill(self.orakle_servers, skill_id, params)

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
                    for name, obj in inspect.getmembers(
                        module, inspect.isclass
                    ):
                        if (
                            issubclass(obj, BaseSystemSkill)
                            and obj is not BaseSystemSkill
                        ):
                            skill_instance = obj()
                            skill_definition = skill_instance.get_definition()
                            self.capabilities.append(skill_definition)
                            self.system_skills[skill_instance.name] = (
                                skill_instance
                            )
                            logger.info(
                                f"Loaded system skill: {skill_instance.name}"
                            )
                except Exception as e:
                    logger.error(
                        f"Failed to load system skill from {filename}: {e}"
                    )

    def _get_chat_context(
        self,
        chat_history: Optional[List[Dict]] = None,
        memories: Optional[List[Dict]] = None,
    ) -> dict:
        """Extracts relevant context from the chat history and memories.

        Note: This method provides basic context extraction. For richer context
        (user profile, conversation summary), the caller should pass
        a chat_history that already includes this information in the system message
        or provide it through other means.
        """
        chat_context = {}
        if not chat_history:
            return chat_context

        # Recent chat history (e.g., last 4 messages / 2 rounds)
        history_text = ""
        # Take last 4 messages
        recent_messages = chat_history[-4:]
        for msg in recent_messages:
            # Skip system messages to avoid redundant context
            if msg.get("role") == "system":
                continue
            role = msg.get("role", "unknown").capitalize()
            content = msg.get("content", "")
            history_text += f"{role}: {content}\n"
        if history_text:
            chat_context["recent_history"] = history_text.strip()

        # Add memories if provided
        if memories and len(memories) > 0:
            logger.info(
                f"Injecting {len(memories)} dynamically retrieved memories"
                " into ORAKLE context."
            )
            context_memories_prompt = self.template_manager.render(
                "framework.chat_manager.user_memories_prompt",
                {"memories": memories},
            )
            chat_context["memories"] = f"\n\n{context_memories_prompt}"

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
        agentic_mode: bool = False,
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

        # Skip context enrichment in agentic mode
        if agentic_mode:
            # Use minimal context to avoid redundant information
            effective_context = {}
        else:
            effective_context = chat_context or {}

        interpretation_prompt = self.template_manager.render(
            "framework.chat_manager.command_interpretation",
            {
                "formatted_results": "\n".join(formatted_results),
                "query": query,
                "chat_context": effective_context,
                "language": self.current_language or "English",
            },
        )

        logger.debug(f"ORAKLE interpretation_prompt: {interpretation_prompt}")

        if not self.system_message:
            raise ValueError(
                "system_message is not initialized in OrakleMiddleware"
            )

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
        cleaned_stream = self._strip_think_blocks_from_stream(
            interpretation_stream
        )

        # Yield each chunk as it comes
        for chunk in cleaned_stream:
            if chunk:
                yield chunk

    def _spawn_ephemeral_agent(
        self,
        query: str,
        chat_history: Optional[List[Dict]] = None,
        reasoning_level: float = 0.0,
    ) -> Optional[str]:
        """
        Spawn an ephemeral agent via Bureau to handle multi-step queries.

        Args:
            query: The user's query
            chat_history: Optional chat history for context
            reasoning_level: Reasoning effort level

        Returns:
            Agent's final response or None on failure
        """
        bureau_config = self.config_manager.get("bureau", {})
        bureau_host = bureau_config.get("host", "127.0.0.1")
        bureau_port = bureau_config.get("port", 8010)
        bureau_url = f"http://{bureau_host}:{bureau_port}"

        try:
            # Create agent
            logger.info(f"Spawning ephemeral agent for query: '{query}'")

            # Build blueprint for the agent
            blueprint = {
                "name": "EphemeralAgent",
                "system_message": (
                    "\n\nYou are an autonomous agent handling a multi-step"
                    " task. Work systematically toward the goal."
                ),
                "allowed_skills": ["*"],
            }

            # Build user context from chat history
            user_context = {}
            if chat_history:
                recent_messages = chat_history[-6:]  # Last 3 exchanges
                context_summary = "\n".join(
                    [
                        f"{msg.get('role', 'unknown')}:"
                        f" {msg.get('content', '')[:200]}"
                        for msg in recent_messages
                        if msg.get("role") in ["user", "assistant"]
                    ]
                )
                user_context["recent_conversation"] = context_summary

            # Create agent via Bureau API
            create_response = requests.post(
                f"{bureau_url}/v1/agents",
                json={
                    "goal": query,
                    "blueprint": blueprint,
                    "user_context": user_context,
                    "max_turns": 15,
                    "execution_timeout": 600,
                },
                timeout=5,
            )

            if create_response.status_code != 202:
                logger.error(f"Failed to create agent: {create_response.text}")
                return None

            agent_data = create_response.json()
            agent_id = agent_data.get("agent_id")

            if not agent_id:
                logger.error("No agent_id returned from Bureau")
                return None

            logger.info(f"Agent created with ID: {agent_id}")

            # Poll for completion
            max_wait = 120  # 2 minutes max
            poll_interval = 2  # seconds
            elapsed = 0

            while elapsed < max_wait:
                time.sleep(poll_interval)
                elapsed += poll_interval

                status_response = requests.get(
                    f"{bureau_url}/v1/agents/{agent_id}", timeout=5
                )

                # Handle different status codes
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    status = status_data.get("status")

                    logger.info(
                        f"Agent {agent_id} status: {status} (elapsed:"
                        f" {elapsed}s)"
                    )

                    if status == "COMPLETED":
                        response = status_data.get("response", "")
                        # Extract the actual response text if it's a dictionary
                        if isinstance(response, dict):
                            response = response.get("response", "")
                        logger.info(
                            "Agent completed successfully. "
                            f"Turns: {status_data.get('turns_used')}, "
                            f"Skills: {status_data.get('skills_executed')}"
                        )
                        return response
                    elif status == "FAILED":
                        # Agent executed but didn't achieve goal
                        failure_reason = status_data.get(
                            "failure_reason", "Unknown reason"
                        )
                        response = status_data.get("response", "")
                        # Extract the actual response text if it's a dictionary
                        if isinstance(response, dict):
                            response = response.get("response", "")
                        logger.warning(
                            f"Agent failed to achieve goal: {failure_reason}. "
                            f"Turns: {status_data.get('turns_used')}, "
                            f"Skills: {status_data.get('skills_executed')}"
                        )
                        # Return the response even on failure so user gets explanation
                        return (
                            response
                            if response
                            else (
                                "I couldn't complete that request."
                                f" {failure_reason}"
                            )
                        )

                elif status_response.status_code == 424:
                    # Failed Dependency - goal not achieved
                    status_data = status_response.json()
                    failure_reason = status_data.get(
                        "failure_reason", "Goal not achieved"
                    )
                    response = status_data.get("response", "")
                    # Extract the actual response text if it's a dictionary
                    if isinstance(response, dict):
                        response = response.get("response", "")
                    logger.warning(f"Agent failed (424): {failure_reason}")
                    return (
                        response
                        if response
                        else (
                            "I couldn't complete that request."
                            f" {failure_reason}"
                        )
                    )

                elif status_response.status_code == 500:
                    # Internal Server Error - execution error
                    status_data = status_response.json()
                    error = status_data.get("error", "Unknown error")
                    logger.error(f"Agent execution error (500): {error}")
                    return None

                else:
                    logger.error(
                        "Unexpected status code"
                        f" {status_response.status_code}:"
                        f" {status_response.text}"
                    )
                    return None

            logger.warning(f"Agent {agent_id} timed out after {max_wait}s")
            return None

        except requests.RequestException as e:
            logger.error(f"Bureau connection error: {e}")
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error spawning agent: {e}", exc_info=True
            )
            return None
