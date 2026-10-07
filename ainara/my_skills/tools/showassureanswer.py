# Ainara AI Companion Framework Project -- user skill
#
# Ainara Skill: Show Assure Answer -- the model answer in the Assure1 Classroom
# ("show me the answer", "talk me through it", "I give up")

"""
Ainara Skill: Show Assure Answer (Assure1 Classroom)

"Show me the answer", "talk me through it", "explain the answer", "I give up".

The open classroom fills in the model answer (the filter, search or Console
request), runs it so the matching alarms are listed, and shows why it works.
Ainara gets the same answer and reasoning to talk through, piece by piece.

If the classroom is closed, Ainara is told to open it with show_answer = yes.

REAL PATHS:
    this file   -> ainara/my_skills/tools/showassureanswer.py
    uses        -> ainara/my_skills/tools/assureclassroom.py (same folder)
"""

import asyncio
import importlib.util
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from ainara.framework.skill import Skill


def _main():
    path = Path(__file__).with_name("assureclassroom.py")
    spec = importlib.util.spec_from_file_location("_assureclassroom_for_showassureanswer", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class ToolsShowassureanswer(Skill):
    """Show assure answer: reveal the model answer to the task in the Assure1
    Classroom, list the alarms it returns, and have Ainara talk it through."""

    matcher_info = (
        "Use this skill when the learner in the ASSURE1 CLASSROOM wants the answer to the task on"
        " screen: '**show me the answer**', '**talk me through it**', 'explain the answer', 'what's"
        " the right filter?', 'what should the query be?', 'why is that the answer?', 'I give up',"
        " 'just tell me'. The screen fills in the answer and lists the alarms it returns."
        "\n\nNOT for the coding classroom (show-me-the-answer) or the medical classroom"
        " (show-me-the-reasoning). For a hint only, use check-my-filter."
        "\n\nKeywords: show me the answer, talk me through, explain, right filter, right query, Assure"
        " classroom."
    )

    embeddings_boost_factor = 1.4

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    async def run(self) -> Dict[str, Any]:
        """Show the model answer in the open Assure1 classroom."""
        self.logger.info("TOOLS_SHOWASSUREANSWER RUN")
        m = _main()
        rules = m.TALK_RULES + m.SAFETY_RULES
        if not m.classroom_on_screen():
            other = m.other_classroom_on_screen()
            if other:
                return m.wrong_classroom(other, "see the answer")
            return {"success": False, "classroom_open": False, "open_with": "action = open, show_answer = yes",
                    "for_ainara": ("The Assure1 classroom isn't open. If they want the answer to the lesson they were on,"
                                   " call the Assure classroom capability with action = open, lesson = <the lesson they"
                                   " named, if any>, show_answer = yes." + rules)}
        live = m.read_json(m.LIVE_FILE)
        if not live.get("task"):
            return {"success": True, "classroom_open": True, "on_screen": live.get("on_screen"),
                    "for_ainara": ("There's no marked task on screen (course page or sandbox), so there's no answer to show."
                                   " Ask what they'd like to do." + rules)}
        req = {"id": uuid.uuid4().hex, "action": "showme", "at": time.time()}
        delivered = await m.deliver(req)
        if delivered:
            end = time.time() + 2.0
            while time.time() < end:
                await asyncio.sleep(0.2)
                fresh = m.read_json(m.LIVE_FILE)
                if fresh.get("answer_shown"):
                    live = fresh
                    break
        out: Dict[str, Any] = {"success": True, "classroom_open": delivered}
        for k in ("course_name", "lesson_number", "lesson_title", "task", "correct_answer", "why", "last_run", "key_terms"):
            if live.get(k) not in (None, "", [], {}):
                out[k] = live[k]
        out["for_ainara"] = (
            ("The answer is now filled in on screen and the alarms it returns are listed. " if delivered else
             "The screen isn't responding (it may have been closed), so explain from here. ")
            + "Talk it through like a friendly senior NOC engineer: say the answer in words, piece by piece (each"
            " condition and what it keeps or removes), using why. Mention how many alarms it returns from last_run."
            + (" This is the FINAL SHIFT, so showing the answer scores 0 for this step: say so kindly, then tell them to"
               " press Check and say 'next step'." if live.get("final_shift") else
               " Then remind them to press Check so the lesson counts, and ask if it makes sense.") + rules)
        return out
