# Ainara AI Companion Framework Project -- user skill
#
# Ainara Skill: Change Assure Lesson -- move around the open Assure1 Classroom
# ("next lesson", "switch to event analytics", "open the sandbox")

"""
Ainara Skill: Change Assure Lesson (Assure1 Classroom)

"Next lesson", "go to lesson 4", "switch to event analytics", "back to the
course page", "open the sandbox" -- and two settings: "call me Dave", "stop
talking during lessons".

WHY A SEPARATE SKILL
  Ainara reopens a skill's screen every time a skill with a screen is called.
  This one has no screen: it leaves a request in ~/.ainara_assure/request.json
  and the open classroom (waiting on the assureclassroom "wait" action) turns
  the page at once. Which lesson to go to is worked out by assureclassroom.py,
  so there's one set of rules.

REAL PATHS:
    this file   -> ainara/my_skills/tools/changeassurelesson.py
    uses        -> ainara/my_skills/tools/assureclassroom.py (same folder)
    writes      -> ~/.ainara_assure/request.json, progress.json
"""

import asyncio
import importlib.util
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict, Optional

from ainara.framework.skill import Skill


def _main():
    """assureclassroom.py (same folder): its shared helpers and rules."""
    path = Path(__file__).with_name("assureclassroom.py")
    spec = importlib.util.spec_from_file_location("_assureclassroom_for_changeassurelesson", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class ToolsChangeassurelesson(Skill):
    """Change assure lesson: move to another lesson, course, the course page or
    the sandbox in the Assure1 Classroom that's already open, or change the
    learner's name or spoken-tips setting."""

    matcher_info = (
        "Use this skill to MOVE AROUND the ASSURE1 CLASSROOM while it's open: '**next lesson**',"
        " '**previous lesson**', '**go to lesson 4**' (lesson = 4), 'bring me into event list, lesson 4' (course = events, lesson = 4), '**switch to event"
        " analytics**', 'switch to the rules course', 'take me to the sandbox', '**open the"
        " sandbox**', 'back to the course page', '**take the final shift**' / 'start the final assessment' (course = final),"
        " in the final shift or a recap: '**next step**' (lesson = next) and 'take it again' (lesson = retake), '**give me another one**' / 'more practice' (lesson = more), '**quiz me**' / 'quick recap' (page = recap), 'call me Dave', 'stop talking during lessons' / 'turn"
        " your tips back on' (spoken_tips). It changes the classroom that's already on screen, without"
        " opening a new window."
        "\n\nNOT for the coding classroom (that is change-lesson) or the medical classroom (that is"
        " change-med-lesson)."
        "\n\nKeywords: next lesson, previous lesson, go to lesson, switch course, sandbox, Assure"
        " classroom, Assure1, alarm filters, event analytics."
    )

    embeddings_boost_factor = 1.4

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    @staticmethod
    async def _wait_for(m, test, tries: int = 14) -> Optional[Dict[str, Any]]:
        """The open card reports what it shows to live.json a moment after a change."""
        for _ in range(tries):
            await asyncio.sleep(0.25)
            live = m.read_json(m.LIVE_FILE)
            if live and test(live):
                return live
        return None

    async def run(
        self,
        lesson: Annotated[Optional[str], "Which lesson. If they said a NUMBER ('lesson 4', 'maybe lesson four', 'the fourth one') pass just that number: '4'. Otherwise 'next', 'previous', 'sandbox', or part of a lesson title. Use 'project' ONLY if they said the word project. 'more' when they want another practice task on the same lesson ('give me another one', 'more practice'). Never put a course name here. Leave empty when they only named a course or changed a setting"] = None,
        course: Annotated[Optional[str], "The course if they named one: events (event list, SQL filters, displays), rules (where alarms come from, deduplication, mechanizations), analytics (Discover, KQL, Console, Search Profiler), final (the final shift: the scored assessment with a certificate)"] = None,
        page: Annotated[Optional[str], "'landing' for the course page, 'sandbox' for free practice, 'recap' for a quick quiz on lessons they've finished ('quiz me', 'test me on what I've done'). Leave empty for a normal lesson change"] = None,
        name: Annotated[Optional[str], "Only if they told you the name to call them"] = None,
        spoken_tips: Annotated[Optional[str], "'off' if they want Ainara's short spoken tips during lessons to stop, 'on' to bring them back"] = None,
    ) -> Dict[str, Any]:
        """Change lesson, course, page or settings in the Assure1 classroom."""
        self.logger.info(f"TOOLS_CHANGEASSURELESSON RUN: lesson={lesson} course={course} page={page}")
        m = _main()
        classroom = m.ToolsAssureclassroom()
        progress = m.read_json(m.PROGRESS_FILE)
        rules = m.TALK_RULES + m.SAFETY_RULES

        settings: Dict[str, Any] = {}
        if name and str(name).strip():
            settings["name"] = re.sub(r"\s+", " ", str(name)).strip()[:60]
        v = str(spoken_tips or "").strip().lower()
        if v in ("on", "yes", "true", "1", "y", "enable", "start"):
            settings["voice_cues"] = True
        elif v in ("off", "no", "false", "0", "n", "disable", "stop"):
            settings["voice_cues"] = False
        said = ""
        if "name" in settings:
            said += f"Saved: their name is {settings['name']}. Use it now and then, not in every sentence. "
        if "voice_cues" in settings:
            said += "Ainara's short spoken tips during lessons are now " + ("on. " if settings["voice_cues"] else "off. ")

        wants_move = any(str(x or "").strip() for x in (lesson, course, page))
        on_screen = m.classroom_on_screen()
        if not wants_move and not settings:
            return {"success": False, "classroom_open": on_screen,
                    "for_ainara": "Nothing to change was given. Ask what they'd like to change." + m.TALK_RULES}
        if not on_screen and not settings:
            other = m.other_classroom_on_screen()
            if other:
                return m.wrong_classroom(other, "change lesson")

        def save_settings_directly() -> None:
            if "name" in settings:
                progress["profile"] = {**(progress.get("profile") or {}), "name": settings["name"]}
            if "voice_cues" in settings:
                progress["voiceCues"] = settings["voice_cues"]
            m.write_json(m.PROGRESS_FILE, progress)

        request: Dict[str, Any] = {"id": uuid.uuid4().hex, "at": time.time(), **settings}
        if not wants_move:
            request["action"] = "settings"
            if not await m.deliver(request, 4.0 if on_screen else 1.5):
                save_settings_directly()
                return {"success": True, "classroom_open": False, "settings": settings,
                        "for_ainara": said + "Confirm it in one short sentence; it takes effect next time the classroom opens." + rules}
            return {"success": True, "classroom_open": True, "settings": settings,
                    "for_ainara": said + "Confirm it in one short, friendly sentence." + rules}

        # Inside the final shift, "next" means the next STEP and "again" restarts the assessment.
        live = m.read_json(m.LIVE_FILE) if on_screen else {}
        which = "final_shift" if isinstance(live.get("final_shift"), dict) else "recap" if isinstance(live.get("recap"), dict) else ""
        fs = live.get(which) if which else None
        label = "final shift" if which == "final_shift" else "recap"
        words = set(re.findall(r"[a-z]+", str(lesson or "").lower()))
        if fs and not course and not page and words & {"next", "continue", "forward", "again", "retake", "restart", "retry"}:
            again = bool(words & {"again", "retake", "restart", "retry"})
            if not again and live.get("on_screen") in ("the final shift result", "the recap result"):
                return {"success": True, "classroom_open": True, "result": live.get("result"),
                        "for_ainara": said + f"The {label} is finished and its result is on screen, so there is no next step. Tell them their score from result and offer to take it again or go back to the courses." + rules}
            if not again and not fs.get("step_ready_for_next"):
                return {"success": False, "classroom_open": True, which: fs,
                        "for_ainara": said + f"They're on step {fs.get('step')} of {fs.get('steps')} of the {label} and haven't got it right yet, so it can't move on. Encourage them to answer it; check-my-filter will mark it. Showing the answer scores 0 for the step." + rules}
            request.update(action="retake" if again else "next_step")
            if await m.deliver(request, 4.0):
                sent = request["at"]
                after = await self._wait_for(
                    m, lambda d: float(d.get("updated_ts") or 0) >= sent and (
                        ((d.get(which) or {}).get("step") == 1 and d.get("on_screen") == "the lesson") if again else
                        ((d.get(which) or {}).get("step") != fs.get("step") or d.get("on_screen") != live.get("on_screen"))), 10)
                after = after or m.read_json(m.LIVE_FILE)
                out = {"success": True, "classroom_open": True, which: after.get(which), "on_screen": after.get("on_screen")}
                if after.get("result"):
                    out["result"] = after["result"]
                    out["for_ainara"] = said + ("The final shift is finished and the result is on screen. Tell them the score and whether they passed (70 of 100), name ONE step to revisit if any lost points, and if they passed mention the certificate and its Save button." if which == "final_shift" else "The recap is finished and its result is on screen. Tell them the score and ONE lesson worth revisiting (from result.revisit), or that it has all stuck, and offer another recap or to carry on with the course.") + rules
                else:
                    if isinstance(after.get("task"), dict):
                        out["task"] = after["task"].get("prompt")
                        out["task_language"] = after["task"].get("language")
                    out["for_ainara"] = said + (f"The {label} has restarted at question 1. " if again else f"The next question of the {label} is on screen. ") + "Read out what it is asking in ONE sentence (from task) and let them work. It's a test: no hints unless they ask, and say a hint costs 5 points." + rules
                return out

        # "Give me another one" / "more practice": the optional follow-up tasks of this lesson.
        if on_screen and not course and not page and (words & {"another", "more", "extra"}) and not (words & {"lesson", "course"}):
            ep = live.get("extra_practice") if isinstance(live.get("extra_practice"), dict) else None
            if not ep:
                return {"success": False, "classroom_open": True,
                        "for_ainara": said + "This lesson has no extra practice tasks. Offer the sandbox (free practice), a quick recap quiz (page = recap), or the next lesson." + rules}
            if not ep.get("offered"):
                return {"success": False, "classroom_open": True, "extra_practice": ep,
                        "for_ainara": said + "The extra practice opens once the lesson's main task is right. Encourage them to finish that first; check-my-filter will mark it." + rules}
            if int(ep.get("on_now") or 0) >= int(ep.get("tasks") or 0):
                return {"success": True, "classroom_open": True, "extra_practice": ep,
                        "for_ainara": said + "They've done all the extra practice for this lesson. Offer the next lesson, or a quick recap quiz (page = recap)." + rules}
            request.update(action="more")
            if await m.deliver(request, 4.0):
                sent = request["at"]
                after = await self._wait_for(m, lambda d: float(d.get("updated_ts") or 0) >= sent and (d.get("extra_practice") or {}).get("on_now") != ep.get("on_now"), 8) or m.read_json(m.LIVE_FILE)
                out = {"success": True, "classroom_open": True, "extra_practice": after.get("extra_practice")}
                if isinstance(after.get("task"), dict):
                    out["task"] = after["task"].get("prompt")
                    out["task_language"] = after["task"].get("language")
                out["for_ainara"] = said + "An extra practice task for this lesson is on screen. Say what it is asking in ONE sentence (from task) and let them try. It isn't scored." + rules
                return out

        where = classroom.resolve(course, lesson, page)

        async def closed() -> Dict[str, Any]:
            if settings:
                save_settings_directly()
            if where.get("recap"):
                args = "action = open, page = recap"
            elif where.get("landing"):
                args = "action = open, page = landing"
            else:
                args = "action = open" + "".join(f", {k} = {val}" for k, val in (("course", where["course"]), ("lesson", lesson), ("page", page)) if val)
            return {"success": False, "classroom_open": False, "open_with": args,
                    "for_ainara": (said + "The Assure1 classroom isn't open on screen right now. Call the Assure classroom"
                                   f" capability NOW with {args}; don't just say it's open." + rules)}

        if where.get("recap"):
            request.update(action="goto", page="recap")
            if not await m.deliver(request, 4.0 if on_screen else 1.5):
                return await closed()
            after = await self._wait_for(m, lambda d: float(d.get("updated_ts") or 0) >= request["at"], 8) or {}
            if not isinstance(after.get("recap"), dict):
                return {"success": False, "classroom_open": True,
                        "for_ainara": said + "A recap needs at least three finished lessons, and they haven't done that many yet. Say so kindly and suggest carrying on with the course." + rules}
            out = {"success": True, "classroom_open": True, "recap": after.get("recap")}
            if isinstance(after.get("task"), dict):
                out["task"] = after["task"].get("prompt")
                out["task_language"] = after["task"].get("language")
            out["for_ainara"] = said + ("A quick recap is on screen: five questions drawn from lessons they've finished, 20 points each. Say what the first one is asking in ONE sentence and let them work. No hints unless they ask. 'Next step' moves on once a question is right." + rules)
            return out
        if where.get("landing"):
            request.update(action="goto", page="landing")
            if not await m.deliver(request, 4.0 if on_screen else 1.5):
                return await closed()
            return {"success": True, "classroom_open": True, "courses": classroom.course_status(progress),
                    "for_ainara": said + "The classroom is back on the course page. Ask which course they'd like, or offer to resume one." + rules}

        t, idx, titles = where["course"], where["idx"], where["titles"]
        request.update(action="goto", course=t, idx=idx)
        if not await m.deliver(request, 4.0 if on_screen else 1.5):
            return await closed()
        is_sandbox = idx >= len(titles)
        title = "Sandbox (free practice)" if is_sandbox else titles[idx]
        out: Dict[str, Any] = {"success": True, "classroom_open": True,
                               "now_showing": {"course": m.COURSES[t]["name"],
                                               "lesson": "the sandbox" if is_sandbox else f"lesson {idx + 1} of {len(titles)}",
                                               "title": title}}
        if is_sandbox:
            say = ("The sandbox is on screen: free practice in SQL filters (live list), KQL and the Console (alarm"
                   " history). Invite them to try a query, or to say one out loud for you to run with check-my-filter.")
        else:
            lesson_id = m.lesson_index()[t][idx].get("id")
            live = await self._wait_for(m, lambda d: d.get("course") == t and d.get("lesson_id") == lesson_id)
            say = (f"The classroom has moved to {out['now_showing']['course']}, {out['now_showing']['lesson']}: '{title}'. "
                   + m.FINAL_RULES if t == "final" else
                   f"The classroom has moved to {out['now_showing']['course']}, {out['now_showing']['lesson']}: '{title}'."
                   " Introduce it like a friendly senior NOC engineer in TWO short spoken sentences: why it matters on"
                   " shift (from what_it_teaches), then what to try (from the task). Don't read the lesson out and don't"
                   " give the answer.")
            if live:
                out["what_it_teaches"] = str(live.get("lesson_explain", ""))[:700]
                if isinstance(live.get("task"), dict):
                    out["task"] = live["task"].get("prompt")
                    out["task_language"] = live["task"].get("language")
        if where.get("note"):
            out["note"] = where["note"]
        if not is_sandbox and "project" in str(lesson or "").lower() and not re.search(r"\d", str(lesson)):
            say += (" You asked for the PROJECT lesson. If they actually said a lesson number, you went to the wrong"
                    " place: call this capability again at once with lesson = that number, without apologising at length.")
        out["for_ainara"] = said + say + rules
        return out
