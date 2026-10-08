# Ainara AI Companion Framework Project -- user skill
#
# Ainara Skill: Assure Classroom ("open my Assure classroom", "teach me Assure1 filters")

"""
Ainara Skill: Assure Classroom

A beginner's course in administering alarms in Assure1 (event filters,
displays, where alarms come from, Event Analytics), built the same way as the
Coding and Medical Classrooms. It opens a popup card
(_components/ToolsAssureclassroom/index.html):

    LEFT    the lesson: a short explanation, examples, key terms
    RIGHT   the task and an ALARM SIMULATOR. The learner writes a SQL filter,
            a KQL search or a Console (Elasticsearch) request, presses Run and
            the matching alarms are listed, coloured by severity. Any query
            that returns the same alarms as the model answer is marked right.

EVERYTHING IS SIMULATED. The card holds 32 dummy live alarms and 180 dummy
history records; it never connects to a real Assure1. All names are made up:
TST1_xxx = NGN cabinets, RAN1_xxx = RAN sites, CORE1_xxx = core routers,
TX1_xxx = transmission, SRC_A..D = alarm sources. Never use real network,
filter, display or customer names when talking about this classroom.

Ainara is the tutor. She can see the learner's work through the companion
skills, which have NO popup (so asking for help never reopens the screen):

    changeassurelesson    "next lesson", "go to lesson 4", "switch to event analytics", "open the sandbox",
                          "give me another one" (extra practice), "quiz me" (quick recap)
    checkmyfilter         "check my filter", "is it Severity equals 5 and Ack equals 0?", "give me a hint"
    showassureanswer      "show me the answer", "talk me through it"
    closeassureclassroom  "close my Assure classroom"
    assurehowto           "how do I create a filter?", "why did my alarm disappear?" (answers with a diagram)

REAL PATHS:
    this file   -> ainara/my_skills/tools/assureclassroom.py
    popup card  -> ainara/my_skills/_components/ToolsAssureclassroom/index.html
    lesson list -> ainara/my_skills/_components/ToolsAssureclassroom/lessons.json
    state       -> ~/.ainara_assure/  (progress.json, live.json, request.json, heartbeat, card.json, ack.json)
                   kept apart from ~/.ainara_learn/ (coding) and ~/.ainara_med/ (medical)
    no extra dependencies (Python standard library only)

HOW THE CARD TALKS TO THIS FILE
  The card POSTs to http://localhost:8100/run/user_tools_assureclassroom with
  {"action": ..., ...}.
    open            -> the card's starting data (course, lesson)
    wait            -> 25 s long-poll for requests from the helper skills
    ack             -> the card acted on a helper's request
    sync            -> saves live.json (what is on screen, read by the helpers)
    save_progress / load_progress / reset
  Short spoken tips come from the card itself through PyBridge
  (POST http://localhost:8101/framework/tts), with no chat turn and no popup.
"""

import asyncio
import base64
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from ainara.framework.skill import Skill

STATE_DIR = Path(os.path.expanduser("~/.ainara_assure"))
PROGRESS_FILE = STATE_DIR / "progress.json"
LIVE_FILE = STATE_DIR / "live.json"
REQUEST_FILE = STATE_DIR / "request.json"     # written by the helper skills
HEARTBEAT_FILE = STATE_DIR / "heartbeat"      # touched while a classroom card is open
CARD_FILE = STATE_DIR / "card.json"           # which open classroom screen is the newest
ACK_FILE = STATE_DIR / "ack.json"             # the last request a screen actually acted on
OTHER_CLASSROOMS = {                          # heartbeats of the other classrooms, to tell them apart
    "coding": Path(os.path.expanduser("~/.ainara_learn/heartbeat")),
    "medical": Path(os.path.expanduser("~/.ainara_med/heartbeat")),
}
LESSONS_JSON = Path(__file__).resolve().parent.parent / "_components" / "ToolsAssureclassroom" / "lessons.json"
MAX_LIVE_CHARS = 200_000
OPEN_IF_BEAT_WITHIN = 35  # seconds (the open card checks in every 25 s)

COURSES = {
    "events": {"name": "Event list, filters & displays", "prefix": "ev"},
    "rules": {"name": "Where alarms come from", "prefix": "ru"},
    "analytics": {"name": "Event Analytics", "prefix": "ea"},
    "final": {"name": "Final shift", "prefix": "fs"},
}
CERT_DIR_NAME = "Assure1 Classroom"
MAX_CERT_BYTES = 8 * 1024 * 1024
COURSE_ALIASES = {
    "events": "events", "event list": "events", "filters": "events", "filter": "events", "event filters": "events",
    "displays": "events", "display": "events", "sql": "events", "sql filters": "events", "alarm filters": "events",
    "filters and displays": "events", "alarms": "events", "alarm list": "events",
    "rules": "rules", "where alarms come from": "rules", "aggregators": "rules", "deduplication": "rules",
    "dedup": "rules", "eventkey": "rules", "event key": "rules", "mechanizations": "rules", "mechanisations": "rules",
    "thresholds": "rules", "traps": "rules", "syslog": "rules",
    "analytics": "analytics", "event analytics": "analytics", "kibana": "analytics", "discover": "analytics",
    "kql": "analytics", "elasticsearch": "analytics", "elastic": "analytics", "console": "analytics",
    "search profiler": "analytics", "profiler": "analytics", "history": "analytics", "alarm history": "analytics",
    "aggregations": "analytics",
    "final": "final", "final shift": "final", "final assessment": "final", "assessment": "final", "final test": "final",
    "exam": "final", "final exam": "final", "test": "final", "certificate": "final", "final lesson": "final",
}
LANDING_WORDS = ("home", "landing", "landing page", "menu", "main menu", "courses", "course page",
                 "courses page", "main page", "start page", "home page", "choose a course", "course list")
SANDBOX_WORDS = ("sandbox", "playground", "free", "free practice", "free play")
RECAP_WORDS = ("recap", "quiz", "review", "revise", "revision", "test me")
HOWTO_JSON = LESSONS_JSON.with_name("howto.json")   # the How-do-I answers, written by the test script from the card
HOW_STOP = set("how do i can you the a an to of in on for my me is it and or with what does did are was be we us our your this that at from by as".split())


def how_words(text: Optional[str]) -> List[str]:
    return [w for w in re.split(r"[^a-z0-9]+", str(text or "").lower()) if len(w) > 1 and w not in HOW_STOP]


def howto_topics() -> List[Dict[str, Any]]:
    try:
        data = json.loads(HOWTO_JSON.read_text(encoding="utf-8"))
        return [t for t in data if isinstance(t, dict) and t.get("id")]
    except Exception:  # noqa: BLE001
        return []


def howto_find(question: Optional[str]) -> Optional[Dict[str, Any]]:
    """The prepared How-do-I answer that best fits a question (same scoring as the card), or None."""
    qs = set(how_words(question))
    best, best_n = None, 0
    for t in howto_topics():
        keys, tw, n = t.get("keys") or [], set(how_words(t.get("q"))), 0
        for w in qs:
            if w in keys:
                n += 2
            elif w in tw or any(len(k) > 4 and (k.startswith(w) or w.startswith(k)) for k in keys):
                n += 1
        if n > best_n:
            best, best_n = t, n
    return best if best_n >= 3 else None

TALK_RULES = (
    " Keep it short and spoken: two or three sentences, then hand back to them. Never use"
    " triple-backtick blocks or ASCII diagrams while the classroom is open (they open a popup over"
    " it); say a filter in words or in one plain line. When they want to stop, you MUST ask ORAKLE"
    " to 'close my Assure classroom' (the close-assure-classroom capability); it only closes when"
    " that runs."
)
SAFETY_RULES = (
    " ABOUT THE DATA: the classroom is a SIMULATOR with dummy alarms only; it never touches a real"
    " Assure1. Use only the classroom's made-up names (TST1_001 = NGN cabinets, RAN1_001 = RAN sites,"
    " CORE1_001 = core routers, TX1_001 = transmission, SRC_A..D = sources). Never mention or ask for"
    " real node, filter, display, customer or network names. If they ask about doing something on"
    " the live system, remind them of the safe habits: clone never edit, prefix practice items"
    " TRAIN_, keep them private, read-only first, and ask a senior admin before touching rules,"
    " mechanizations or Elasticsearch management."
)


# What a learner can do after each course; Ainara uses these on the course page.
OUTCOMES = {
    "events": "read and work the event list (acknowledge, own, journal) and build and maintain alarm views: write and edit SQL filters for any team, hide noise, lay out a display, set a filter group's restriction, and safely delete alarms that should not be there",
    "rules": "set up a new alarm and fix a bad one: write a rule (severity, EventType, EventKey), pair clears with problems, create a threshold alarm from a measurement, give clutter an expiry so it removes itself, and know what is safe to change",
    "analytics": "answer questions about the past: search alarm history in Discover with KQL, and count and rank alarms from the Console",
    "final": "prove it on a full morning shift of five mixed tasks, and earn the certificate",
}

FINAL_RULES = (
    "This is the FINAL SHIFT, the assessment: one morning-shift scenario with five steps (a SQL filter, a"
    " display, a rules question, a KQL search, a Console count), 20 points each, 70 of 100 passes and earns"
    " a certificate. Set the scene in two short sentences and wish them luck. It is a test: don't volunteer"
    " answers; a hint or a second try costs 5 points and Show answer scores 0 for the step, so say that"
    " before giving either. 'Next step' and 'take it again' go through change-assure-lesson. "
)


def read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 -- missing/corrupt file = nothing yet
        return {}


def write_json(path: Path, data: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def beat_age(path: Path) -> Optional[float]:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def classroom_on_screen() -> bool:
    """A classroom card is listening if it checked in recently (heartbeat, kept fresh
    the whole time its long-poll is parked) or reported what it shows (live.json)."""
    age = beat_age(HEARTBEAT_FILE)
    if age is not None and age < OPEN_IF_BEAT_WITHIN:
        return True
    try:
        return time.time() - float(read_json(LIVE_FILE).get("updated_ts") or 0) < OPEN_IF_BEAT_WITHIN
    except (TypeError, ValueError):
        return False


def other_classroom_on_screen() -> Optional[str]:
    """'coding' or 'medical' if one of the other classrooms is what's on screen."""
    for name, path in OTHER_CLASSROOMS.items():
        age = beat_age(path)
        if age is not None and age < OPEN_IF_BEAT_WITHIN:
            return name
    return None


def wrong_classroom(other: str, this_skill_does: str) -> Dict[str, Any]:
    """What a helper answers when a different classroom is the one on screen."""
    use = {"coding": "the coding classroom's own capabilities (change-lesson, check-my-code, show-me-the-answer, close-classroom)",
           "medical": "the medical classroom's own capabilities (change-med-lesson, check-my-answer, show-me-the-reasoning, close-med-classroom)"}[other]
    return {"success": False, "classroom_open": False,
            "for_ainara": (f"The {other.upper()} classroom is on screen, not the Assure one. If they meant that classroom, use {use}."
                           f" If they want to {this_skill_does} in the Assure classroom, open it first with the Assure classroom capability." + TALK_RULES)}


async def deliver(request: Dict[str, Any], seconds: float = 4.0) -> bool:
    """Leave a request for the open card and wait until the card says it acted on it
    ("ack"). False means no classroom is really listening (closed, or its screen was
    lost). Used by every helper skill, so 'is it open?' is answered by the screen
    itself, not guessed from file times."""
    request = dict(request)
    request.setdefault("at", time.time())
    write_json(REQUEST_FILE, request)
    end = time.time() + seconds
    while time.time() < end:
        await asyncio.sleep(0.15)
        if read_json(ACK_FILE).get("id") == request.get("id"):
            return True
    return False


def lesson_index() -> Dict[str, List[Dict[str, Any]]]:
    """Courses and their lesson titles, from lessons.json next to the card."""
    data = read_json(LESSONS_JSON)
    return {k: v for k, v in data.items() if k in COURSES and isinstance(v, list) and v}


def course_key(text: Optional[str]) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    t = re.sub(r"^(the|my)\s+", "", t)
    t = re.sub(r"\s+(course|lessons?|class)$", "", t)
    if t in COURSES:
        return t
    if t in COURSE_ALIASES:
        return COURSE_ALIASES[t]
    for k, c in COURSES.items():
        if t and t == c["name"].lower():
            return k
    for alias, k in sorted(COURSE_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if t and re.search(r"\b" + re.escape(alias) + r"\b", t):
            return k
    return ""


def done_in(progress: Dict[str, Any], course: str) -> int:
    pre = COURSES[course]["prefix"]
    return sum(1 for k, v in (progress.get("done") or {}).items() if v and re.fullmatch(pre + r"\d+", k))


class ToolsAssureclassroom(Skill):
    """Assure classroom: learn to administer alarms in Assure1 (filters, displays,
    rules, Event Analytics) in an interactive screen with short lessons and an
    alarm simulator that lists the alarms each query returns. Opens the screen
    only -- checking work is the check-my-filter skill."""

    matcher_info = (
        "Opens the ASSURE1 CLASSROOM screen. Use it whenever the user wants to LEARN, STUDY or"
        " PRACTISE Assure1 / Unified Assurance alarm administration -- don't teach them in chat, open"
        " the classroom. Examples: '**open my Assure classroom**', '**open the Assure1 classroom**',"
        " '**teach me Assure1**', 'teach me how to write alarm filters', 'I want to learn Assure1"
        " admin', 'teach me event filters', 'how do I create a filter in Assure1', 'teach me KQL',"
        " 'teach me the Kibana console', 'practise alarm filters', 'open the alarm classroom',"
        " 'continue my Assure lessons', 'open the alarm sandbox'."
        "\n\nNOT for the coding classroom or the medical classroom (each has its own capability)."
        "\n\nActions: open (default) with course = events (event list, SQL filters, displays) / rules"
        " (where alarms come from, deduplication, mechanizations) / analytics (Discover, KQL, Console,"
        " Search Profiler) / final (the final shift: 'take the final assessment', 'I want my Assure"
        " certificate', 'test me on Assure1') if they named one. If they don't name a course, leave course, lesson and"
        " page empty: the classroom opens on its course page."
        "\n\nWhile the classroom is OPEN, other capabilities do the work without opening a new"
        " window: 'next lesson' / 'go to lesson 4' / 'switch to event analytics' / 'open the sandbox'"
        " = change-assure-lesson; 'check my filter' / 'check my query' / 'is it Severity equals 5?' /"
        " 'give me a hint' = check-my-filter; 'show me the answer' / 'talk me through it' ="
        " show-assure-answer; 'close my Assure classroom' = close-assure-classroom. Use THIS one only"
        " to open the classroom, or when one of those says it isn't open."
        "\n\nKeywords: Assure1, Assure classroom, Unified Assurance, alarms, alarm filter, event"
        " filter, event list, display, filter group, rules, deduplication, mechanization, event"
        " analytics, Kibana, KQL, Elasticsearch console, search profiler, NOC, learn, practise."
    )

    embeddings_boost_factor = 1.3

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    # ---------------------------------------------
    # PROGRESS AND LIVE STATE (card actions)
    # ---------------------------------------------

    @staticmethod
    def _read_progress() -> Dict[str, Any]:
        return read_json(PROGRESS_FILE)

    async def load_progress(self) -> Dict[str, Any]:
        return {"success": True, "progress": self._read_progress()}

    async def save_progress(self, progress: Optional[str]) -> Dict[str, Any]:
        try:
            data = json.loads(progress or "{}")
            if not isinstance(data, dict):
                raise ValueError("progress must be an object")
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": f"Couldn't read progress: {exc}"}
        data["saved_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            write_json(PROGRESS_FILE, data)
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": f"Couldn't save progress: {exc}"}
        return {"success": True}

    async def sync(self, live: Optional[str]) -> Dict[str, Any]:
        if live and len(live) > MAX_LIVE_CHARS:
            return {"success": False, "error": "Live state too large"}
        try:
            data = json.loads(live or "{}")
            if not isinstance(data, dict):
                raise ValueError("live state must be an object")
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": f"Couldn't read live state: {exc}"}
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        data["updated_ts"] = time.time()
        try:
            write_json(LIVE_FILE, data)
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": f"Couldn't save live state: {exc}"}
        return {"success": True}

    async def reset(self) -> Dict[str, Any]:
        """Erase all saved progress and the live state ('Reset all progress' on the card)."""
        errors = []
        for f in (PROGRESS_FILE, LIVE_FILE):
            try:
                if f.exists():
                    f.write_text("{}", encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{f.name}: {exc}")
        if errors:
            return {"success": False, "error": "Couldn't reset: " + "; ".join(errors)}
        return {"success": True}

    async def save_certificate(self, image: Optional[str]) -> Dict[str, Any]:
        """Save the certificate picture the card drew to ~/Pictures/Assure1 Classroom/."""
        data = str(image or "")
        prefix = "data:image/png;base64,"
        if not data.startswith(prefix):
            return {"success": False, "error": "No certificate picture was sent."}
        try:
            raw = base64.b64decode(data[len(prefix):], validate=True)
        except Exception:  # noqa: BLE001
            return {"success": False, "error": "The certificate picture was damaged."}
        if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) > MAX_CERT_BYTES:
            return {"success": False, "error": "That doesn't look like a certificate picture."}
        pictures = Path(os.path.expanduser("~/Pictures"))
        folder = (pictures if pictures.is_dir() else Path(os.path.expanduser("~"))) / CERT_DIR_NAME
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "Assure1 Classroom certificate.png"
            path.write_bytes(raw)
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": f"Couldn't save it: {exc}"}
        home = str(Path(os.path.expanduser("~")))
        shown = str(path).replace(home, "~", 1) if str(path).startswith(home) else str(path)
        return {"success": True, "path": str(path), "shown_path": shown}

    # ---------------------------------------------
    # THE OPEN CARD'S LONG-POLL
    # ---------------------------------------------

    @staticmethod
    def _beat() -> None:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            HEARTBEAT_FILE.touch()
        except OSError:
            pass

    @staticmethod
    def _pending_request(seen: Optional[str], since_t: float) -> Optional[Dict[str, Any]]:
        data = read_json(REQUEST_FILE)
        at = float(data.get("at") or 0)
        if data.get("id") and data.get("id") != seen and at >= since_t and time.time() - at < 20:
            return data
        return None

    async def wait(self, since: Optional[str], seen: Optional[str]) -> Dict[str, Any]:
        """Long-poll from the open card: returns as soon as a helper skill leaves a
        request, or after ~25 s. Keeps the heartbeat fresh so the helpers know the
        classroom is on screen. Only the newest open card listens (card lease)."""
        try:
            since_t = float(since or 0)
        except ValueError:
            since_t = 0.0
        now = time.time()
        card = read_json(CARD_FILE)
        newest, last = float(card.get("boot") or 0), float(card.get("seen") or 0)
        if since_t + 0.001 < newest and now - last < 35:
            return {"success": True, "request": self._pending_request(seen, since_t), "superseded": True}
        try:
            write_json(CARD_FILE, {"boot": since_t, "seen": now})
        except OSError:
            pass
        self._beat()
        end = now + 25
        last_beat = now
        while True:
            req = self._pending_request(seen, since_t)
            if req:
                return {"success": True, "request": req}
            if time.time() >= end:
                return {"success": True, "request": None}
            if time.time() - last_beat > 3:  # keep "on screen" true for the whole poll
                self._beat()
                last_beat = time.time()
            await asyncio.sleep(0.4)

    # ---------------------------------------------
    # OPEN (spoken)
    # ---------------------------------------------

    NUMBER_WORDS = {
        "one": 1, "first": 1, "two": 2, "second": 2, "three": 3, "third": 3, "four": 4, "fourth": 4,
        "five": 5, "fifth": 5, "six": 6, "sixth": 6, "seven": 7, "seventh": 7, "eight": 8, "eighth": 8,
        "nine": 9, "ninth": 9, "ten": 10, "tenth": 10,
    }

    @classmethod
    def target_index(cls, lesson: str, current: int, titles: List[str]) -> Optional[int]:
        """'next', 'previous', '4', 'lesson four', 'sandbox', 'the project', or part of a
        title -> a 0-based index (the sandbox is index len(titles))."""
        text = str(lesson).strip().lower()
        words = re.findall(r"[a-z0-9]+", text)
        ws = set(words)
        if ws & {"next", "forward", "continue", "following"}:
            return current + 1
        if ws & {"previous", "prev", "back", "before", "earlier"} or text == "last lesson":
            return current - 1
        if ws & set(SANDBOX_WORDS):
            return len(titles)
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            return int(digits) - 1
        for w in words:
            if w in cls.NUMBER_WORDS:
                return cls.NUMBER_WORDS[w] - 1
        if "project" in ws:
            projects = [i for i, t in enumerate(titles) if t.lower().startswith("project")]
            return (projects or [current])[0]
        if ws & {"start", "beginning", "begin", "intro", "introduction"}:
            return 0
        for i, t in enumerate(titles):
            if text and text in t.lower():
                return i
        for i, t in enumerate(titles):
            tw = set(re.findall(r"[a-z0-9]+", t.lower())) - {"the", "and", "a", "of", "to", "project", "your", "with"}
            if tw and len(tw & ws) >= max(1, min(2, len(tw))):
                return i
        return None

    @staticmethod
    def page_key(page: Optional[str]) -> Optional[str]:
        p = str(page or "").strip().lower()
        if not p or p in ("none", "no", "null"):
            return None
        if p in LANDING_WORDS or any(w in p for w in ("landing", "course page", "course list", "all courses", "main", "home", "choose", "menu")):
            return "landing"
        if "how" in p or "help page" in p or "question" in p:
            return "howto"
        if any(w in p for w in RECAP_WORDS):
            return "recap"
        if any(w in p for w in SANDBOX_WORDS):
            return "sandbox"
        return None

    def resolve(self, course: Optional[str], lesson: Optional[str], page: Optional[str]) -> Dict[str, Any]:
        """Work out where the classroom should go. Shared with changeassurelesson.py."""
        built = lesson_index()
        progress = self._read_progress()
        key = course_key(course)
        if lesson:
            # "change lesson to event analytics" -> the lesson is really a course name
            # (also when the course was given too: lesson = "Event list, filters & displays")
            k2 = course_key(lesson)
            if k2 and not re.search(r"\d", str(lesson)) and not (set(re.findall(r"[a-z]+", str(lesson).lower())) & {"next", "previous", "project", "sandbox"}):
                key, lesson = key or k2, None
        pk = self.page_key(page) or (self.page_key(lesson) if lesson and not re.search(r"\d", str(lesson)) else None)
        if pk == "landing":
            return {"landing": True}
        if pk == "recap":
            return {"landing": True, "recap": True}
        if pk == "howto":
            return {"landing": True, "howto": True}
        if not key and str(lesson or "").strip().lower() in ("", "none", "null", "no") and pk is None:
            return {"landing": True}
        # "next" / "previous" count from what is on screen right now (live.json), which is
        # newer than progress.json; with no screen open, from where they left off.
        live = read_json(LIVE_FILE) if classroom_on_screen() else {}
        live_course = live.get("course") if live.get("course") in built else ""
        t = key or live_course or (progress.get("course") if progress.get("course") in built else "") or ("events" if "events" in built else "")
        if not t or t not in built:
            return {"landing": True}
        titles = [x["title"] for x in built[t]]
        current = int((progress.get("idx") or {}).get(t, 0) or 0)
        if t == live_course:
            try:
                current = len(titles) if live.get("lesson_free") else int(live.get("lesson_number") or current + 1) - 1
            except (TypeError, ValueError):
                pass
        note = ""
        if pk == "sandbox":
            current = len(titles)
        elif lesson and str(lesson).strip():
            target = self.target_index(str(lesson), current, titles)
            if target is None:
                note = f"Couldn't tell which lesson '{lesson}' means, so it stayed where they left off."
            else:
                if target > len(titles):
                    note = "That was already the last page (the sandbox)."
                elif target < 0:
                    note = "They were already on the first lesson."
                current = max(0, min(len(titles), target))
        elif key:
            # a course named with no lesson: resume at the first lesson not yet done
            done = progress.get("done") or {}
            current = next((i for i, x in enumerate(built[t]) if not done.get(x["id"])), current)
        return {"course": t, "idx": current, "titles": titles, "note": note}

    @staticmethod
    def course_status(progress: Dict[str, Any]) -> Dict[str, str]:
        built = lesson_index()
        out = {}
        for k, c in COURSES.items():
            if k not in built:
                continue
            n, d = len(built[k]), done_in(progress, k)
            nxt = next((i for i, x in enumerate(built[k]) if not (progress.get("done") or {}).get(x["id"])), None)
            if k == "final":
                best = ((progress.get("finals") or {}).get("fs1") or {}).get("best")
                out[c["name"]] = ("the final assessment: not taken yet" if best is None else
                                  f"the final assessment: best score {best} of 100, " + ("passed, certificate earned" if d else "not passed yet (70 passes)"))
                continue
            out[c["name"]] = ("not started" if not d else f"all {n} lessons done" if nxt is None else
                              f"{d} of {n} done, next is lesson {nxt + 1}: {built[k][nxt]['title']}")
        return out

    async def open(self, course: Optional[str], lesson: Optional[str] = None, page: Optional[str] = None,
                   show_answer: Optional[str] = None) -> Dict[str, Any]:
        progress = self._read_progress()
        where = self.resolve(course, lesson, page)
        name = str((progress.get("profile") or {}).get("name") or "").strip()
        result: Dict[str, Any] = {"success": True, "view": "classroom", "courses": self.course_status(progress)}
        if name:
            result["learner_name"] = name

        if where.get("landing"):
            result["course"] = None
            result["now_showing"] = {"page": "the course page"}
            first_time = not progress.get("done")
            done = progress.get("done") or {}
            built = lesson_index()
            left = [k for k in COURSES if k in built and not all(done.get(x["id"]) for x in built[k])]
            result["by_the_end_they_can"] = {COURSES[k]["name"]: OUTCOMES[k] for k in COURSES if k in built}
            say = "The Assure1 classroom is open on its course page. "
            if first_time:
                say += ("This looks like their first visit. For this welcome you may use FIVE or six short spoken"
                        " sentences: welcome them; then paint the picture of what they will be able to do by the end,"
                        " in your own words from by_the_end_they_can (one sentence per course: build their own alarm"
                        " views with filters and displays, explain where an alarm came from and what is safe to"
                        " change, and answer questions about last week from alarm history); say it finishes with a"
                        " final shift that earns a certificate and that every lesson ends with real-looking alarms"
                        " on screen; then suggest starting with 'Event list, filters & displays'. Make it sound"
                        " like something worth having, not a syllabus. If you don't know their name, ask once; when"
                        " they tell you, ask ORAKLE to 'change assure lesson' with name so it is remembered. ")
            elif left:
                result["still_to_learn"] = {COURSES[k]["name"]: OUTCOMES[k] for k in left}
                say += ("Greet them (by name if you know it) in one sentence, then in ONE or two sentences remind them"
                        " what finishing will let them do, using still_to_learn (only what is left, in your own"
                        " words), and offer to carry on where they left off using the courses list. If all three"
                        " courses are done and the final shift isn't passed, suggest the final shift. You may use"
                        " four short sentences here. ")
            else:
                say += ("They have finished everything, final shift included. Greet them (by name if you know it),"
                        " congratulate them in one sentence, and offer the sandbox for practice or a retake of the"
                        " final shift for a better score. ")
            if where.get("howto"):
                topic = howto_find(lesson) or howto_find(page)
                result["page"] = "howto"
                if topic:
                    result["howto"] = topic["id"]
                    result["how_to"] = {k: topic.get(k) for k in ("q", "where", "risk", "steps", "note")}
                say = ("The Assure1 classroom is open on its 'How do I…?' page"
                       + (f", showing the prepared answer to '{topic['q']}' with a diagram. Talk them through how_to in three or four short sentences: where to go, the key steps, and the risk. " if topic else
                          ": a list of common admin questions, each with steps and a diagram. Ask what they'd like to know how to do. ")
                       + "For any further 'how do I' question use the assure-how-to capability; it changes this page without reopening it. ")
            if where.get("recap"):
                result["page"] = "recap"
                say = ("The Assure1 classroom is open and a quick recap is starting: five questions drawn from lessons"
                       " they've finished, 20 points each. (If they have finished fewer than three lessons the screen"
                       " stays on the course page and says so.) Wish them luck in one sentence. ")
            say += ("The courses list is the ONLY truth about their progress: never use lesson numbers from earlier"
                    " chats. When they pick a course, ask ORAKLE to 'change assure lesson to <course>' with no lesson"
                    " number; it resumes where they are.")
            result["for_ainara"] = say + TALK_RULES + SAFETY_RULES
            return result

        t, idx, titles = where["course"], where["idx"], where["titles"]
        progress.setdefault("idx", {})[t] = idx
        progress["course"] = t
        await self.save_progress(json.dumps(progress))
        is_sandbox = idx >= len(titles)
        result.update(course=t, idx=idx)
        result["now_showing"] = {"course": COURSES[t]["name"],
                                 "lesson": "the sandbox" if is_sandbox else f"lesson {idx + 1} of {len(titles)}",
                                 "title": "Sandbox (free practice)" if is_sandbox else titles[idx]}
        if where.get("note"):
            result["note"] = where["note"]
        if str(show_answer or "").strip().lower() in ("yes", "true", "1", "y"):
            result["showme"] = True
        result["for_ainara"] = (
            f"The Assure1 classroom is open at {result['now_showing']['course']}, {result['now_showing']['lesson']}:"
            f" '{result['now_showing']['title']}'. "
            + (FINAL_RULES if t == "final" and not is_sandbox else "The sandbox is free practice: they can type any SQL filter, KQL search or Console request and see the"
               " alarms it returns. Invite them to try one. " if is_sandbox else
               "Introduce the lesson like a friendly senior NOC engineer in TWO short spoken sentences: why it matters"
               " on shift, then what to try. Don't give the answer. ")
            + "You can't see the screen, but the check-my-filter capability can (never ask them to paste anything)."
            + TALK_RULES + SAFETY_RULES
        )
        return result

    async def run(
        self,
        action: Annotated[str, "Action: open (default). The classroom screen itself uses wait, ack, sync, save_progress, load_progress, reset"] = "open",
        course: Annotated[Optional[str], "For open: the course if they named one: events (event list, SQL filters, displays), rules (where alarms come from, deduplication, mechanizations), analytics (Discover, KQL, Console, Search Profiler), final (the final shift: the scored assessment with a certificate). Leave empty if they didn't say"] = None,
        lesson: Annotated[Optional[str], "For open: which lesson, only if they asked for one. If they said a NUMBER ('lesson 4', 'maybe lesson four') pass just that number: '4'. Otherwise 'next', 'sandbox', or part of a lesson title. Use 'project' ONLY if they said the word project. Leave empty to open on the course page"] = None,
        page: Annotated[Optional[str], "For open: 'sandbox' for free practice, 'recap' for a quick quiz on finished lessons, 'howto' for the How-do-I page (put their question in lesson), or 'landing' for the course page. Leave empty for a normal lesson"] = None,
        show_answer: Annotated[Optional[str], "For open: 'yes' only when the show-assure-answer capability said the classroom was closed and they want it opened with the answer shown"] = None,
        since: Annotated[Optional[str], "Card only: when the card opened (for wait)"] = None,
        seen: Annotated[Optional[str], "Card only: last request id the card handled (for wait and ack)"] = None,
        live: Annotated[Optional[str], "Card only: JSON live state"] = None,
        progress: Annotated[Optional[str], "Card only: JSON progress to save"] = None,
        image: Annotated[Optional[str], "Card only: certificate picture (PNG data URL)"] = None,
    ) -> Dict[str, Any]:
        """Main entry point -- routes to the right action."""
        if action == "wait":  # the open card's long-poll: not worth a log line
            return await self.wait(since, seen)
        self.logger.info(f"TOOLS_ASSURECLASSROOM RUN: action={action}")
        if action == "open":
            return await self.open(course, lesson, page, show_answer)
        if action == "ack":  # the card acted on a helper's request
            try:
                write_json(ACK_FILE, {"id": str(seen or ""), "at": time.time()})
            except OSError as exc:
                return {"success": False, "error": str(exc)}
            self._beat()
            return {"success": True}
        if action == "sync":
            return await self.sync(live)
        if action == "save_progress":
            return await self.save_progress(progress)
        if action == "load_progress":
            return await self.load_progress()
        if action == "reset":
            return await self.reset()
        if action == "save_certificate":
            return await self.save_certificate(image)
        return {"success": False, "error": f"Unknown action '{action}'",
                "valid_actions": ["open", "wait", "ack", "sync", "save_progress", "load_progress", "reset", "save_certificate"]}
