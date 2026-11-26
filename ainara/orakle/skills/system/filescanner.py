# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html for details)
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

import fnmatch
import os
import re
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional

from pathspec import GitIgnoreSpec

from ainara.framework.redaction import redact_text
from ainara.framework.skill import Skill

# Directories never scanned, by name (applies at any depth).
DEFAULT_EXCLUDED_DIRS = frozenset(
    [
        ".git", ".hg", ".svn", "__pycache__", ".mypy_cache",
        ".pytest_cache", ".ruff_cache", ".tox", ".idea", ".vscode",
        "node_modules", ".venv", "venv", "env", ".next", "dist",
        "build", "target", "coverage", "__macosx",
    ]
)

# Well-known lock/bulk files excluded even though they are plain text.
DEFAULT_EXCLUDED_FILES = frozenset(
    [
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "poetry.lock", "Pipfile.lock", "uv.lock", "Cargo.lock",
    ]
)

# Extensions skipped without sniffing (never useful as text matches).
BINARY_EXTS = frozenset(
    [
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".icns",
        ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
        ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a",
        ".mp3", ".mp4", ".wav", ".flac", ".ogg", ".webm", ".mkv", ".avi",
        ".woff", ".woff2", ".ttf", ".otf", ".eot", ".psd", ".ai",
        ".pyc", ".pyo", ".class", ".jar", ".wasm", ".db", ".sqlite",
        ".sqlite3", ".onnx", ".pt", ".pth", ".bin", ".model",
    ]
)

# Files larger than this are skipped for content search.
MAX_SEARCH_FILE_BYTES = 1_000_000
# Hard ceiling for search results returned in one call.
MAX_SEARCH_RESULTS = 200
# Directories shown in the overview map, most populated first.
MAX_OVERVIEW_DIRS = 80
# Entries shown in a one-level directory listing.
MAX_LIST_ENTRIES = 200
# Byte sniff window for binary detection.
SNIFF_BYTES = 8192


def _expand_glob_braces(glob: str) -> List[str]:
    """Expand ``{a,b}`` alternations, which fnmatch does not support.

    Selectors routinely emit brace globs (``*.{py,md}``); without this
    they silently match nothing.
    """
    match = re.search(r"\{([^{}]+)\}", glob)
    if not match:
        return [glob]
    expanded: List[str] = []
    prefix, suffix = glob[: match.start()], glob[match.end():]
    for alt in match.group(1).split(","):
        expanded.extend(_expand_glob_braces(prefix + alt + suffix))
    return expanded


class SystemFilescanner(Skill):
    """Explore and analyze a directory tree containing many files.

    Maps the shape of a folder or project (file-type breakdown, directory
    structure), searches file CONTENTS across the whole tree (literal
    text or regular expression), lists the immediate contents of one
    directory, and checks whether a specific path exists.

    Behavioral rules:
      - Use 'overview' first when the tree is unknown: it shows the shape
        of the collection and which file types dominate, so later reads
        can be targeted instead of blind.
      - Use 'search' to locate where something appears across many files;
        results are capped: if 'truncated' is true, narrow the query
        (add a glob filter or a more specific pattern) instead of paging
        blindly.
      - Use 'list' for the immediate contents of a single directory;
        'overview' already covers the whole tree, so avoid both for the
        same question.
      - Read the matching regions afterwards with the file read skill,
        using offset/limit to request slices rather than whole large
        files.
      - Hidden directories (starting with '.'), dependency/cache/build
        directories and lock files are excluded by default; the root
        .gitignore (if present) is honored too, so a code project is
        scanned the way a developer sees it.
      - Binary files are skipped; only text content is searched.
      - Search matches are mechanically redacted when they contain
        secret-shaped text (API keys, tokens, passwords) before leaving
        the skill; over-redaction on look-alike lines is the intended
        fail-safe direction. Patterns are configurable via the
        security.redaction config keys.

    This skill is read-only: it never modifies, moves or deletes files.
    """

    matcher_info = (
        "Explore and analyze a folder or project that contains many files:"
        " show its structure and file-type breakdown, search the CONTENTS"
        " of all files in the tree for a text or pattern reporting file"
        " and line number, list the immediate contents of one directory,"
        " or check whether a specific path exists. Built for whole"
        " collections of files, not single known files. Examples include:"
        " 'explain how this project is organized', 'where is the routing"
        " implemented in this codebase?', 'find every mention of invoices"
        " across my notes folder', 'what kinds of files are in this"
        " directory?', 'search this repository for handleAuth', 'what is"
        " in this folder?', 'does notes/2024 exist?'. Use the file read"
        " skill instead to read one specific file by exact path, and the"
        " file finder skill to locate a single file by name. Keywords:"
        " analyze, scan, overview, structure, codebase, project,"
        " repository, folder, directory, tree, list, contents, exists,"
        " across files, contents search, grep, contains, implemented,"
        " organized."
    )

    def __init__(self):
        super().__init__()
        self._gitignore_cache: Dict[str, Optional[GitIgnoreSpec]] = {}

    async def run(
        self,
        action: Annotated[
            Literal["overview", "search", "list", "exists"],
            "'overview' maps the whole tree: file counts, total size,"
            " file-type breakdown and directory structure. 'search' looks"
            " inside the files and returns every match with file, line"
            " number and text. 'list' shows the immediate contents of one"
            " directory. 'exists' checks whether the path exists and"
            " whether it is a file or a directory.",
        ],
        path: Annotated[
            str,
            "Directory to analyze, or the exact path to check for the"
            " 'exists' action",
        ],
        query: Annotated[
            Optional[str],
            "Text or regular expression to find inside the files"
            " (search action only)",
        ] = None,
        is_regex: Annotated[
            Optional[bool],
            "Treat 'query' as a regular expression instead of literal text"
            " (search action only, default False)",
        ] = False,
        case_sensitive: Annotated[
            Optional[bool],
            "Case-sensitive matching (search action only, default False)",
        ] = False,
        glob: Annotated[
            Optional[str],
            "Only include files whose relative path matches this wildcard"
            " pattern, e.g. '*.py' or 'docs/*.md' (search and list"
            " actions only)",
        ] = None,
        max_results: Annotated[
            Optional[int],
            "Maximum number of search matches to return (search action only,"
            " default 100, capped at 200)",
        ] = 100,
    ) -> Dict[str, Any]:
        """Scan a directory tree: overview, contents search, list or exists"""
        path_ = Path(path).expanduser()
        if action == "exists":
            return await self._check_exists(path_)
        if not path_.is_dir():
            return {
                "success": False,
                "error": f"Not a directory: {path_}",
            }

        if action == "overview":
            return await self._overview(path_)
        if action == "search":
            if not query:
                return {
                    "success": False,
                    "error": "The 'query' parameter is required for search",
                }
            return await self._search(path_, query, is_regex, case_sensitive,
                                      glob, max_results)
        if action == "list":
            return await self._list_dir(path_, glob)
        return {"success": False, "error": f"Unsupported action: {action}"}

    # ------------------------------------------------------------------
    # Tree walking (shared)
    # ------------------------------------------------------------------

    def _gitignore_for(self, directory: Path) -> Optional[GitIgnoreSpec]:
        """Compile the .gitignore of a directory, cached per directory."""
        key = str(directory)
        if key in self._gitignore_cache:
            return self._gitignore_cache[key]
        spec = None
        gi = directory / ".gitignore"
        if gi.is_file():
            try:
                spec = GitIgnoreSpec.from_lines(
                    gi.read_text(encoding="utf-8", errors="replace")
                    .splitlines()
                )
            except Exception:
                spec = None
        self._gitignore_cache[key] = spec
        return spec

    def _is_excluded_dir(self, name: str) -> bool:
        return name in DEFAULT_EXCLUDED_DIRS or (
            name.startswith(".") and name not in (".", "..")
        )

    def _walk_files(
        self, root: Path
    ):
        """Yield text candidate files under root, relative Path objects.

        Excludes hidden dirs, well-known noise dirs and lock files,
        honors .gitignore files, and skips binaries by extension or
        content sniff.
        """
        root_spec = self._gitignore_for(root)
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            current = Path(dirpath)

            # Prune excluded/hidden directories in place.
            dirnames[:] = sorted(
                d for d in dirnames if not self._is_excluded_dir(d)
            )

            # Nested .gitignore files refine the parent spec.
            spec = root_spec
            if current != root:
                local_spec = self._gitignore_for(current)
                if local_spec is not None:
                    spec = (
                        local_spec
                        if root_spec is None
                        else root_spec + local_spec
                    )

            for fname in sorted(filenames):
                if fname in DEFAULT_EXCLUDED_FILES:
                    continue
                fpath = current / fname
                rel = fpath.relative_to(root)
                if spec is not None and spec.match_file(rel.as_posix()):
                    continue
                if fpath.suffix.lower() in BINARY_EXTS:
                    continue
                yield fpath, rel

    @staticmethod
    def _looks_binary(fpath: Path) -> bool:
        try:
            with open(fpath, "rb") as fh:
                return b"\0" in fh.read(SNIFF_BYTES)
        except OSError:
            return True

    # ------------------------------------------------------------------
    # overview action
    # ------------------------------------------------------------------

    async def _overview(self, root: Path) -> Dict[str, Any]:
        files = 0
        total_bytes = 0
        by_ext: Dict[str, Dict[str, int]] = {}
        files_per_dir: Dict[str, int] = {}
        top_level: List[str] = []
        truncated = False

        for fpath, rel in self._walk_files(root):
            if self._looks_binary(fpath):
                continue
            files += 1
            try:
                size = fpath.stat().st_size
            except OSError:
                size = 0
            total_bytes += size
            ext = fpath.suffix.lower() or "(no extension)"
            entry = by_ext.setdefault(ext, {"files": 0, "bytes": 0})
            entry["files"] += 1
            entry["bytes"] += size
            parent = rel.parent.as_posix()
            files_per_dir[parent] = files_per_dir.get(parent, 0) + 1

        # Root entries: the shallow map the agent orients itself with.
        try:
            for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
                if self._is_excluded_dir(child.name) or (
                    child.is_dir() and child.name.startswith(".")
                ):
                    continue
                top_level.append(
                    child.name + ("/" if child.is_dir() else "")
                )
        except OSError:
            pass

        # Compact per-directory map: most populated directories first.
        # A flat list of every file path would flood the agent context
        # with tens of KB for medium-sized trees; directories-with-counts
        # carry the same orientation value at a fraction of the size.
        directories = {
            d: n
            for d, n in sorted(
                files_per_dir.items(), key=lambda kv: -kv[1]
            )[:MAX_OVERVIEW_DIRS]
        }
        truncated = len(files_per_dir) > len(directories)

        languages = {
            ext: entry
            for ext, entry in sorted(
                by_ext.items(), key=lambda kv: kv[1]["files"], reverse=True
            )
        }

        result = {
            "success": True,
            "root": str(root),
            "summary": {
                "files": files,
                "directories": len(files_per_dir),
                "total_bytes": total_bytes,
            },
            "file_types": languages,
            "top_level": top_level,
            "directories": directories,
            "truncated": truncated,
        }
        if truncated:
            result["notes"] = [
                "Directory map capped at"
                f" {MAX_OVERVIEW_DIRS} entries (most populated first); use"
                " the search action to locate specific content."
            ]
        return result

    # ------------------------------------------------------------------
    # search action
    # ------------------------------------------------------------------

    async def _search(
        self,
        root: Path,
        query: str,
        is_regex: Optional[bool],
        case_sensitive: Optional[bool],
        glob: Optional[str],
        max_results: Optional[int],
    ) -> Dict[str, Any]:
        flags = 0 if case_sensitive else re.IGNORECASE
        if is_regex:
            try:
                pattern = re.compile(query, flags)
            except re.error as e:
                return {
                    "success": False,
                    "error": f"Invalid regular expression: {e}",
                }
        else:
            pattern = re.compile(re.escape(query), flags)

        glob_patterns = (
            _expand_glob_braces(glob) if glob else None
        )
        limit = min(int(max_results or 100), MAX_SEARCH_RESULTS)
        matches: List[Dict[str, Any]] = []
        files_searched = 0
        truncated = False

        for fpath, rel in self._walk_files(root):
            if glob_patterns and not any(
                fnmatch.fnmatch(rel.as_posix(), g) for g in glob_patterns
            ):
                continue
            try:
                if fpath.stat().st_size > MAX_SEARCH_FILE_BYTES:
                    continue
            except OSError:
                continue
            if self._looks_binary(fpath):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            files_searched += 1
            for lineno, line in enumerate(
                text.splitlines(), start=1
            ):
                if pattern.search(line):
                    matches.append(
                        {
                            "file": rel.as_posix(),
                            "line": lineno,
                            "text": redact_text(line.strip()[:200]),
                        }
                    )
                    if len(matches) >= limit:
                        truncated = True
                        break
            if truncated:
                break

        result = {
            "success": True,
            "query": query,
            "matches": matches,
            "count": len(matches),
            "files_searched": files_searched,
            "truncated": truncated,
        }
        if truncated:
            result["notes"] = [
                "Search stopped after reaching the result cap; narrow the"
                " query or add a glob filter to get complete results."
            ]
        elif not files_searched and glob_patterns:
            result["notes"] = [
                "No files matched the glob filter, so nothing was searched;"
                " the empty result reflects the filter, not the content."
                " Simplify or drop the glob and search again."
            ]
        return result

    # ------------------------------------------------------------------
    # list / exists actions
    # ------------------------------------------------------------------

    async def _list_dir(
        self, root: Path, glob: Optional[str]
    ) -> Dict[str, Any]:
        """List the immediate children of one directory (one level only)."""
        entries: List[Dict[str, Any]] = []
        truncated = False
        try:
            children = sorted(
                root.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
            )
        except OSError as e:
            return {"success": False, "error": str(e)}

        for child in children:
            name = child.name
            if (
                name in DEFAULT_EXCLUDED_DIRS
                or (child.is_dir() and name.startswith("."))
            ):
                continue
            rel_child = child.relative_to(root)
            rel_posix = rel_child.as_posix()
            if glob and not fnmatch.fnmatch(rel_posix, glob) and \
                    not fnmatch.fnmatch(name, glob):
                continue
            spec = self._gitignore_for(root)
            if spec is not None and spec.match_file(rel_posix):
                continue
            entry: Dict[str, Any] = {
                "name": name,
                "type": "dir" if child.is_dir() else "file",
            }
            if child.is_file():
                try:
                    entry["size"] = child.stat().st_size
                except OSError:
                    entry["size"] = 0
            entries.append(entry)
            if len(entries) >= MAX_LIST_ENTRIES:
                truncated = True
                break

        result = {
            "success": True,
            "path": str(root),
            "entries": entries,
            "count": len(entries),
            "truncated": truncated,
        }
        if truncated:
            result["notes"] = [
                "Listing capped; use a glob filter or the overview action"
                " to narrow it down."
            ]
        return result

    async def _check_exists(self, path: Path) -> Dict[str, Any]:
        """Check whether a specific path exists and what it is."""
        return {
            "success": True,
            "path": str(path),
            "exists": path.exists(),
            "is_file": path.is_file() if path.exists() else None,
            "is_dir": path.is_dir() if path.exists() else None,
        }
