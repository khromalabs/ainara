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
from typing import Any, Dict, List, Optional

from pycountry import languages

from ainara.framework.config import config
from ainara.framework.orakle_middleware import OrakleMiddleware
from ainara.framework.template_manager import TemplateManager

logger = logging.getLogger(__name__)


class Agent:
    """
    Autonomous Agent that executes tasks using LLM and Orakle skills.

    The Agent operates in a loop:
    1. Receives a goal.
    2. Thinks (LLM).
    3. Acts (OrakleMiddleware executes skills).
    4. Observes (Result added to history).
    5. Repeats until the goal is met or no skills are used (final answer).
    """

    def __init__(
        self,
        llm,
        orakle_middleware: OrakleMiddleware,
        blueprint: Dict[str, Any],
        system_message: str,
        user_context: Optional[Dict[str, Any]] = None,
        conductor_agent: bool = False,
    ):
        """
        Initialize the Agent.

        Args:
            llm: The LLM backend instance.
            orakle_middleware: The middleware for skill execution.
            blueprint: Configuration dict defining the agent's persona and capabilities.
            Expected keys: 'name', 'system_message', 'allowed_skills'.
            user_context: Optional context about the user (e.g. profile summary).
        """
        self.llm = llm
        self.orakle_middleware = orakle_middleware
        self.blueprint = blueprint
        self.user_context = user_context or {}
        self.template_manager = TemplateManager()
        self.system_message = system_message + blueprint.get(
            "system_message", ""
        )
        self.name = blueprint.get("name", "Agent")
        # TODO Limit available skills?
        self.allowed_skills = blueprint.get("allowed_skills", ["*"])
        # Context will be initialized per run
        self.context = None
        self.current_lang_code = self.user_context.get(
            "language", config.get("stt.language", "en")
        )
        self.current_language = languages.get(
            alpha_2=self.current_lang_code
        ).name
        self.conductor_agent = conductor_agent
        logger.info(
            f"AGENT self.current_lang_code: {self.current_lang_code}"
            f" self.current_language: {self.current_language}"
        )

    def _parse_goal_completion(self, text: str) -> tuple[Optional[bool], dict]:
        """
        Parse goal completion tags from agent response.

        Args:
            text: The agent's response text

        Returns:
            Tuple of (goal_complete: bool or None, data: dict)
            - goal_complete: True if achieved, False if failed, None if no tags found
            - data: Dictionary with 'final_answer' and optionally 'failure_reason'
        """
        import re

        # Check for goal_complete tag
        complete_match = re.search(
            r"<goal_complete>(true|false)</goal_complete>",
            text,
            re.IGNORECASE | re.DOTALL,
        )

        if not complete_match:
            return None, {}

        goal_achieved = complete_match.group(1).lower() == "true"

        # Extract final_answer
        answer_match = re.search(
            r"<final_answer>(.*?)</final_answer>",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        final_answer = answer_match.group(1).strip() if answer_match else text

        data = {"final_answer": final_answer}

        # Extract failure_reason if present
        if not goal_achieved:
            reason_match = re.search(
                r"<failure_reason>(.*?)</failure_reason>",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if reason_match:
                data["failure_reason"] = reason_match.group(1).strip()

        return goal_achieved, data

    def run(self, goal: str, max_turns: int = 20) -> dict:
        """
        Execute the agent loop to achieve the goal.

        Args:
            goal: The objective for the agent.
            max_turns: Safety limit to prevent infinite loops.

        Returns:
            Dictionary with:
                - response: The final text response for the user
                - turns_used: Number of turns executed
                - skills_executed: List of unique skill IDs used
                - failure_reason: Explanation if goal not achieved (None if successful)
        """
        logger.info(f"Agent '{self.name}' starting run. Goal: {goal}")

        # TODO add user profile, maybe memories as well?
        # user_profile = self.user_context.get("user_profile_summary", "")

        # Initialize context for this run
        self.context: List[str] = []
        system_message = (
            f"{self.system_message}\nIMPORTANT: Never extend your work over "
            f" {max_turns} turns of conversation, that's the server hard"
            " cut limit."
        )
        self.llm.add_msg(system_message, self.context, "system")

        # Track execution metadata
        skills_executed = []

        # Build skills hint text from available capabilities
        skills_names = [
            skill["name"] for skill in self.orakle_middleware.capabilities
        ]
        skills_hint_text = ", ".join(skills_names)

        # Planning phase: Ask agent to create a plan before execution
        planning_prompt = (
            f"Goal: {goal}\n\n"
            "Before starting execution, create a brief plan:\n"
            "1. What are the main steps needed to achieve this goal?\n"
            "2. What information might you need to gather?\n\n"
            "After outlining your plan, begin execution."
        )
        self.llm.add_msg(planning_prompt, self.context, "user")
        logger.info(f"\nUSER:\n{planning_prompt}\n\n")

        final_response = ""
        turn = 0
        max_turns_without_skills = 3
        turn_without_skills = 0

        while turn < max_turns:
            turn += 1
            logger.info(f"Agent '{self.name}' - Turn {turn}/{max_turns}")

            # Inject skills hint into the last user message
            if (
                skills_hint_text
                and self.context
                and self.context[-1]["role"] == "user"
            ):
                if self.conductor_agent:
                    skills_hint_final_answer = ""
                else:
                    skills_hint_final_answer = """
ADDITIONAL INSTRUCTIONS FOR THE <final_answer> block:
- Use standard Markdown triple backtick blocks (e.g. ```python sample_variable=1```) to enclose blocks of code and tables.
- Any received block with this exact format: `_orakle_nexus_data_|{{json block}}` must be reproduced verbatim.
"""
                skills_hint = f"""
INSTRUCTIONS:
- Review ALL the information gathered in this conversation.
- If goal has not been achieved yet continue using skills to finish the task, via using <orakle>intent</orakle>.
- If an attempt to achieve the goal failed, avoid repeating the same intent. Try different strategies while also keeping the work within the specified max turn limits ({max_turns}).
- As soon goal is achieved, respond with this specific format:

<goal_complete>true</goal_complete>
<final_answer>Final response to the user in {self.current_language}. IMPORTANT: INCLUDE HERE ALL THE RELEVANT INFORMATION GATHERED ABOUT THE GOAL</final_answer>

{skills_hint_final_answer}

IMPORTANT: The limit to achieve the goal is {max_turns} turns of conversation. Use the <orakle>intent</orakle> tag for queries about real time data or external actions.
Attempt a single action per ORAKLE query. Use multiple queries if necessary.
</system_hint>"
"""

                # Create a copy to avoid polluting the actual history
                turn_context = copy.deepcopy(self.context)
                turn_context[-1]["content"] += skills_hint
                if turn == 1:
                    logger.info(
                        f"\nUSER + HINT:\n{turn_context[-1]["content"]}\n\n"
                    )
            else:
                turn_context = self.context

            # 1. Call LLM with current history
            # We use stream=True because OrakleMiddleware expects a generator
            llm_stream = self.llm.chat(chat_history=turn_context, stream=True)

            # 2. Process through OrakleMiddleware
            # The middleware handles skill detection, execution, and interpretation.
            # We pass our context (chat history) directly.
            processed_stream = self.orakle_middleware.process_stream(
                llm_stream,
                self.context,
                agentic_mode=True,
                current_language=self.current_language,
            )

            turn_response = ""
            skill_executed = False

            # 3. Consume the stream
            for chunk in processed_stream:
                if isinstance(chunk, str):
                    # Check for the internal signal that OrakleMiddleware emits
                    # when a skill is about to be executed.
                    if "_orakle_loading_signal_" in chunk:
                        # Extract skill_id from signal format: _orakle_loading_signal_|skill_id
                        if "|" in chunk:
                            skill_id = chunk.split("|", 1)[1].strip()
                            if skill_id and skill_id not in skills_executed:
                                skills_executed.append(skill_id)
                        skill_executed = True
                        # We don't add the signal to the final text response
                        continue
                    turn_response += chunk
                elif isinstance(chunk, dict):
                    # Handle structured data (e.g. Nexus components)
                    # For a headless agent, we might just log this or append a summary
                    if chunk.get("type") == "nexus_skill_result":
                        skill_executed = True
                        desc = (
                            f"\n\n_orakle_nexus_data_|{json.dumps(chunk)}\n\n"
                        )
                        turn_response += f"\n{desc}\n"

            logger.info(f"Executed skill in last turn: {skill_executed}")

            # 4. Update History
            self.llm.add_msg(turn_response, self.context, "assistant")
            logger.info(f"\nAGENT: {turn_response}\n\n")
            final_response = turn_response

            # Log the LLM output for debugging
            logger.info(f"Turn {turn} LLM output:\n{turn_response}")
            logger.debug(f"Turn {turn} response length: {len(turn_response)}")

            # 5. Check for goal completion tags
            goal_complete, completion_data = self._parse_goal_completion(
                turn_response
            )

            if goal_complete is True:
                # # Agent explicitly signaled completion or failure
                # if goal_complete:
                logger.info("Agent signaled goal completion (success)")
                return {
                    "response": completion_data.get(
                        "final_answer", turn_response
                    ),
                    "turns_used": turn,
                    "skills_executed": skills_executed,
                    "failure_reason": None,
                }

            evaluation_prompt = """
Is the goal achieved now? Please follow the instructions provided and continue until the goal is achieved.
"""
            self.llm.add_msg(evaluation_prompt, self.context, "user")
            logger.info(f"\nUSER:\n{evaluation_prompt}\n\n")

            if not skill_executed:
                turn_without_skills = turn_without_skills + 1
                if turn_without_skills > max_turns_without_skills:

                    # Max turns reached without completion
                    failure_reason = (
                        f"Maximum turns reached ({max_turns_without_skills})"
                        f" without using skills (turn: {turn})"
                    )
                    logger.warning(failure_reason)
                    return {
                        "response": final_response,
                        "turns_used": turn,
                        "skills_executed": skills_executed,
                        "failure_reason": failure_reason,
                    }
            else:
                turn_without_skills = 0  # reset on successful skill use

        # Max turns reached without completion
        logger.warning(
            f"Agent '{self.name}' reached max turns ({max_turns}) without"
            " completing goal."
        )
        return {
            "response": final_response,
            "turns_used": turn,
            "skills_executed": skills_executed,
            "failure_reason": (
                f"Maximum turns ({max_turns}) reached without completing goal"
            ),
        }
