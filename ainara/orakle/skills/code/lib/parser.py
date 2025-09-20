import os
import logging
import platform
import sys
from typing import Any, Dict, Optional
from pathlib import Path

import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
from tree_sitter import Language, Parser


class NodeNotFoundError(Exception):
    """Raised when a specified node is not found in the AST."""

    pass


class CodeParser:
    """
    A wrapper around the tree-sitter library to parse, find, and manipulate
    nodes in a source code file's Abstract Syntax Tree (AST).
    """

    def __init__(self, grammar_dir: str = "tree-sitter"):
        self.languages: Dict[str, Language] = {}
        self.parsers: Dict[str, Parser] = {}
        self.logger = logging.getLogger(__name__)
        # TODO This is a simplified mapping
        self.extension_map = {
            ".py": "python",
            ".js": "javascript",
        }
        resource_base_dir = self._get_resource_base_dir() / "resources/bin/"
        system = platform.system()
        if system == "Windows":
            self.grammar_path = (
                resource_base_dir / "windows" / grammar_dir
            )
        elif system == "Darwin":  # macOS
            mac_arch = self._get_macos_architecture()
            self.grammar_path = (
                resource_base_dir / f"macos/{mac_arch}" / grammar_dir
            )
        else:  # Linux
            self.grammar_path = (
                resource_base_dir / "linux" / grammar_dir
            )

    def _get_resource_base_dir(self) -> Path:
        """Determine the base directory for resources (project root or MEIPASS)."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            # Running as a bundled app (PyInstaller)
            return Path(sys._MEIPASS)
        else:
            # Running from source
            # __file__ -> lib -> code -> skills -> orakle -> ainara -> repo_root
            return Path(__file__).parent.parent.parent.parent.parent.parent

    def _get_parser(self, file_path: str) -> Optional[Parser]:
        """
        Loads the appropriate pre-compiled grammar for the file extension and
        current platform, then returns a parser.
        """
        lang_name = self.extension_map.get(os.path.splitext(file_path)[1])
        if not lang_name:
            return None

        if lang_name in self.parsers:
            return self.parsers[lang_name]

        # Determine platform-specific library path
        os_name = sys.platform
        arch = platform.machine()

        if os_name == "linux":
            # platform_str = f"linux-{arch}"
            platform_str = "linux"
            lib_ext = "so"
        elif os_name == "win32":
            # Windows arch can be 'AMD64' for x86_64
            # arch = "x86_64" if arch == "AMD64" else arch
            platform_str = "windows"
            lib_ext = "dll"
        elif os_name == "darwin":
            platform_str = f"macos-{arch}"
            lib_ext = "dylib"
        else:
            raise OSError(f"Unsupported operating system: {os_name}")

        lib_path = os.path.join(
            self.grammar_path, f"{lang_name}.{lib_ext}"
        )

        if not os.path.exists(lib_path):
            raise FileNotFoundError(
                f"Pre-compiled grammar for '{lang_name}' on platform '{platform_str}' not found. "
                f"Expected at: {lib_path}"
            )

        if lang_name == "python":
            self.languages[lang_name] = Language(tspython.language())
        elif lang_name == "javascript":
            self.languages[lang_name] = Language(tsjavascript.language())
        parser = Parser(self.languages[lang_name])
        self.parsers[lang_name] = parser
        return parser

    def _get_grammar_lib_path(self, lang_name: str) -> str:
        """Constructs the platform-specific path for a grammar library."""
        os_name = sys.platform
        if os_name == "linux":
            lib_ext = "so"
        elif os_name == "win32":
            lib_ext = "dll"
        elif os_name == "darwin":
            lib_ext = "dylib"
        else:
            return ""  # Unsupported OS

        return os.path.join(self.grammar_path, f"{lang_name}.{lib_ext}")

    def get_supported_extensions(self) -> list[str]:
        """Returns a list of file extensions with available grammar libraries."""
        supported = []
        for ext, lang_name in self.extension_map.items():
            lib_path = self._get_grammar_lib_path(lang_name)
            if lib_path and os.path.exists(lib_path):
                supported.append(ext)
        return supported

    def replace_in_content(self, file_path: str, source_code: str, identifier: str, new_code: str) -> str:
        """Parses source code from a string, finds a node, replaces it, and returns the new source."""
        # 1. Get parser for file_path
        # 2. Parse source_code string to get tree
        # 3. Find node in tree
        # 4. Reconstruct the source code with the node replaced
        raise NotImplementedError("replace_in_content method is not yet implemented.")

    def find_enclosing_function_or_class(
        self, file_path: str, source_code: str, line: int, column: int
    ) -> Optional[Dict[str, Any]]:
        """
        Parses source code and finds the enclosing function or class at a given
        line and column.

        Returns a dictionary with the node's text and its start/end byte
        offsets, or None.
        """
        parser = self._get_parser(file_path)
        if not parser:
            self.logger.error(f"Parser {file_path} not found")
            return None

        tree = parser.parse(bytes(source_code, "utf8"))
        root_node = tree.root_node

        # Neovim is 1-based, tree-sitter is 0-based
        cursor_point = (line - 1, column)

        # Language-specific node types to consider as top-level blocks
        # This could be expanded for more languages.
        lang_name = self.extension_map.get(os.path.splitext(file_path)[1])
        if lang_name == "python":
            relevant_node_types = {"function_definition", "class_definition"}
        else:
            # Default or for other languages like JS
            relevant_node_types = {
                "function_declaration",
                "class_declaration",
                "method_definition",
            }

        best_match = None

        def traverse(node):
            nonlocal best_match
            # Check if the current node contains the cursor
            if node.start_point <= cursor_point <= node.end_point:
                # If it's a relevant type, it's a potential candidate
                if node.type in relevant_node_types:
                    best_match = node

                # Continue searching deeper for a more specific (smaller) node
                for child in node.children:
                    traverse(child)

        traverse(root_node)

        if best_match:
            return {
                "start_line": best_match.start_point[0],
                "end_line": best_match.end_point[0],
            }

        return None

    # Methods not fully implemented yet

    def _find_node_by_identifier(self, root_node, identifier: str):
        """
        Traverses the AST to find a node matching the identifier.
        Note: This is a placeholder for the actual AST traversal logic.
        """
        # Placeholder: Implement traversal logic here.
        # This could involve querying the tree for function_definition nodes,
        # class_definition nodes, etc., and matching their names.
        raise NotImplementedError("AST node search is not yet implemented.")

    def extract(self, file_path: str, identifier: str) -> str:
        """Reads a file, finds a node, and returns its source text."""
        # Placeholder for full implementation
        # 1. Get parser for file_path
        # 2. Read file content
        # 3. Parse content to get tree
        # 4. Find node in tree using identifier
        # 5. Return node.text
        raise NotImplementedError("extract method is not yet implemented.")

    def replace(self, file_path: str, identifier: str, new_code: str) -> None:
        """Reads a file, finds a node, and replaces its content in the file."""
        # Placeholder for full implementation
        # 1. Read file content into a mutable buffer (e.g., list of lines)
        # 2. Get parser, parse content, find node
        # 3. Get start and end byte/line information from the node
        # 4. Replace the corresponding text in the buffer
        # 5. Write the modified buffer back to the file
        raise NotImplementedError("replace method is not yet implemented.")

    def extract_from_content(self, file_path: str, source_code: str, identifier: str) -> str:
        """Parses source code from a string, finds a node, and returns its text."""
        # 1. Get parser for file_path (to know the language)
        # 2. Parse source_code string to get tree
        # 3. Find node in tree using identifier
        # 4. Return node.text
        raise NotImplementedError("extract_from_content method is not yet implemented.")
