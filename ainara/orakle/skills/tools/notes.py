"""Skill for creating, reading, and managing quick text notes"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional

from ainara.framework.config import get_data_dir
from ainara.framework.skill import Skill

_DEFAULT_NOTES_DIR = get_data_dir() / "notes"


class ToolsNotes(Skill):
    """Create, read, and manage quick text notes"""

    embeddings_boost_factor = 2.0

    matcher_info = (
        "Use this skill when the user wants to add, save, write, or jot down a note "
        "or reminder, or when they want to read, list, show, or clear their notes. "
        "This skill MUST be used for any request containing 'add a note', 'take a note', "
        "'write this down', 'jot this down', 'save a note', 'show my notes', "
        "'read my notes', 'list my notes', or 'clear my notes'.\n\n"
        "Examples include: 'add a note: buy milk', 'take a note about the meeting', "
        "'write this down for me', 'what notes do I have?', 'show me my notes', "
        "'clear all my notes'.\n\n"
        "Keywords: note, notes, write down, jot, reminder, save note, add note, "
        "take note, read notes, list notes, show notes, clear notes, journal, memo."
    )

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        # Use ConfigManager when available, fall back to default path
        try:
            from ainara.framework.config import ConfigManager
            cfg = ConfigManager()
            self.notes_dir = Path(cfg.get("skills.notes.directory", str(_DEFAULT_NOTES_DIR)))
        except Exception:
            self.notes_dir = _DEFAULT_NOTES_DIR
        self.notes_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_file(self, filename: Optional[str]) -> Path:
        name = (filename or "notes").strip()
        if not name.endswith(".md"):
            name += ".md"
        return self.notes_dir / name

    async def run(
        self,
        action: Annotated[
            Literal["add", "read", "list", "clear"],
            "Operation to perform: add a new note, read all notes, list note entries, or clear the notes file",
        ],
        content: Annotated[
            Optional[str],
            "The note text to save (required for 'add')",
        ] = None,
        filename: Annotated[
            Optional[str],
            "Notes file name without extension, defaults to 'notes'",
        ] = None,
    ) -> Dict[str, Any]:
        """Create, read, and manage quick text notes stored as markdown files.

        Notes are stored under the platform data directory (notes/) as plain markdown files.
        Each entry is prefixed with a timestamp header.

        Examples:
            action='add', content='Buy milk' → appends a timestamped note
            action='read' → returns the full notes file as a string
            action='list' → returns a structured list of note entries
            action='clear' → empties the notes file
        """
        notes_file = self._resolve_file(filename)

        if action == "add":
            return await self._add(notes_file, content)
        elif action == "read":
            return await self._read(notes_file)
        elif action == "list":
            return await self._list(notes_file)
        elif action == "clear":
            return await self._clear(notes_file)
        else:
            return {
                "success": False,
                "error": f"Unknown action '{action}'. Use: add, read, list, clear",
            }

    async def _add(self, notes_file: Path, content: Optional[str]) -> Dict[str, Any]:
        if not content or not content.strip():
            return {"success": False, "error": "content is required for 'add'"}
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"## {timestamp}\n\n{content.strip()}\n\n"
        try:
            with notes_file.open("a", encoding="utf-8") as f:
                f.write(entry)
            return {
                "success": True,
                "message": f"Note saved to {notes_file.name}",
                "timestamp": timestamp,
                "content": content.strip(),
            }
        except Exception as e:
            self.logger.error(f"{self.name} add failed: {e}")
            return {"success": False, "error": str(e)}

    async def _read(self, notes_file: Path) -> Dict[str, Any]:
        if not notes_file.exists():
            return {"success": True, "content": "", "message": "No notes yet."}
        try:
            content = notes_file.read_text(encoding="utf-8").strip()
            if not content:
                return {"success": True, "content": "", "message": "Notes file is empty."}
            return {"success": True, "content": content, "file": str(notes_file)}
        except Exception as e:
            self.logger.error(f"{self.name} read failed: {e}")
            return {"success": False, "error": str(e)}

    async def _list(self, notes_file: Path) -> List[Dict[str, Any]]:
        if not notes_file.exists():
            return {"success": True, "notes": [], "count": 0}
        try:
            raw = notes_file.read_text(encoding="utf-8")
            entries = re.split(r"^## ", raw, flags=re.MULTILINE)
            notes = []
            for entry in entries:
                entry = entry.strip()
                if not entry:
                    continue
                lines = entry.split("\n", 1)
                notes.append({
                    "timestamp": lines[0].strip(),
                    "content": lines[1].strip() if len(lines) > 1 else "",
                })
            return {"success": True, "notes": notes, "count": len(notes)}
        except Exception as e:
            self.logger.error(f"{self.name} list failed: {e}")
            return {"success": False, "error": str(e)}

    async def _clear(self, notes_file: Path) -> Dict[str, Any]:
        try:
            notes_file.write_text("", encoding="utf-8")
            return {"success": True, "message": f"{notes_file.name} cleared."}
        except Exception as e:
            self.logger.error(f"{self.name} clear failed: {e}")
            return {"success": False, "error": str(e)}
