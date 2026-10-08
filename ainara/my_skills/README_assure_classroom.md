# Assure1 Classroom for Ainara

_Installed in this folder on 2026-10-07. The tests are in `Claude outputs/assure_classroom_tests/`._

A beginner's course in administering alarms in Assure1, built as Ainara user skills the same
way as the Coding and Medical Classrooms. Ainara is the tutor: you talk to her ("check my
filter", "give me a hint", "next lesson") while working in one classroom screen with a
built-in **alarm simulator**. You write a filter or query, press Run, and the matching alarms
are listed, coloured by severity.

**Everything is simulated.** The screen holds 32 dummy live alarms and 180 dummy history
records. It never connects to a real Assure1, and every name is made up:

| Dummy name | Stands for |
|---|---|
| `TST1_001` … `TST1_006` | NGN cabinets |
| `RAN1_001` … `RAN1_008` | RAN sites |
| `CORE1_001`, `CORE1_002` | Core routers |
| `TX1_001` … `TX1_003` | Transmission nodes |
| `SRC_A` … `SRC_D` | Alarm sources (SubMethod) |

## Courses (27 lessons, a final assessment, a recap quiz and a sandbox)

| Course | Lessons | Hands-on with |
|---|---|---|
| Event list, filters & displays | 11, ending in a project (a RAN working view) | clicking rows in the event list; operator tools (acknowledge, own, journal); SQL `WHERE` filters; a display; a filter group's restriction filter |
| Where alarms come from | 7 | an EventKey (deduplication simulator); two rule-writing lessons (set up a new alarm, tidy a noisy one); clear pairing; a threshold on a CPU chart |
| Event Analytics | 8, ending in a project (the noisiest RAN sites) | KQL searches; Console (Elasticsearch) requests |
| Final shift | 1 assessment of 5 scored steps: 20 points each, 70 of 100 passes | a filter, a display, a rules question, a KQL search, a Console count |

Five lessons are multiple choice; the rest are done in a simulator. Eleven lessons carry one
or two optional **extra practice** tasks, offered once the main task is right. The **quick
recap** on the main page asks five scored questions drawn at random from finished lessons.
Five lessons have a diagram (the alarm pipeline, a filter's anatomy, deduplication, clear
pairing, live list versus history).

Any query that returns the same alarms as the model answer is marked right, so there is no
single accepted spelling. A wrong answer says how many alarms came back and names one row
that should not be there or is missing; the simulators say what the result did wrong (for
example "a clear closed the fan alarm too"). The Console is read-only: `PUT`, `POST` and
`DELETE` are refused with an explanation.

## Files

    my_skills/tools/assureclassroom.py        opens the classroom (the only skill with the main screen)
    my_skills/tools/changeassurelesson.py     "next lesson", "switch to event analytics", "open the sandbox", "call me Dave"
    my_skills/tools/checkmyfilter.py          "check my filter", "is it Severity equals 5 and Ack equals 0?", "give me a hint"
    my_skills/tools/showassureanswer.py       "show me the answer", "talk me through it"
    my_skills/tools/closeassureclassroom.py   "close my Assure classroom"
    my_skills/tools/assurehowto.py            "how do I create a filter?", "why did my alarm disappear?" (steps + a diagram)
    my_skills/_components/ToolsAssureclassroom/index.html
    my_skills/_components/ToolsAssureclassroom/lessons.json
    my_skills/_components/ToolsAssureclassroom/howto.json     (the How-do-I answers; written by engine_test.js, like lessons.json)
    my_skills/_components/ToolsCloseassureclassroom/index.html

**Restart Ainara** so Orakle picks up the new skills, then say **"open my Assure classroom"**.
No extra dependencies (Python standard library only).

## How it fits together

Same design as the Medical Classroom:

- **One screen.** Only `assureclassroom` has a screen. The other four leave a request in
  `~/.ainara_assure/request.json`; the open classroom collects it through one long-poll
  (`wait`, 25 s), acts, and answers `ack`. If no screen answers, Ainara is told to open the
  classroom where you asked to go.
- **Ainara can see your work.** The screen `sync`s to `~/.ainara_assure/live.json`: the
  lesson, the task, what you typed, the alarms your last Run returned (or the error), tries,
  hint used, and the model answer (for Ainara to coach towards, not to read out).
- **Spoken answers count.** Say a filter out loud and `checkmyfilter` passes it to the
  screen, which types it in, runs it and marks it like a typed one. In the sandbox a spoken
  query is just run.
- **Spoken tips** come from the screen through PyBridge (`POST :8101/framework/tts`), with
  captions. ⚙ → Test Ainara's voice. Turn them off in the ⚙ menu or say "stop talking during
  lessons".
- **Progress** is in `~/.ainara_assure/progress.json`, apart from `~/.ainara_learn/` (coding)
  and `~/.ainara_med/` (medical). If one of those classrooms is the one on screen, the Assure
  helper skills tell Ainara to use that classroom's own skills.
- **Closing by voice** uses the same Polaris listener as the other classrooms
  (`ainara:close-documents` in `polaris/components/com-ring.js`).

## Tested, and not tested

Tested here:

- every lesson's model answer, and about 40 other filters and queries, against the three
  query engines (`node engine_test.js <index.html> [lessons.json]`; it also rewrites
  `lessons.json`, so run it after editing lessons);
- the five skills against a stand-in for the open screen, in a temporary home folder
  (`venv/bin/python test_skills.py ainara/my_skills/tools`);
- the screen itself in a browser in preview mode (no Ainara): lessons, checking, hints, show
  answer, the sandbox, and requests arriving from the helper skills.

Not tested, because Ainara was running and was not restarted: the skills loaded inside the
real Orakle, Ainara choosing the right skill from what you say, the voice tips, and closing
by voice.

"Next lesson" and "check my answer" are phrases the other classrooms also listen for. With
only the Assure classroom open, each helper checks which classroom is on screen and redirects
Ainara if it was called for the wrong one. The Coding and Medical helper skills were not
changed, so they do not yet know about the Assure classroom.

## Accuracy

Field meanings, filter and display form fields follow Oracle's Unified Assurance 6.1
documentation. Severity names, the rule example, and the Broker Control, Rules, Thresholds
and Mechanizations menu paths are from general product knowledge and were not checked
against your version. The simulator is a teaching model: it covers the common SQL, KQL and
query-DSL features, not all of them.

## Editing lessons

Lessons are in `index.html`, in the `LESSONS` object inside the block marked
`//<<ENGINE … //ENGINE>>`, with the dummy alarms (`RAW`) just above. A query task needs only
`answer`: whatever returns the same alarms is right. Keep to dummy names.

## Changes

- **2026-10-07 (later).** Every lesson now works by voice. Spoken answers are understood for
  the display task ("Severity, LastReported, Count, Node and Summary, sorted by Severity
  descending"), the EventKey task ("Node, SubNode and EventType") and multiple choice by
  letter, position ("the second one") or wording. "Check my filter" with nothing said now
  presses Check on the screen, so what you typed is run, the alarms are listed and the lesson
  is marked. Ainara introduces a lesson opened by clicking Next. The two lessons with an empty
  output panel (working safely; Search Profiler and management) now show alarms or the index
  list. "Lesson 4" said with a course name no longer risks landing on the project.
- **2026-10-07 (final shift).** Added the Final shift: one morning-shift scenario with five
  mixed steps and a score out of 100. Right first time with no hint scores 20, a hint or a
  second try 15, later 10, Show answer 0. 70 passes, marks the course done and draws a
  certificate, which Save certificate writes to `~/Pictures/Assure1 Classroom/`. Best score
  is kept. By voice: "take the final shift", "next step", "take it again". Ainara is told it
  is a test, and to say what a hint costs before giving one.
- **2026-10-07 (lessons, second pass).** Main page restyled to match the Coding Classroom,
  with the gold Ainara logo, a demo event list and the course outcomes. Lessons: six new ones
  (operator tools, filter groups, two rule-writing lessons, thresholds, and clear pairing
  rebuilt as a simulator), "Reading the event list" now asks you to click a row, optional
  extra practice tasks, a quick recap quiz, and five diagrams. By voice: "give me another
  one", "quiz me", and spoken answers for every new task type. The lesson code for these
  additions is in the block headed COURSE ADDITIONS inside the engine section of
  `index.html`. Lesson ids are kept, so earlier progress still counts; lesson numbers in the
  first two courses have shifted.
- **2026-10-08 (How do I…?).** A new page in the classroom, opened from the main page, the
  lesson header, or by asking Ainara a how-to question. It holds 19 prepared answers (filters,
  displays, the event list, rules and alarms, history, getting around). Each shows where to
  click, the steps, a risk label (safe to do yourself, or agree it with a senior admin
  first), a numbered flow diagram, and a button to the lesson that practises it. The new
  `assurehowto` skill picks the answer that fits the question and shows it without reopening
  the screen. For a question with no prepared answer, Ainara's own steps are drawn as a flow
  diagram and marked as general guidance that has not been checked against your version.
  The answers are in the `HOWTO` list in `index.html`; run `engine_test.js` after editing
  them so `howto.json` is rewritten for the skill.
- **2026-10-08 (search).** The search box on the How-do-I page now searches everything:
  prepared questions (including their steps), lessons (title, key terms, text and task) and
  key terms. Results are grouped; a question opens with its diagram, a lesson opens in the
  classroom, a key term shows its meaning with a link to its lesson. There is a search box on
  the main page too, and by voice: "search for EventKey", "find the lesson on thresholds".
