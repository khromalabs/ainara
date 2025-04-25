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

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from ainara.framework.config import ConfigManager
from ainara.framework.skill import Skill


class ToolsReport(Skill):
    """Generate reports in local files following a user request"""

    matcher_info = (
        "Use this skill when the user wants to generate a report based on a"
        " conversation or specific content. This skill can create"
        " well-structured reports in various formats like markdown, text, or"
        " HTML, and save them to a file.\n\nExamples include: 'generate a report"
        " from this chat', 'create a summary report in markdown', 'make a"
        " report about our discussion', 'save a report of this conversation as"
        " HTML'. Keywords: report, generate, create, summary, document, save,"
        " file, markdown, text, HTML, conversation, chat, content."
    )

    def __init__(self):
        super().__init__()
        self.name = "report_generator"
        self.logger = logging.getLogger(__name__)
        self.config = ConfigManager()

        # Get default report directory from config or use Desktop
        self.default_dir = self.config.get(
            "skills.report_generator.default_directory", str(Path.home())
        )

        # Create the directory if it doesn't exist
        os.makedirs(self.default_dir, exist_ok=True)

    def _get_default_filename(self, format: str = "md") -> str:
        """Generate a default filename based on timestamp"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"report_{timestamp}.{format}"

    def _get_format_extension(self, format: str) -> str:
        """Convert format name to file extension"""
        format_map = {
            "markdown": "md",
            "md": "md",
            "text": "txt",
            "txt": "txt",
            "html": "html",
            "htm": "html",
        }
        return format_map.get(format.lower(), "md")

    def _format_chat_history(self, chat_history: list) -> str:
        """Format chat history into a readable conversation string"""
        conversation = ""
        for msg in chat_history:
            role = msg.get("role", "").capitalize()
            content = msg.get("content", "")
            conversation += f"{role}: {content}\n\n"
        return conversation

    def _create_report_prompt(
        self, conversation: str, goal: str, format: str
    ) -> str:
        """Create a prompt for the LLM to generate the report"""
        prompt = f"""
        Based on the following conversation, generate a report {goal}.
        Format the report in {format} format.

        CONVERSATION:
        {conversation}

        Your task is to analyze this conversation, extract the relevant information,
        and create a well-structured report that addresses the goal: {goal}.

        The report should be comprehensive, well-organized, and ready for presentation. The report should only represent and organize the information of the conversation towards the intended {goal} in a concise way, without adding further comments.
        """
        return prompt

    async def run(
        self,
        _chat_history: Annotated[
            List[Dict[str, Any]],
            "Chat history provided by the chat manager (internal)",
        ],
        goal: Annotated[
            Optional[str], "The purpose or intention of the report"
        ] = None,
        title: Annotated[Optional[str], "Title for the report"] = None,
        format: Annotated[
            str, "Output format (markdown, text, html)"
        ] = "markdown",
    ) -> Dict[str, Any]:
        """Generate a report based on the conversation and specified goal"""
        # Use provided conversation text or build from chat history
        if not _chat_history:
            return {
                "success": False,
                "error": (
                    "No conversation provided and no chat history available"
                ),
            }
        try:
            # Determine file extension
            ext = self._get_format_extension(format)

            # Use default directory with generated filename
            filename = self._get_default_filename(ext)
            if title:
                # Create a filename from the title
                safe_title = "".join(
                    c if c.isalnum() or c in " -_" else "_" for c in title
                )
                safe_title = safe_title.replace(" ", "_").lower()
                filename = f"{safe_title}_{filename}"

            report_path = Path(self.default_dir) / filename

            if not goal:
                goal = (
                    "Generate a well structured, informative, concise report"
                    " about the provided conversation"
                )

            # Create the prompt for the LLM
            prompt = self._create_report_prompt(_chat_history, goal, format)

            # Get LLM from the framework
            from ainara.framework.llm.litellm import LiteLLM

            llm = LiteLLM()

            # Prepare chat messages for the LLM
            system_message = (
                "You are a professional report writer. Your task is to analyze"
                " conversations and create well-structured reports."
            )
            chat_history = llm.prepare_chat(system_message, prompt)

            # Generate the report content using the LLM
            self.logger.info(f"Generating report with goal: {goal}")
            report_content = await llm.achat(chat_history=chat_history)

            # Add title if provided
            if title and format.lower() in ["markdown", "md"]:
                report_content = f"# {title}\n\n{report_content}"
            elif title:
                report_content = (
                    f"{title}\n{'=' * len(title)}\n\n{report_content}"
                )

            # Write the report to file
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_content)

            self.logger.info(f"Report saved to: {report_path}")

            # Return the result
            preview_length = min(500, len(report_content))
            return {
                "success": True,
                "path": str(report_path),
                "preview": (
                    report_content[:preview_length]
                    + ("..." if len(report_content) > preview_length else "")
                ),
                "format": format,
            }

        except Exception as e:
            self.logger.error(f"Error generating report: {str(e)}")
            return {"success": False, "error": str(e)}
