# Ainara AI Companion Framework Project -- user skill
#
# Ainara Skill: Check My Filter -- Ainara looks at the learner's work in the
# open Assure1 Classroom ("check my filter", "is it Severity equals 5?", "give me a hint")

"""
Ainara Skill: Check My Filter (Assure1 Classroom)

"Check my filter", "check my query", "am I right?", "is it Severity equals 5
and Ack equals 0?", "run Node like RAN1", "give me a hint", "I'm stuck", "what
alarms did that return?", "why is that row there?".

Ainara can't see the screen, so this reads what the open classroom reports in
~/.ainara_assure/live.json: the task, what the learner has typed or picked,
the alarms their last Run returned (or its error), tries, whether they've had
a hint, and the model answer (for Ainara only -- she coaches towards it).

A SPOKEN answer is passed to the screen, which types it in, runs it against
the dummy alarms and marks it exactly like a typed one, so the alarms appear
on screen and progress stays right. In the sandbox a spoken query is just run.

REAL PATHS:
    this file   -> ainara/my_skills/tools/checkmyfilter.py
    uses        -> ainara/my_skills/tools/assureclassroom.py (same folder)
    reads       -> ~/.ainara_assure/live.json      writes -> ~/.ainara_assure/request.json
"""

import asyncio
import importlib.util
import logging
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict, Optional

from ainara.framework.skill import Skill


def _main():
    path = Path(__file__).with_name("assureclassroom.py")
    spec = importlib.util.spec_from_file_location("_assureclassroom_for_checkmyfilter", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


YES = ("yes", "true", "1", "y", "please")
LANGS = {"sql": "sql", "filter": "sql", "kql": "kql", "discover": "kql", "es": "es", "console": "es", "elasticsearch": "es", "json": "es"}

TUTOR_RULES = (
    " HOW TO TUTOR: be a friendly senior NOC engineer. Say back what they wrote in a few words so"
    " they know you saw it. If it's right, praise the specific thing they got right and add one"
    " real-shift reason it matters. If it's wrong, don't give the answer: use last_check and last_run"
    " (how many alarms came back, which rows are extra or missing, or the error text) to point at"
    " the ONE thing to change. Hint ladder -- 1st miss, a question that points at the idea; 2nd miss,"
    " the hint; 3rd miss, offer to show the answer (show-assure-answer). Never read out"
    " correct_answer unless they ask for the answer."
)


class ToolsCheckmyfilter(Skill):
    """Check my filter: see the learner's work in the Assure1 Classroom, run or
    mark a spoken filter or query, give a hint, or explain the alarms on screen."""

    matcher_info = (
        "Use this skill when the learner in the ASSURE1 CLASSROOM wants their work looked at or"
        " needs help with the task on screen: '**check my filter**', '**check my query**', 'check my"
        " answer' (when the Assure classroom is open), '**am I right?**', '**is it Severity equals 5"
        " and Ack equals 0?**', 'the answer is B', 'run Node like RAN1 percent', 'try Severity greater"
        " than 3', '**give me a hint**', 'I'm stuck', 'what does this task mean?', 'what alarms did"
        " that return?', 'why is that alarm in the list?', 'what does this error mean?', 'can you see"
        " my filter?'. It reads the open classroom, so never ask them to paste or read anything out."
        "\n\nNOT for the coding classroom (check-my-code) or the medical classroom (check-my-answer)."
        " For 'show me the answer' use show-assure-answer."
        "\n\nKeywords: check my filter, check my query, am I right, hint, stuck, alarms returned,"
        " Assure classroom, SQL filter, KQL, console query."
    )

    embeddings_boost_factor = 1.4

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    @staticmethod
    async def _send(m, action: str, **extra) -> Optional[Dict[str, Any]]:
        """Send a request to the open screen; None if no screen picked it up."""
        req = {"id": uuid.uuid4().hex, "action": action, "at": time.time(), **extra}
        return req if await m.deliver(req) else None

    @staticmethod
    async def _wait_for(m, test, seconds: float = 3.0) -> Optional[Dict[str, Any]]:
        end = time.time() + seconds
        while time.time() < end:
            await asyncio.sleep(0.2)
            live = m.read_json(m.LIVE_FILE)
            if live and test(live):
                return live
        return None

    @staticmethod
    def _task_view(live: Dict[str, Any]) -> Dict[str, Any]:
        keys = ("course_name", "lesson_number", "lesson_title", "is_project", "task", "learner_answer", "last_run",
                "attempts", "hint_seen", "answer_shown", "last_check", "correct_answer", "why", "hint", "key_terms",
                "language", "final_shift", "recap", "extra_practice", "ainara_just_said_on_screen")
        out = {k: live[k] for k in keys if live.get(k) not in (None, "", [], {})}
        if isinstance(out.get("last_check"), dict):
            out["last_check"] = {k: v for k, v in out["last_check"].items() if k != "at"}
        return out

    async def run(
        self,
        spoken_answer: Annotated[Optional[str], "Their answer if they SAID it rather than doing it on screen. A filter or search is written as real syntax on one line: SQL like \"Severity = 5 AND Ack = 0\" or \"Node LIKE 'RAN1%'\"; KQL like 'Node : RAN1_* and Severity >= 4'; a Console request as 'GET eventanalytics-*/_search' followed by the whole JSON body. Multiple choice: the letter ('B') or their words. Display task: the columns and sort as said ('Severity, LastReported, Count, Node and Summary, sorted by Severity descending'). EventKey or clear-pairing task: the fields as said ('Node, SubNode and EventType'). Rule task: what the rule should do as said ('match Rectifier fail, severity major, event type powerFail, key node subnode and event type'). Threshold task: as said ('above 85 percent for 3 polls in a row, major'). Pick-a-row task: the node and sub-node ('RAN1_003 Link-1'). Operator-tools task: the action and the alarm ('acknowledge TST1_001 Port-3 and take ownership', 'add a journal note saying checking with the field team'). Leave empty for 'check my filter' / 'check my answer': the screen's Check is then pressed for them"] = None,
        wants_hint: Annotated[Optional[str], "'yes' if they asked for a hint, said they're stuck, or asked for help"] = None,
        question: Annotated[Optional[str], "Their question about the task, the alarms listed or an error, if they asked one"] = None,
        language: Annotated[Optional[str], "Sandbox only, if they said which: 'sql' (filter on the live list), 'kql' (Discover) or 'console' (Elasticsearch)"] = None,
    ) -> Dict[str, Any]:
        """Look at the learner's work in the open Assure1 classroom."""
        self.logger.info(f"TOOLS_CHECKMYFILTER RUN: spoken={spoken_answer!r} hint={wants_hint} q={question!r}")
        m = _main()
        rules = m.TALK_RULES + m.SAFETY_RULES
        if not m.classroom_on_screen():
            other = m.other_classroom_on_screen()
            if other:
                return m.wrong_classroom(other, "check their work")
            return {"success": False, "classroom_open": False,
                    "for_ainara": ("The Assure1 classroom isn't open, so there's no work to see. Offer to open it (the"
                                   " Assure classroom capability); if they asked a general question, answer it briefly." + rules)}
        live = m.read_json(m.LIVE_FILE)
        on = live.get("on_screen", "")
        if on == "the choose-a-course landing page" or not live:
            return {"success": True, "classroom_open": True, "on_screen": "the course page", "courses": live.get("courses"),
                    "for_ainara": "They're on the course page, so there's no task yet. Help them pick a course." + rules}

        said = str(spoken_answer or "").strip()
        if on == "the sandbox":
            out: Dict[str, Any] = {"success": True, "classroom_open": True, "on_screen": "the sandbox"}
            if said:
                req = await self._send(m, "run", answer=said[:1500], language=LANGS.get(str(language or "").strip().lower()))
                if req:
                    after = await self._wait_for(m, lambda d: float(d.get("updated_ts") or 0) >= req["at"] and d.get("learner_answer") == said[:1500], 2.5)
                    live = after or m.read_json(m.LIVE_FILE)
            out.update(self._task_view(live))
            out["for_ainara"] = (("You ran what they said in the sandbox. " if said else "They're in the sandbox (free practice, nothing is marked). ")
                                 + "Tell them what last_run shows: how many alarms came back and one thing worth noticing, or"
                                 " explain the error in plain words and how to fix it."
                                 + (f" They also asked: '{question}'." if question else "") + rules)
            return out

        if on == "the recap result":
            return {"success": True, "classroom_open": True, "on_screen": on, "result": live.get("result"),
                    "for_ainara": ("The quick recap is finished and its result is on screen. Tell them the score and ONE lesson worth"
                                   " revisiting (result.revisit), or that it has all stuck, and offer another recap"
                                   " (change-assure-lesson, lesson = retake) or to carry on with the course." + rules)}
        if on == "the final shift result":
            return {"success": True, "classroom_open": True, "on_screen": on, "result": live.get("result"),
                    "for_ainara": ("The final shift is finished and its result is on screen. Tell them the score and whether they"
                                   " passed (70 of 100), name ONE step to revisit if any lost points, and offer to take it again"
                                   " (change-assure-lesson, lesson = retake). If they passed, mention the certificate." + rules)}
        if live.get("recap"):
            rules = (" RECAP QUIZ: five scored questions from finished lessons. Don't volunteer help; a hint costs 5 points."
                     " When a question is marked right, tell them to say 'next step'.") + rules
        elif isinstance(live.get("extra_practice"), dict) and live["extra_practice"].get("on_now", 0) < live["extra_practice"].get("tasks", 0):
            rules = (" When this task is marked right you may offer more practice on the same idea: they can say 'give me"
                     " another one' (change-assure-lesson, lesson = more).") + rules
        if live.get("final_shift"):
            rules = (" FINAL SHIFT: this is the scored assessment. A hint or a second try costs 5 points and Show answer"
                     " scores 0 for the step; if they ask for a hint, give it but say what it cost. Don't volunteer help."
                     " When a step is marked right, tell them to say 'next step'.") + rules
        if not live.get("task"):
            return {"success": True, "classroom_open": True, "on_screen": on, "lesson_title": live.get("lesson_title"),
                    "for_ainara": "There's no task showing right now. Ask what they need." + rules}

        out = {"success": True, "classroom_open": True}
        if str(wants_hint or "").strip().lower() in YES and not said:
            if not await self._send(m, "hint"):
                return {"success": False, "classroom_open": False, **self._task_view(live),
                        "for_ainara": ("The classroom screen isn't responding, so it has probably been closed. Give the hint"
                                       " from what you know, and offer to reopen it with the Assure classroom capability." + rules)}
            live = await self._wait_for(m, lambda d: d.get("hint_seen"), 1.5) or live
            out.update(self._task_view(live))
            tries = int(live.get("attempts") or 0)
            level = ("a guiding question that points at the key idea" if tries == 0 else
                     "the hint, in your own words" if tries < 2 else
                     "the hint plus the first part of the answer, then ask if they'd like to see the rest")
            out["for_ainara"] = (f"The hint is now open on screen too. Give {level}. Don't give the whole answer."
                                 + (f" They also asked: '{question}'." if question else "") + TUTOR_RULES + rules)
            return out

        if said:
            req = await self._send(m, "answer", answer=said[:1500])
            if not req:
                return {"success": False, "classroom_open": False, "spoken_answer": said, **self._task_view(live),
                        "for_ainara": ("The classroom screen isn't responding, so it has probably been closed. Tell them"
                                       " whether what they said matches correct_answer, then offer to reopen it with the"
                                       " Assure classroom capability." + TUTOR_RULES + rules)}
            after = await self._wait_for(
                m, lambda d: isinstance(d.get("last_check"), dict) and float(d["last_check"].get("at") or 0) / 1000 >= req["at"] - 0.5)
            if after:
                out.update(self._task_view(after))
                ok = bool(after["last_check"].get("correct"))
                out["for_ainara"] = (
                    f"They said '{said}'. The screen typed it in, ran it and marked it "
                    + ("RIGHT; the matching alarms are listed on screen. " if ok else f"not right yet (attempt {after.get('attempts')}). ")
                    + "The screen already shows its own feedback, so don't repeat it word for word; add your own touch"
                    " in one or two sentences." + TUTOR_RULES + rules)
                return out
            out.update(self._task_view(m.read_json(m.LIVE_FILE)))
            out["spoken_answer"] = said
            out["for_ainara"] = (f"They said '{said}', but the screen couldn't use it for this task (or didn't answer in"
                                 " time). Compare it yourself with correct_answer and tell them if they're on track, then"
                                 " ask them to enter it on screen so it counts." + TUTOR_RULES + rules)
            return out

        # "check my filter" with nothing said: press the screen's Check for them, so what they
        # typed or picked is run, the alarms are listed and the lesson is marked.
        lc = live.get("last_check") or {}
        ans = str(live.get("learner_answer") or "")
        if not question and ans and not ans.startswith("(") and not (lc.get("correct") and lc.get("answer") == ans):
            req = await self._send(m, "check")
            after = req and await self._wait_for(
                m, lambda d: isinstance(d.get("last_check"), dict) and float(d["last_check"].get("at") or 0) / 1000 >= req["at"] - 0.5)
            if after:
                out.update(self._task_view(after))
                ok = bool(after["last_check"].get("correct"))
                out["for_ainara"] = (
                    "You pressed Check on the screen for them. Their answer (learner_answer) was run and marked "
                    + ("RIGHT; the matching alarms are listed on screen. " if ok else f"not right yet (attempt {after.get('attempts')}). ")
                    + "The screen already shows its own feedback, so don't repeat it word for word; add your own touch"
                    " in one or two sentences." + TUTOR_RULES + rules)
                return out
            live = m.read_json(m.LIVE_FILE) or live

        out.update(self._task_view(live))
        lc = live.get("last_check") or {}
        run = live.get("last_run") or {}
        if question:
            say = (f"They asked: '{question}'. Answer that clearly in plain words using last_run (the alarms or error on"
                   " screen) and the lesson's key terms, without giving away the task's answer.")
        elif lc:
            say = ("Their last check on screen was " + ("RIGHT" if lc.get("correct") else "not right") +
                   ". Talk about learner_answer: what's good about it, and if it's wrong, the next rung of the hint ladder.")
        elif run.get("error"):
            say = "They pressed Run and got an error (last_run.error). Explain it in plain words and what to change."
        elif live.get("learner_answer") and not str(live.get("learner_answer")).startswith("("):
            say = ("They've entered learner_answer but not pressed Check. Tell them if it would give the right alarms"
                   " (compare with correct_answer; any wording that returns the same alarms is fine); if not, nudge"
                   " without giving the answer, and remind them to press Check.")
        else:
            say = "They haven't answered yet. Explain what the task is asking in one sentence and how to start."
        out["for_ainara"] = say + TUTOR_RULES + rules
        return out
