# Ainara AI Companion Framework Project -- user skill
#
# Ainara Skill: Close Assure Classroom ("close my Assure classroom", "that's enough for today")

"""
Ainara Skill: Close Assure Classroom

Closes the Assure1 Classroom (tools/assureclassroom.py) when the learner is
done for now.

HOW IT CLOSES THE SCREEN
  Like the other classrooms: this skill's small popup card
  (_components/ToolsCloseassureclassroom/index.html) shows a goodbye with
  today's summary, then posts {type: "ainara:close-documents"} to Polaris,
  which closes all popups (the listener already in
  polaris/components/com-ring.js). The result carries issued_at, so replaying
  an old "close" from chat history never closes anything.

REAL PATHS:
    this file   -> ainara/my_skills/tools/closeassureclassroom.py
    popup card  -> ainara/my_skills/_components/ToolsCloseassureclassroom/index.html
    uses        -> ainara/my_skills/tools/assureclassroom.py (same folder)
"""

import importlib.util
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict

from ainara.framework.skill import Skill


def _main():
    path = Path(__file__).with_name("assureclassroom.py")
    spec = importlib.util.spec_from_file_location("_assureclassroom_for_closeassureclassroom", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def lessons_today(progress: Dict[str, Any]) -> int:
    """Lessons finished today (doneAt holds a millisecond timestamp per lesson)."""
    today = date.today()
    n = 0
    for v in (progress.get("doneAt") or {}).values():
        try:
            if datetime.fromtimestamp(float(v) / 1000).date() == today:
                n += 1
        except (TypeError, ValueError, OSError):
            continue
    return n


class ToolsCloseassureclassroom(Skill):
    """Close the Assure1 Classroom (and the other popups on screen) when the
    learner has finished for now. Their progress is already saved."""

    matcher_info = (
        "Use this skill to CLOSE the ASSURE1 CLASSROOM when the learner is finished: '**close my"
        " Assure classroom**', '**close the Assure1 classroom**', 'close the alarm classroom', 'I'm"
        " done with Assure for today', 'that's enough alarm filters for today', 'finish my Assure"
        " lesson', 'you can close it now'. It closes the classroom screen (and the other popups on"
        " screen). Their progress is already saved."
        "\n\nNOT for the coding classroom (close-classroom) or the medical classroom"
        " (close-med-classroom), and NOT for going back to the course page (that is"
        " change-assure-lesson with page = landing)."
        "\n\nKeywords: close Assure classroom, close Assure1, done for today, finish lesson, close screen."
    )

    embeddings_boost_factor = 1.4

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    async def run(self) -> Dict[str, Any]:
        """Close the classroom popup(s) with a short goodbye."""
        self.logger.info("TOOLS_CLOSEASSURECLASSROOM RUN")
        m = _main()
        progress = m.read_json(m.PROGRESS_FILE)
        today = lessons_today(progress)
        name = str((progress.get("profile") or {}).get("name") or "").strip()
        status = m.ToolsAssureclassroom.course_status(progress)
        bits = []
        if today:
            bits.append(f"{today} lesson{'s' if today != 1 else ''} finished today")
        nxt = next((f"next up: {c}, {s.split('next is ')[-1]}" for c, s in status.items() if "next is" in s), None)
        if nxt:
            bits.append(nxt)
        summary = " · ".join(bits)
        return {
            "success": True,
            "view": "close",
            "issued_at": time.time(),
            "name": name,
            "summary": summary,
            "for_ainara": (
                "The Assure1 classroom is closing now and their progress is saved. Say a short, friendly goodbye"
                + (f" to {name}" if name else "")
                + (f", mentioning ONE thing from today ({summary})" if summary else "")
                + ", and that they can say 'open my Assure classroom' to pick up where they left off."
            ),
        }
