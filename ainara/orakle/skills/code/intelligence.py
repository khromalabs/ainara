import logging
# import os
import re
import shutil
import subprocess
import tempfile
from typing import Annotated, Any, Dict, Optional

from ainara.framework.config import config
from ainara.framework.llm import create_llm_backend
from ainara.framework.skill import Skill

from .lib.neovim import NeovimClient
from .lib.parser import CodeParser


class CodeIntelligence(Skill):
    """Analysis, documentation, refactorization, dynamic read or load for any kind changes or checks in source code connecting with a remote editor"""

    matcher_info = (
        "Connects with a remote editor while a file is being edited allowing"
        " operations of refactorization, documentation, bug fixing, or any"
        " code intelligence related functionalities.\n\nKeywords: code,"
        " refactor, change, modify, update, fix, document, function, class,"
        " method, programming, development, software, editor, neovim, vim."
    )

    def __init__(self):
        # Call the constructor of the parent class to ensure proper initialization
        super().__init__()

        # Initialize the CodeParser instance which is responsible for parsing code
        # This is essential for processing and analyzing the code structure
        self.parser = CodeParser()

        # Obtain a logger instance for this module to enable logging of events and errors
        # This is useful for debugging and monitoring the application's behavior
        self.logger = logging.getLogger(__name__)

        # TODO: Abstract editor clients for broader support
        # This is a placeholder for future enhancement where different editor clients
        # (e.g., VSCode, Sublime Text) can be supported by abstracting the interface
        # Currently, only the NeovimClient is being used

        # Initialize the NeovimClient which provides integration with the Neovim editor
        # This client is used to interact with the editor for features like real-time updates
        # and code navigation
        self.editor_client = NeovimClient()

        self.languages_config = [
            {
                "extension": ".py",
                "language_name": "python",
                "linter_command": ["pyflakes"],
                "supported": False,
            },
            {
                "extension": ".js",
                "language_name": "javascript",
                "linter_command": ["node", "-c"],
                "supported": False,
            },
        ]

        # Determine supported extensions based on parser and linter availability
        parser_supported = self.parser.get_supported_extensions()

        for lang in self.languages_config:
            ext = lang["extension"]
            command = lang["linter_command"]
            linter_found = shutil.which(command[0])
            parser_found = ext in parser_supported

            if linter_found and parser_found:
                lang["supported"] = True
                self.logger.info(
                    f"Code intelligence enabled for '{ext}' files."
                )
            elif linter_found and not parser_found:
                self.logger.warning(
                    f"Linter for '{ext}' found, but no parser grammar. "
                    f"'{ext}' files will not be supported."
                )
            elif not linter_found and parser_found:
                self.logger.warning(
                    f"Parser grammar for '{ext}' found, but no linter. "
                    f"'{ext}' files will not be supported."
                )

    def _cleanup_llm_output(self, text: str) -> str:
        """Removes markdown code fences and leading/trailing whitespace."""
        # Find content within the first python code block
        match = re.search(r"```(?:[a-z]+\n)?(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Fallback for raw code output
        return text.strip()

    def _verify_syntax(
        self, file_path: str, content: Optional[str] = None
    ) -> str | None:
        """Runs a language-specific linter to verify syntax and returns error or None."""
        # This can be expanded with more linters and configuration options.
        # Note: The corresponding linters (e.g., pyflakes) must be installed
        # in the environment where this skill is executed.
        file_path_to_lint = file_path
        temp_file_name = None

        if content is not None:
            extension = "." + file_path.split(".")[-1]
            # Create a temporary file to hold the buffer content
            # We use delete=False and manually clean up because some linters
            # might need to re-open the file by name.
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=extension, delete=False, encoding="utf-8"
            ) as temp_file:
                temp_file.write(content)
                temp_file_name = temp_file.name
            file_path_to_lint = temp_file_name

        extension = "." + file_path.split(".")[-1]
        lang_config = next(
            (
                lc
                for lc in self.languages_config
                if lc["extension"] == extension
            ),
            None,
        )

        if not lang_config or not lang_config["supported"]:
            self.logger.warning(
                f"No linter found for {file_path}, skipping verification."
            )
            return None

        command = lang_config["linter_command"]

        try:
            process = subprocess.run(
                [*command, file_path_to_lint],
                capture_output=True,
                text=True,
                check=False,
            )
            if process.returncode != 0:
                error_output = (
                    process.stdout.strip() + "\n" + process.stderr.strip()
                )
                return f"Syntax check failed:\n{error_output.strip()}"
        except Exception as e:
            return f"Failed to run linter: {e}"
        finally:
            pass
            # if temp_file_name:
            #     os.remove(temp_file_name)

        return None

    def _check_context_window(
        self, system_message: str, user_message: str
    ) -> Optional[Dict[str, Any]]:
        """Checks if the prompt is within the LLM's configured context window."""

        context_window = self.llm.get_context_window()

        if context_window:
            # Estimate token count using a common approximation (1 token ~ 4 chars)
            tokens_system = self.llm._get_token_count(system_message, "system")
            tokens_user = self.llm._get_token_count(user_message, "user")
            total_tokens = tokens_system + tokens_user
            self.logger.info(
                f"Estimated prompt size ({int(total_tokens)} tokens)"
            )

            if total_tokens > context_window:
                self.logger.warning(
                    "Estimated prompt size exceeds the model's"
                    f" context window ({context_window} tokens)."
                )
                return {
                    "success": False,
                    "error": (
                        "The code block is too large for the model's context"
                        f" window. Estimated tokens: {int(total_tokens)},"
                        f" Limit: {context_window}."
                    ),
                }
        return None

    async def run(
        self,
        query: Annotated[
            str, "A natural language instruction for modifying the code."
        ],
    ) -> Dict[str, Any]:
        """
        Modifies code in the current editor buffer based on a natural language query.
        """
        self.logger.info(f"CODE: Received query: '{query}'")

        # 1. Check editor connection and get context
        if not self.editor_client or not self.editor_client.nvim:
            # Try to connect again just in case
            self.editor_client = NeovimClient()
            if not self.editor_client or not self.editor_client.nvim:
                return {
                    "success": False,
                    "error": (
                        "Neovim is not connected or pynvim is not installed."
                    ),
                }

        context = await self.editor_client.get_context()
        if not context:
            return {
                "success": False,
                "error": "Could not retrieve context from Neovim.",
            }
        file_path = context["file_path"]
        cursor_line = context["cursor_line"]
        cursor_col = context["cursor_col"]

        # Determine language for prompt and regex
        file_extension = "." + file_path.split(".")[-1]
        lang_config = next(
            (
                lc
                for lc in self.languages_config
                if lc["extension"] == file_extension
            ),
            None,
        )

        if not lang_config or not lang_config["supported"]:
            return {
                "success": False,
                "error": (
                    f"File type '{file_extension}' is not supported by the"
                    " Code Intelligence skill."
                ),
            }

        language_name = lang_config["language_name"]

        # 2. Get buffer content
        original_content = await self.editor_client.get_buffer_content()
        if original_content is None:
            return {
                "success": False,
                "error": "Could not get buffer content from Neovim.",
            }

        # 3. Find the relevant code block to modify
        try:
            code_block_info = self.parser.find_enclosing_function_or_class(
                file_path, original_content, cursor_line, cursor_col
            )

            lines = original_content.splitlines()
            if code_block_info:
                start_line = code_block_info["start_line"]  # 0-indexed
                end_line = code_block_info["end_line"]  # 0-indexed
                code_block_lines = lines[start_line: end_line + 1]
                context_code = "\n".join(code_block_lines)
            else:
                self.logger.info(
                    "No enclosing function/class found at cursor. Using the"
                    " entire file as context."
                )
                start_line = 0
                end_line = len(lines) - 1
                context_code = original_content
        except Exception as e:
            self.logger.exception("Error finding enclosing code block.")
            return {"success": False, "error": f"Failed to parse code: {e}"}

        # 4. Prompt LLM for modification
        system_message = (
            "You are an expert programmer assistant. Your task is to help a"
            " user with their code. You will be given a code snippet and a"
            " user instruction.\n- If the instruction is a request to modify"
            " the code (e.g., 'refactor this', 'add a docstring'), you MUST"
            " return the complete, modified code snippet enclosed in a"
            f" ```{language_name} markdown block. Any explanatory text or"
            " comments should be placed outside this block. The code inside"
            " the block MUST be a drop-in replacement for the original,"
            " preserving the exact original indentation of the block.\n- If"
            " the instruction is a question that does not require a code"
            " change, provide a concise, helpful answer in plain text. In"
            " case of processing substantive amounts of information, keep"
            " responses instructive, concise and engaging always taking into"
            " account the user query. YOU MUST AVOID ENUMERATED LISTS. For"
            " complex topics, just provide the key points and ask what"
            " information should be expanded. Use spoken style—contractions,"
            " direct address—for fluid STT/TTS conversation. Instead of"
            " lists, which are difficult for TTS, weave multiple items into a"
            " natural sentence or present them as a continuous thought."
        )
        user_message = (
            f"Instruction: {query}\n\nThe code to be modified follows below"
            f" this blank line:\n\n{context_code}"
        )

        self.llm = create_llm_backend(config.get("llm", {}))

        # Check if the prompt exceeds the model's context window
        context_error = self._check_context_window(
            system_message, user_message
        )
        if context_error:
            return context_error

        self.logger.info("CODE: Prompting LLM for code modification.")
        # self.logger.info(
        #     "CODE: Prompting LLM for code modification.\n\nsystem_message:"
        #     f" {system_message}\n\nuser_message:{user_message}"
        # )

        message = ""
        try:
            llm_response = await self.llm.achat(
                # system_message, user_message
                [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message},
                ],
                stream=False,
            )

            # Check if the response contains a code block for modification
            code_match = re.search(
                r"```(?:[a-z]+\n)?(.*?)```", llm_response, re.DOTALL
            )

            if not code_match:
                # This is a question/answer, not a modification
                return {"success": True, "message": llm_response.strip()}

            # This is a modification request. Extract code and any surrounding text.
            new_code = code_match.group(1).strip()
            # self.logger.info(f"new_code:\n{new_code}")
            message = re.sub(
                r"```(?:[a-z]+\n)?(.*?)```", "", llm_response, flags=re.DOTALL
            ).strip()

        except Exception as e:
            self.logger.exception("Error during LLM call.")
            return {"success": False, "error": f"LLM request failed: {e}"}

        if not new_code or not new_code.strip():
            return {"success": False, "error": "LLM returned empty code."}

        # 5. Replace the old code block with the new one
        try:
            new_code_lines = new_code.splitlines()
            modified_lines = (
                lines[:start_line] + new_code_lines + lines[end_line + 1:]
            )
            modified_content = "\n".join(modified_lines)

        except Exception as e:
            self.logger.exception("Error replacing code in buffer content.")
            return {
                "success": False,
                "error": f"Failed to construct modified file: {e}",
            }

        # 6. Verify syntax of the new code in the context of the full file
        self.logger.info("CODE: Verifying syntax of generated code.")
        verification_error = self._verify_syntax(file_path, modified_content)
        if verification_error:
            self.logger.warning(
                f"Syntax verification failed: {verification_error}"
            )
            return {
                "success": False,
                "error": (
                    f"Generated code has a syntax error:\n{verification_error}"
                ),
            }

        # 7. Write the modified content back to the editor
        self.logger.info("CODE: Writing modified content back to editor.")
        success = await self.editor_client.set_buffer_content(modified_content)
        if success:
            final_message = (
                message
                if message
                else "Code successfully modified in the editor."
            )
            return {
                "success": True,
                "message": final_message,
            }
        else:
            return {
                "success": False,
                "error": (
                    "Failed to write modified content back to Neovim buffer."
                ),
            }
