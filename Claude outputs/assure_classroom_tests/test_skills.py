"""Runs the five Assure skills against a stand-in for the open card (HOME is a temp dir)."""
import asyncio, importlib.util, json, os, sys, tempfile, time
from pathlib import Path
os.environ["HOME"] = tempfile.mkdtemp(prefix="assure_test_")
TOOLS = Path(sys.argv[1])
def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py"); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
main = load("assureclassroom"); change = load("changeassurelesson"); check = load("checkmyfilter"); show = load("showassureanswer"); close = load("closeassureclassroom"); howto = load("assurehowto")
card_skill = main.ToolsAssureclassroom()
LESSONS = json.loads(main.LESSONS_JSON.read_text())
handled = []
async def fake_card(stop):
    """What the real card does: long-poll, ack, act, sync."""
    boot, seen = time.time(), ""
    state = {"on_screen": "the choose-a-course landing page", "classroom": "assure"}
    await card_skill.run(action="sync", live=json.dumps(state))
    while not stop.is_set():
        task = asyncio.ensure_future(card_skill.run(action="wait", since=str(boot), seen=seen))
        while not task.done() and not stop.is_set():
            await asyncio.sleep(0.05)
        if not task.done():
            task.cancel(); break
        r = task.result().get("request")
        if not r: continue
        seen = r["id"]; handled.append(r)
        await card_skill.run(action="ack", seen=seen)
        if r["action"] == "goto" and r.get("page") == "recap":
            state = {"on_screen": "the lesson", "course": "events", "recap": {"step": 1, "steps": 5, "step_ready_for_next": False}, "task": {"type": "sql", "prompt": "recap q1", "language": "SQL filter"}}
        elif r["action"] == "search":
            state = {"on_screen": "the how-do-I page", "howto": {"showing": "search results", "searched_for": r["search"], "key_terms": ["EventKey: the dedup key"], "nothing_found": r["search"] == "zzz"}}
        elif r["action"] == "howto":
            state = {"on_screen": "the how-do-I page", "howto": {"topic": r.get("topic"), "question": r.get("question"), "steps": r.get("steps")}}
        elif r["action"] == "more":
            state["extra_practice"] = {"tasks": 2, "on_now": state.get("extra_practice", {}).get("on_now", 0) + 1, "offered": True}
        elif r["action"] == "goto":
            if r.get("page") == "landing" or not r.get("course"):
                state = {"on_screen": "the choose-a-course landing page"}
            else:
                L = LESSONS[r["course"]]
                if r["idx"] >= len(L): state = {"on_screen": "the sandbox", "course": r["course"], "lesson_free": True, "learner_answer": ""}
                else: state = {"on_screen": "the lesson", "course": r["course"], "lesson_id": L[r["idx"]]["id"], "lesson_number": r["idx"] + 1, "lesson_title": L[r["idx"]]["title"], "lesson_explain": "explain", "task": {"type": "sql", "prompt": "do it", "language": "SQL filter"}, "correct_answer": "Severity = 5 AND Ack = 0", "why": "because", "hint": "a hint", "attempts": 0}
        elif r["action"] == "next_step": state["final_shift"] = {"step": state.get("final_shift", {"step": 1})["step"] + 1, "steps": 5, "step_ready_for_next": False}
        elif r["action"] == "retake": state["final_shift"] = {"step": 1, "steps": 5, "step_ready_for_next": False}
        elif r["action"] == "hint": state["hint_seen"] = True
        elif r["action"] == "check":
            state["attempts"] = state.get("attempts", 0) + 1
            state["last_check"] = {"correct": state.get("learner_answer", "").replace(" ", "").lower() == "severity=5andack=0", "answer": state.get("learner_answer"), "msg": "", "at": time.time() * 1000}
        elif r["action"] == "showme": state["answer_shown"] = True
        elif r["action"] in ("answer", "run"):
            state["learner_answer"] = r["answer"]; state["last_run"] = {"alarms_returned": 7}
            if r["action"] == "answer" and state.get("task"):
                state["attempts"] = state.get("attempts", 0) + 1
                state["last_check"] = {"correct": r["answer"].replace(" ", "").lower() == "severity=5andack=0", "answer": r["answer"], "msg": "", "at": time.time() * 1000}
        await card_skill.run(action="sync", live=json.dumps(state))
ok = True
def expect(label, cond, got=None):
    global ok; ok = ok and bool(cond); print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  -> {json.dumps(got, default=str)[:400]}"))
async def go():
    r = await card_skill.run(); expect("open -> course page, first visit", r["view"] == "classroom" and r["course"] is None and "first visit" in r["for_ainara"], r)
    r = await card_skill.run(course="filters"); expect("open course 'filters' -> events lesson 1", r.get("course") == "events" and r.get("idx") == 0, r)
    r = await card_skill.run(course="kql", lesson="3"); expect("open kql lesson 3 -> analytics idx 2", r.get("course") == "analytics" and r.get("idx") == 2, r)
    r = await card_skill.run(page="sandbox"); expect("open sandbox", r.get("idx") == 8 and r["now_showing"]["lesson"] == "the sandbox", r)
    r = await card_skill.run(page="recap"); expect("open with a recap", r.get("page") == "recap" and r.get("course") is None, r)
    r = await card_skill.run(page="howto", lesson="how do I set up a new alarm"); expect("open on the how-do-I page with a topic", r.get("page") == "howto" and r.get("howto") == "new-alarm" and r.get("course") is None, r)
    r = await card_skill.run(page="how do I"); expect("open on the how-do-I list", r.get("page") == "howto" and "howto" not in r, r)
    # nothing on screen
    for f in (main.HEARTBEAT_FILE, main.LIVE_FILE): f.unlink(missing_ok=True)
    r = await howto.ToolsAssurehowto().run(question="how do I create a filter?"); expect("how-to while closed: prepared answer + offer to open", r["classroom_open"] is False and r["prepared_answer"]["where"].endswith("Filters") and "page = howto" in r["for_ainara"] and r.get("practise_it_in", "").startswith("Event list"), r)
    r = await howto.ToolsAssurehowto().run(question="how do I export alarms to a spreadsheet", steps="Open the event list | Load the filter | Click the download icon"); expect("how-to while closed: no prepared answer -> general guidance", "prepared_answer" not in r and r["your_steps"][2] == "Click the download icon" and "general guidance" in r["for_ainara"], r)
    r = await howto.ToolsAssurehowto().run(search_for="EventKey"); expect("search while closed -> offers to open", r["success"] is False and "page = howto" in r["open_with"], r)
    expect("split_steps handles numbered text", howto.split_steps("1. Open Filters 2. Clone one 3) Save") == ["Open Filters", "Clone one", "Save"], howto.split_steps("1. Open Filters 2. Clone one 3) Save"))
    r = await change.ToolsChangeassurelesson().run(lesson="next"); expect("change lesson while closed -> told to open", r["success"] is False and "open_with" in r, r)
    r = await check.ToolsCheckmyfilter().run(); expect("check while closed -> offers to open", r["classroom_open"] is False, r)
    r = await show.ToolsShowassureanswer().run(); expect("show while closed -> open_with show_answer", "show_answer = yes" in r.get("open_with", ""), r)
    r = await change.ToolsChangeassurelesson().run(name="Dave"); expect("name saved while closed", main.read_json(main.PROGRESS_FILE).get("profile", {}).get("name") == "Dave", r)
    # other classroom on screen
    med = Path(os.environ["HOME"]) / ".ainara_med"; med.mkdir(); (med / "heartbeat").touch()
    r = await check.ToolsCheckmyfilter().run(); expect("medical on screen -> redirected", "MEDICAL" in r["for_ainara"], r)
    (med / "heartbeat").unlink()
    # with a card listening
    stop = asyncio.Event(); card = asyncio.ensure_future(fake_card(stop)); await asyncio.sleep(0.6)
    r = await check.ToolsCheckmyfilter().run(); expect("check on course page", r.get("on_screen") == "the course page", r)
    r = await howto.ToolsAssurehowto().run(question="why did my alarm disappear", steps="Check Ack | Check clears"); expect("how-to while open: prepared answer shown on screen", r["classroom_open"] and handled[-1]["action"] == "howto" and handled[-1]["topic"] == "alarm-disappeared" and "diagram" in r["for_ainara"], r)
    r = await howto.ToolsAssurehowto().run(question="how do I export alarms to a spreadsheet", steps="Open the event list | Load the filter | Click the download icon"); expect("how-to while open: Ainara's own steps sent for drawing", handled[-1]["topic"] is None and len(handled[-1]["steps"]) == 3 and "flow diagram" in r["for_ainara"], r)
    r = await howto.ToolsAssurehowto().run(search_for="EventKey"); expect("search: results on screen and read back", handled[-1]["action"] == "search" and r["results"]["key_terms"] and "found" in r["for_ainara"], r)
    r = await howto.ToolsAssurehowto().run(search_for="zzz"); expect("search: nothing found", "found nothing" in r["for_ainara"], r)
    r = await howto.ToolsAssurehowto().run(); expect("how-to with no question: list shown", handled[-1]["action"] == "howto" and handled[-1]["topic"] is None and "list of questions" in r["for_ainara"], r)
    r = await change.ToolsChangeassurelesson().run(page="landing")
    r = await change.ToolsChangeassurelesson().run(course="events", lesson="3"); expect("goto events lesson 3", r["success"] and r["now_showing"]["title"] == "Working an alarm: acknowledge, own, journal" and r.get("task") == "do it", r)
    r = await change.ToolsChangeassurelesson().run(lesson="next"); expect("next -> lesson 4", r["success"] and r["now_showing"]["lesson"] == "lesson 4 of 14", r)
    r = await change.ToolsChangeassurelesson().run(lesson="previous"); expect("previous -> lesson 3", r["now_showing"]["lesson"] == "lesson 3 of 14", r)
    r = await check.ToolsCheckmyfilter().run(wants_hint="yes"); expect("hint opens on screen", r["success"] and r.get("hint_seen") and handled[-1]["action"] == "hint", r)
    r = await check.ToolsCheckmyfilter().run(spoken_answer="Severity = 4"); expect("spoken wrong answer marked", "not right yet" in r["for_ainara"] and r["last_check"]["correct"] is False, r)
    r = await check.ToolsCheckmyfilter().run(spoken_answer="Severity = 5 AND Ack = 0"); expect("spoken right answer marked", "RIGHT" in r["for_ainara"] and r["last_check"]["correct"] is True, r)
    n = len(handled); r = await check.ToolsCheckmyfilter().run(); expect("check again when already right -> no second press", len(handled) == n and "RIGHT" in r["for_ainara"], r)
    await card_skill.run(action="sync", live=json.dumps({**main.read_json(main.LIVE_FILE), "learner_answer": "Severity = 3"}))
    r = await check.ToolsCheckmyfilter().run(); expect("'check my filter' presses Check on a typed answer", handled[-1]["action"] == "check" and "pressed Check" in r["for_ainara"], r)
    r = await show.ToolsShowassureanswer().run(); expect("show answer", r["classroom_open"] and r.get("correct_answer") and handled[-1]["action"] == "showme", r)
    r = await change.ToolsChangeassurelesson().run(course="event analytics"); expect("switch course by name", r["now_showing"]["course"] == "Event Analytics", r)
    r = await change.ToolsChangeassurelesson().run(page="sandbox"); expect("sandbox", r["now_showing"]["lesson"] == "the sandbox", r)
    r = await check.ToolsCheckmyfilter().run(spoken_answer="Node : RAN1_*", language="kql"); expect("sandbox run", r.get("on_screen") == "the sandbox" and handled[-1]["action"] == "run" and handled[-1]["language"] == "kql" and r.get("last_run"), r)
    r = await change.ToolsChangeassurelesson().run(course="events", lesson="3")
    r = await change.ToolsChangeassurelesson().run(lesson="more"); expect("extra practice: none on this lesson -> explained", r["success"] is False and "no extra practice" in r["for_ainara"], r)
    await card_skill.run(action="sync", live=json.dumps({**main.read_json(main.LIVE_FILE), "extra_practice": {"tasks": 2, "on_now": 0, "offered": False}}))
    r = await change.ToolsChangeassurelesson().run(lesson="give me another one"); expect("extra practice: refused before the main task is right", r["success"] is False and "main task" in r["for_ainara"], r)
    await card_skill.run(action="sync", live=json.dumps({**main.read_json(main.LIVE_FILE), "extra_practice": {"tasks": 2, "on_now": 0, "offered": True}}))
    r = await change.ToolsChangeassurelesson().run(lesson="more practice"); expect("extra practice: started", handled[-1]["action"] == "more" and r["extra_practice"]["on_now"] == 1, r)
    r = await change.ToolsChangeassurelesson().run(page="quiz me"); expect("recap: started", handled[-1].get("page") == "recap" and r.get("recap", {}).get("steps") == 5 and r.get("task") == "recap q1", r)
    r = await change.ToolsChangeassurelesson().run(lesson="next"); expect("recap: next refused until right", r["success"] is False and "recap" in r["for_ainara"], r)
    await card_skill.run(action="sync", live=json.dumps({"on_screen": "the recap result", "course": "events", "recap": {"step": 5, "steps": 5}, "result": {"score": 80, "revisit": ["Your first filter"]}}))
    r = await check.ToolsCheckmyfilter().run(); expect("recap: result reported", r.get("result", {}).get("score") == 80 and "recap" in r["for_ainara"], r)
    r = await change.ToolsChangeassurelesson().run(course="final"); expect("open the final shift", r["now_showing"]["course"] == "Final shift" and "FINAL SHIFT" in r["for_ainara"], r)
    await card_skill.run(action="sync", live=json.dumps({**main.read_json(main.LIVE_FILE), "final_shift": {"step": 1, "steps": 5, "step_ready_for_next": False}}))
    n = len(handled); r = await change.ToolsChangeassurelesson().run(lesson="next"); expect("final: next step refused until the step is right", r["success"] is False and len(handled) == n, r)
    await card_skill.run(action="sync", live=json.dumps({**main.read_json(main.LIVE_FILE), "final_shift": {"step": 1, "steps": 5, "step_ready_for_next": True}}))
    r = await change.ToolsChangeassurelesson().run(lesson="next step"); expect("final: next step", handled[-1]["action"] == "next_step" and r["final_shift"]["step"] == 2, r)
    r = await check.ToolsCheckmyfilter().run(wants_hint="yes"); expect("final: hint warns about points", "costs 5 points" in r["for_ainara"], r)
    r = await change.ToolsChangeassurelesson().run(lesson="take it again"); expect("final: retake", handled[-1]["action"] == "retake" and r["final_shift"]["step"] == 1, r)
    await card_skill.run(action="sync", live=json.dumps({"on_screen": "the final shift result", "course": "final", "final_shift": {"step": 5, "steps": 5}, "result": {"score": 85, "passed": True}}))
    r = await check.ToolsCheckmyfilter().run(); expect("final: result reported", r.get("result", {}).get("score") == 85, r)
    r = await change.ToolsChangeassurelesson().run(page="landing"); expect("back to course page", r["success"] and handled[-1].get("page") == "landing", r)
    r = await change.ToolsChangeassurelesson().run(spoken_tips="off"); expect("spoken tips off", handled[-1].get("voice_cues") is False and r["success"], r)
    stop.set(); await card
    r = await close.ToolsCloseassureclassroom().run(); expect("close", r["view"] == "close" and r["name"] == "Dave" and time.time() - r["issued_at"] < 5, r)
    png = "data:image/png;base64," + __import__("base64").b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 20).decode()
    r = await card_skill.run(action="save_certificate", image=png); expect("certificate saved under HOME", r["success"] and os.path.exists(r["path"]) and r["path"].startswith(os.environ["HOME"]), r)
    r = await card_skill.run(action="save_certificate", image="data:text/html;base64,AAAA"); expect("non-PNG certificate refused", r["success"] is False, r)
    for s in (card_skill, change.ToolsChangeassurelesson(), check.ToolsCheckmyfilter(), show.ToolsShowassureanswer(), close.ToolsCloseassureclassroom(), howto.ToolsAssurehowto()):
        expect(f"matcher_info on {type(s).__name__}", len(s.matcher_info) > 100)
asyncio.run(go()); print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
