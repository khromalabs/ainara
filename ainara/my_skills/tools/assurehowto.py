# Ainara AI Companion Framework Project -- user skill
#
# Ainara Skill: Assure How To -- answer a "how do I ...?" question about Assure1
# with the steps and a diagram ("how do I create a filter?", "why did my alarm disappear?")

"""
Ainara Skill: Assure How To (Assure1 Classroom)

"How do I create a filter?", "how do I set up a new alarm?", "why did my alarm
disappear?", "how do I share a filter with a team?", "which screen do I use?".

The classroom holds prepared answers (howto.json next to the card, written from
the card by the test script): where to click, the steps, how risky it is, a
diagram, and the lesson that practises it. This skill picks the one that fits
the question and, if the classroom is open, shows it on the "How do I...?" page
without reopening the screen. Ainara gets the same steps to talk through.

No prepared answer? Ainara's own short steps (the `steps` argument) are drawn
on the page as a numbered flow diagram, marked as general guidance.

If the classroom is closed, Ainara answers out loud and is told how to open the
page so the diagram can be seen.

REAL PATHS:
    this file   -> ainara/my_skills/tools/assurehowto.py
    uses        -> ainara/my_skills/tools/assureclassroom.py (same folder)
    reads       -> ainara/my_skills/_components/ToolsAssureclassroom/howto.json
"""

import asyncio
import importlib.util
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from ainara.framework.skill import Skill


def _main():
    path = Path(__file__).with_name("assureclassroom.py")
    spec = importlib.util.spec_from_file_location("_assureclassroom_for_assurehowto", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


RISK_SAY = {
    "safe": "safe to do on their own",
    "care": "fine to do, on their own items only",
    "ask": "something to agree with a senior admin first; say so clearly",
}


def split_steps(steps: Optional[str]) -> List[str]:
    """'Open Filters | Clone one | ...' or a numbered / line-separated list -> up to 7 short steps."""
    text = str(steps or "").strip()
    if not text:
        return []
    parts = re.split(r"\s*\|\s*|\n+|\s*;\s*|\s+(?=\d[.)]\s)", text)
    out = [re.sub(r"^\s*(?:step\s*)?\d+[.):]\s*", "", p, flags=re.I).strip() for p in parts]
    return [p[:220] for p in out if p][:7]


class ToolsAssurehowto(Skill):
    """Assure how to: answer a how-do-I question about administering Assure1
    alarms with the steps and a diagram, shown in the Assure1 Classroom."""

    matcher_info = (
        "Use this skill when the user asks HOW TO DO something in ASSURE1 / Unified Assurance alarm"
        " administration, or asks why something happens there: '**how do I create a filter?**',"
        " '**how do I set up a new alarm?**', 'how do I change the severity of an alarm?', 'how do I"
        " share a filter with a team?', 'how do I add a column to the display?', '**why did my alarm"
        " disappear?**', 'why won't this alarm clear?', 'how do I stop duplicate alarms?', 'how do I"
        " create a threshold alarm?', 'how do I search alarm history?', 'which nodes had the most"
        " alarms?', 'why is my search slow?', 'which screen do I use for that?', 'what is safe for me"
        " to change?', '**explain that with a diagram**', 'open the how do I page', and SEARCHING the classroom:"
        " '**search for EventKey**', 'find the lesson on thresholds', 'look up restriction filter'"
        " (search_for). It shows the steps"
        " and a diagram in the Assure1 classroom and gives you the same steps to say."
        "\n\nNOT for marking the task on screen (that is check-my-filter) and NOT for moving between"
        " lessons (change-assure-lesson)."
        "\n\nKeywords: how do I, how to, why, Assure1, alarm, filter, display, rule, severity,"
        " threshold, history, diagram, steps, explain."
    )

    embeddings_boost_factor = 1.4

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    @staticmethod
    async def search(m, text: str, rules: str) -> Dict[str, Any]:
        """'Search for EventKey': show the classroom's search results and read back the best ones."""
        if not m.classroom_on_screen():
            return {"success": False, "classroom_open": False, "searched_for": text, "open_with": f"action = open, page = howto, lesson = {text}",
                    "for_ainara": ("The Assure1 classroom isn't open, so the search can't be shown. Say what you know about"
                                   f" '{text}' in two sentences and offer to open the classroom's search (the Assure classroom"
                                   " capability with action = open, page = howto)." + rules)}
        req = {"id": uuid.uuid4().hex, "at": time.time(), "action": "search", "search": text}
        if not await m.deliver(req):
            return {"success": False, "classroom_open": False, "searched_for": text,
                    "for_ainara": "The classroom screen isn't responding, so it has probably been closed. Offer to reopen it." + rules}
        results: Dict[str, Any] = {}
        end = time.time() + 3
        while time.time() < end:
            await asyncio.sleep(0.2)
            live = m.read_json(m.LIVE_FILE)
            if float(live.get("updated_ts") or 0) >= req["at"] and (live.get("howto") or {}).get("searched_for") == text:
                results = live["howto"]
                break
        nothing = not results or results.get("nothing_found")
        return {"success": True, "classroom_open": True, "searched_for": text, "results": results,
                "for_ainara": ((f"The classroom searched for '{text}' and found nothing. Say so, suggest a simpler word, or answer"
                                " from what you know and say it is general guidance." if nothing else
                                f"The search results for '{text}' are on screen, grouped as how-do-I questions, lessons and key"
                                " terms. In two or three short sentences say what was found: read the meaning if a key term"
                                " matches, name the best question or lesson, and ask which they'd like to open. A how-do-I"
                                " question opens with this capability (question = its wording); a lesson opens with"
                                " change-assure-lesson.") + rules)}

    async def run(
        self,
        question: Annotated[str, "Their question in their own words, e.g. 'how do I create a filter' or 'why did my alarm disappear'. Leave empty only for 'open the how do I page'"] = "",
        steps: Annotated[Optional[str], "ALWAYS include your own short answer as 3 to 6 steps separated by ' | ', each under 12 words, starting with a verb (e.g. 'Open Configuration, Events, Filters | Clone a similar filter | ...'). It is drawn as a diagram when the classroom has no prepared answer. Use only made-up names like TST1_001 or RAN1_001"] = None,
        search_for: Annotated[Optional[str], "ONLY when they ask to SEARCH or LOOK UP a word or topic in the classroom ('search for EventKey', 'find the lesson on thresholds', 'look up restriction filter'): the one to three words to search for. Leave empty for a how-do-I question"] = None,
    ) -> Dict[str, Any]:
        """Answer a how-do-I question with steps and a diagram."""
        self.logger.info(f"TOOLS_ASSUREHOWTO RUN: question={question!r}")
        m = _main()
        rules = m.TALK_RULES + m.SAFETY_RULES
        if search_for and str(search_for).strip():
            return await self.search(m, re.sub(r"\s+", " ", str(search_for)).strip()[:80], rules)
        q = re.sub(r"\s+", " ", str(question or "")).strip()[:160]
        topic = m.howto_find(q) if q else None
        own = split_steps(steps)
        out: Dict[str, Any] = {"success": True, "question": q}
        if topic:
            out["prepared_answer"] = {k: topic.get(k) for k in ("q", "where", "risk", "steps", "note")}
            lesson = topic.get("lesson") or []
            if len(lesson) == 2 and lesson[0] in m.COURSES:
                idx = next((i for i, x in enumerate(m.lesson_index().get(lesson[0], [])) if x.get("id") == lesson[1]), None)
                if idx is not None:
                    out["practise_it_in"] = f"{m.COURSES[lesson[0]]['name']}, lesson {idx + 1}"

        on_screen = m.classroom_on_screen()
        shown = False
        if on_screen:
            req = {"id": uuid.uuid4().hex, "at": time.time(), "action": "howto", "topic": topic["id"] if topic else None, "question": q, "steps": own}
            shown = await m.deliver(req)
        out["classroom_open"] = shown

        if topic:
            how = (f"Answer from prepared_answer in FOUR or five short spoken sentences: where to go ('{topic.get('where')}'), the"
                   " steps in order in your own words (group them, don't read a list), and that this is "
                   + RISK_SAY.get(topic.get("risk"), "something to check first") + ". Mention the note if there is one.")
            if out.get("practise_it_in"):
                how += f" Finish by offering to practise it: {out['practise_it_in']}."
            if shown:
                say = "The steps and a diagram for this are now on the classroom's How-do-I page. " + how + " Point at the diagram ('step three on the screen')."
            else:
                say = (how + " The classroom isn't open, so there is no diagram on screen: after answering, offer to show it, and if they"
                       f" say yes call the Assure classroom capability with action = open, page = howto, lesson = {q or topic.get('q')}.")
        elif not q:
            if shown:
                say = "The How-do-I page is open with its list of questions. Ask what they'd like to know how to do."
            else:
                out["open_with"] = "action = open, page = howto"
                say = "Call the Assure classroom capability NOW with action = open, page = howto to show the How-do-I page."
        else:
            out["your_steps"] = own
            say = ("The classroom has no prepared answer for this, so answer from what you know about Assure1 / Unified"
                   " Assurance in four or five short spoken sentences, and say plainly that it is general guidance they should"
                   " check on their own version. If you are not sure, say so rather than guess; for anything touching rules,"
                   " mechanizations, services or Elasticsearch management, tell them to agree it with a senior admin. ")
            if shown and own:
                say += "Your own steps are now drawn as a flow diagram on the How-do-I page, marked as general guidance: refer to it."
            elif shown:
                say += "The page shows their question but you gave no steps, so there is no diagram."
            else:
                say += "The classroom isn't open, so nothing is on screen."
        out["for_ainara"] = say + rules
        return out
