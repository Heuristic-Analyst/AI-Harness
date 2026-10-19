# 04 — agent.py: the Agent class, the loop, checkpoints, subagents

**In this chapter:** (each section then goes function by function, or tool by tool)
- Module level: imports, litellm, the tool loader
- Module level: the prompt strings and constants
- The two helper functions
- `Agent.__init__` (`agent.py:125-156`)
- `build_system` (`agent.py:159-190`)
- `pick_skills` (`agent.py:192-194`)
- `refresh_system` (`agent.py:196-198`)
- `record` (`agent.py:201-207`)
- `add` (`agent.py:209-216`)
- `moved` (`agent.py:218-222`)
- `say` (`agent.py:225-230`)
- `print_part` (`agent.py:232-241`)
- `show` (`agent.py:243-257`)
- `run_tool` (`agent.py:260-271`)
- `save_result` (`agent.py:273-281`)
- `shows` (`agent.py:283-287`)
- `run_tools` (`agent.py:289-304`)
- `ask` (`agent.py:307-340`) — the loop
- `tokens` (`agent.py:343-344`)
- `maybe_checkpoint` (`agent.py:346-358`)
- `make_room` (`agent.py:360-379`)
- `write_checkpoint` (`agent.py:381-400`)
- Goal
- Decisions
- Facts
- Open
- Files
- `clear` (`agent.py:402-407`)
- `last_tasks` (`agent.py:409-431`)
- `move_old_results` (`agent.py:433-449`)
- `delegate` (`agent.py:452-497`)
- `tell` (`agent.py:499-506`)
- `report_head` (`agent.py:508-510`)
- `report_status` (`agent.py:512-522`)
- `close_children` (`agent.py:524-532`)
- `close` (`agent.py:534-539`)
- What this chapter hands to the rest of the guide

---

`agent.py` is one class, `Agent`, plus a tool loader and two small helpers. One `Agent` object is **one conversation with
one model**.

- The conversation is a plain list, `self.messages` (`agent.py:156`): dicts in exactly the shape the model API wants.
- The agent also owns a **folder** (`agent.py:127`): `log.jsonl` (every message, word for word, appended only),
  `checkpoint.md` (its own notes), `results/` (tool results too long for the context), `agents/` (its subagents).
- Sending a message = append it, call the model, append the reply, run the tool calls, append their results, repeat until
  the model answers without a tool (`ask`, `agent.py:307`). That is the loop.
- Nothing is ever summarized. When the list gets too big the agent writes a checkpoint in its own words and the list is
  rebuilt as *system prompt + checkpoint + the last task* (`maybe_checkpoint`, `make_room`). The log keeps every word.
- The same class is the agent you talk to (depth 1, prints to your terminal) and every subagent (depth 2/3, writes to a
  transcript file). The differences: instructions, tool list, depth, and where the output goes.

The rest of the file is bookkeeping around one `litellm.completion` call — plus care about a context that fills mid-task.

## Module level: imports, litellm, the tool loader

**Imports** (`agent.py:14-22`): `os`, `re`, `json`, `datetime`, `logging`, `importlib.util`, `threading` cover walking the
tools folder, matching result pointers, parsing arguments, timestamping log lines, quietening litellm, loading files by
path and parallel threads. `import litellm` (`agent.py:21`) is the only way this file talks to a model. `from config import
*` (`agent.py:22`) brings every setting and helper — names not defined here come from `config.py`.

**Three litellm lines** (`agent.py:24-26`): `setLevel(logging.ERROR)` on `"LiteLLM"` (it is chatty); `drop_params = True`
(a parameter the model cannot do is dropped instead of raising — without it, changing `MODEL` could break every call);
`suppress_debug_info = True` (no "Provider List" block when litellm cannot identify a model).

**The tool loader** (`agent.py:29-49`) runs **once, at import time** (`main.py` does `from agent import Agent`), so
`Agent.__init__` already has the whole menu.

- `TOOLS` (`agent.py:31`) name → description in the model's format; `FUNCTIONS` (`agent.py:32`) name → the Python
  function; `FOUND_IN` (`agent.py:33`) name → its file.
- `os.walk(TOOLS_DIR)` (`agent.py:34`) walks `tools/` and every folder below it; folders are for humans, the model only
  sees the name inside `TOOL`. `subfolders[:] = sorted(...)` (`agent.py:35`) writes into the list `os.walk` itself uses
  next, so `__pycache__`, `.git`, `_drafts` are never entered, and `sorted` keeps the order identical every run (so
  `self.tools`, which goes into every request, is stable).
- `if not file.endswith(".py") or file.startswith("_")` (`agent.py:37`) — `README.md` is not a tool; `_`-files are helpers
  for the tools beside them (`tools/results/_results.py`).
- `where = os.path.relpath(path, HERE)` (`agent.py:40`) → `tools/notebook/nb_add.py`; `spec_from_file_location(
  where[:-3].replace(os.sep, "."), path)` (`agent.py:41`) loads it as `tools.notebook.nb_add`, and that dotted name is what
  lets a tool write `from . import _notebook`. I loaded `tools/notebook/nb_add.py` that way in the sandbox and it worked —
  the folders act as namespace packages, no `__init__.py` needed.
- `module_from_spec` + `exec_module` (`agent.py:42-43`) really run the file, so a tool that raises on import kills the
  program at startup, not at call time.
- `name = module.TOOL["name"]` (`agent.py:44`) — the model's name comes from the file's `TOOL` dict, **not** the file name.
  `if name in TOOLS: raise SystemExit(...)` (`agent.py:45-46`) stops the program when two files claim one name, naming both
  — the only reason `FOUND_IN` exists.
- `TOOLS[name] = {"type": "function", "function": module.TOOL}` (`agent.py:47`) is the envelope litellm/OpenAI expects in
  `tools=`; `FUNCTIONS[name] = module.run` (`agent.py:48`) is the function half; `FOUND_IN[name] = where` (`agent.py:49`).

## Module level: the prompt strings and constants

Not settings: text pasted into messages, each fixing a specific failure.

### `SUBAGENT_RULES` (`agent.py:52-61`)

Every subagent's system prompt gets this block (`agent.py:161-162`): you never talk to the user, settle unclear things
with a stated assumption, your final message is your only report, start it with `DONE:`, `BLOCKED:` or `QUESTION:`, keep
it under `REPORT_LIMIT` characters, put details in files, say where every claim comes from. A subagent's reader is another
model: without it you get chatty prose, a buried result, or a question the user never sees. One literal with
`format(REPORT_LIMIT, ",")` spliced in (`agent.py:59`, default `8,000`, `config.py:34`). The first word is parsed back by
`report_status` (`agent.py:512`) to decide whether the subagent stays alive — change the words here and you must change
them there. Without it the parent cannot classify reports, so every subagent dies after one task and `tell` always answers
"no live subagent called …".

### `AUTO_MODE` (`agent.py:63-66`)

Appended when `self.mode == "auto"` (`agent.py:184-185`): the user is not available, you decide, answer your subagents'
`QUESTION` reports yourself. `/mode auto` (`main.py:196`) means nobody is watching; without this text the model has no way
to know it should decide instead of asking, so it stalls. Without it, auto mode is a no-op flag (`self.mode` starts as
`"ask"`, `agent.py:132`).

### `CHECKPOINT_PROMPT` (`agent.py:68-84`)

The user message sent *only* to ask for a checkpoint (`agent.py:385`), and the thing that replaces summarizing: the context
will be cleared right after this message, so the model must write down everything needed to continue, in exactly these
sections — Goal, Decisions, Facts, Done, Open, Files, Questions. Fixed sections make the next context predictable and
dense. Two details matter: "It replaces your previous checkpoint … so carry over everything … still true" (the new text
overwrites the file), and "Do not call tools" (a call could not run anyway: `tool_choice="none"`, `agent.py:390`). Without
it the model writes free-form musings, or nothing, and the cleared agent restarts blind.

### `EMERGENCY_NOTE` (`agent.py:86-87`)

Three lines added to `CHECKPOINT_PROMPT` for a mid-task checkpoint only (`agent.py:385`): you are in the MIDDLE of a task,
say exactly where you are and what you were about to do next. A normal checkpoint is written after a task, where "what is
left" is fuzzy; a mid-task one must be precise. Without it the notes read like a finished job and the task silently stops.

### `GO_ON` (`agent.py:89-92`)

Appended to the current question when the context is cleared mid-task (`agent.py:377`): you were interrupted, the
checkpoint says where you were, earlier results are in `results/`. Without it, the last thing the model sees is the message
it was already working on, which read cold looks like a fresh request — so the whole task starts over, forever.

### `WHOLE_RESULTS` (`agent.py:94`)

`["load_skill", "read_memory", "read_result", "search_result"]`. These tools exist to *read* something, so a file pointer
to their output is a pointer to a pointer; they are also short by their own limits. Checked at `agent.py:269`. Without it a
9,000-character `SKILL.md` becomes a pointer and the agent must call `read_result` to see the skill it just asked for.

### `MOVED` (`agent.py:96`)

The literal prefix `"[moved out of your context to make room: "`, marking a tool message that used to hold a result and now
holds a pointer. `move_old_results` uses it to skip messages already moved (`agent.py:438`) and to build the new text
(`agent.py:447`); the string doubles as the record of "done". Without it every pass of `make_room` would re-save the same
pointer into a new file.

## The two helper functions

### `preview(path, text)` (`agent.py:99-109`)

**Why** — a tool can return a megabyte. The model needs to know it happened, roughly what is in it, and where the rest
lives; a raw dump fills the context, a bare "written to file" tells it nothing.

- `lines = text.split("\n")` (`agent.py:101`) — start and end are counted in lines.
- `head = "\n".join(lines[:40])[:3000]` (`agent.py:102`) — first 40 lines, then cut to 3,000 characters, so 40 enormous
  lines cannot blow through it.
- `tail = "\n".join(lines[-20:])[-1500:] if len(lines) > 40 else ""` (`agent.py:103`) — last 20 lines, at most 1,500
  characters from the end; with 40 lines or fewer the head already has everything.
- `answer = "[result: " + path + ", " + format(len(text), ",") + " characters, " + format(len(lines), ",") + " lines. " …`
  (`agent.py:104-106`) — header with thousands separators, then "this is only the start" (or "… the start and the end"),
  then the hint that `read_result` and `search_result` show the rest; `if tail: answer += "\n...\n" + tail`
  (`agent.py:107-108`) marks the gap.

**Example** — an 8,040-character, 120-line result saved as `results/000001-sandbox_shell.txt` starts exactly like this:

```
[result: results/000001-sandbox_shell.txt, 8,040 characters, 120 lines. this is only the start and the end: read_result and search_result show the rest]
```

then the first 40 lines, a line with only `...`, then the last 20. (This chapter's own tool output came back through this
function, so the header is real.) **Gotcha** — `preview` is only called for results over `RESULT_TO_FILE`
(`agent.py:269`), so the header is always true in practice.

### `highest_result(folder)` (`agent.py:111-121`)

**Why** — result files are named `000042-sandbox_shell.txt` and a name must never be reused in one conversation, because
old messages and checkpoints still point at those files; restarting the counter at 0 after `/open` would overwrite them.
`if os.path.isdir(results)` (`agent.py:116`) is false for a new conversation, which is not an error;
`number = file.split("-", 1)[0]` (`agent.py:118`) turns `"000042-sandbox_shell.txt"` into `"000042"`, and
`if number.isdigit(): highest = max(highest, int(number))` (`agent.py:119-120`) ignores a stray `README.md`. Called once,
from `__init__` (`agent.py:134`).

**Example** — `000001-sandbox_shell.txt`, `000002-nb_run.txt`, `README.md` → returns `2`, so the next result is `000003-…`.

**Gotcha** — it counts the highest number *present*, so deleting the newest file lets that number be handed out twice. The
code assumes the folder is only ever appended to.

## `Agent.__init__` (`agent.py:125-156`)

**Why** — it builds one conversation: identity, folder, limits, the tools and skills this agent may use, and message 0.
Signature `(name, instructions, tools, skills, folder, depth=1, memory=False, log=None)` (`agent.py:125`); `tools` and
`skills` are *specs* — `"all"` or a list of names (`main.py:30` passes `"all"` for both).

- `self.name` (`agent.py:126`), `self.folder` (`agent.py:127`) — log, checkpoint, results, subagents, created lazily by the first log line
  (`agent.py:205`), `self.instructions` (`agent.py:128`) — soul, template body or one-off text.
- `self.depth` (`agent.py:129`) — 1 talks to you, 2 subagent, 3 subagent of a subagent; gates `SUBAGENT_RULES`, the after-task
  checkpoint and creating subagents at all. `self.memory` (`agent.py:130`) — only main passes `True`. `self.log` (`agent.py:131`) — `None` =
  print, a file = write there; this one attribute makes main agent and subagent behave differently.
- `self.mode = "ask"` (`agent.py:132`); `self.logged_system = None` (`agent.py:133`) — prompt last logged, `None` = never, so the first
  `add` writes it; `self.results = highest_result(folder)` (`agent.py:134`) — result counter resumed from disk.
- `self.children = {}` (`agent.py:135`); `self.waiting = False` (`agent.py:136`) — `True` when its last report was a `QUESTION`, which keeps
  it alive across its parent's tasks; `self.spawned = 0` (`agent.py:137`) — for ids, **not** restored from disk, so after `/open` a
  new subagent is `worker-1` again and only its folder is made unique (`free_name`, `agent.py:487`).
- `self.lock` (`agent.py:138`) — result numbering and the id/slot section of `delegate`; tool calls are real threads. `self.busy`
  (`agent.py:139`) — a second `ask()` waits here, or two threads could interleave two conversations. `self.printing = None` (`agent.py:140`).
- `self.memory_seen` / `self.skills_seen` (`agent.py:141-143`) — what this agent last *saw* of `MEMORY.md` and each skill file;
  nothing here reads them, but `write_memory` / `edit_skill` refuse to overwrite a file changed meanwhile.
- `self.skill_choice = skills`; `self.skills = self.pick_skills()` (`agent.py:145-146`) — keep the spec, resolve it now, *before*
  the tool loop, which needs to know whether the agent has skills.
- The tool loop (`agent.py:148-153`): skip `delegate`/`tell` if `depth >= MAX_DEPTH` (`agent.py:150`), else append if `tools == "all" or tool
  in tools or (tool == "load_skill" and self.skills)` (`agent.py:152`). `self.tool_names` (`agent.py:154`) is the allow-list `run_tool`
  checks (`agent.py:264`).
- `self.messages = [{"role": "system", "content": self.build_system()}]` (`agent.py:156`) — the conversation, system prompt at
  index 0; later messages are appended or replaced, never reordered.

**Example** — a depth-2 subagent with `tools=["calculate", "sandbox_shell"], skills=["pdf"]` gets `["calculate",
"load_skill", "sandbox_shell", "delegate", "tell"]`; `load_skill` is there because it has a skill. At depth 3 the last two
disappear.

**Gotchas** — `tools="all"` is not literally all, and `MAIN_ONLY_TOOLS` are **not** filtered here (that is `delegate`,
`agent.py:471`). `TOOLS`/`FUNCTIONS` are an import-time snapshot, so a tool file deleted later stays callable; only `SKILLS`
is re-read live. A skill name that no longer exists is silently dropped.

## `build_system` (`agent.py:159-190`)

**Why** — the prompt is assembled from parts that change during the conversation (checkpoint, new skill, auto mode,
memory edit), so it can be rebuilt from scratch instead of patched. Comment at `agent.py:158`: "rebuilt from parts
whenever a part changes, never edited in place". Seven parts, in this order:

1. `system = self.instructions` (`agent.py:160`) — who the agent is.
2. `if self.depth > 1: system += "\n" + SUBAGENT_RULES` (`agent.py:161-162`) — every subagent, never the main agent.
3. Skills menu (`agent.py:163-173`): a paragraph ("step-by-step instructions … first call load_skill, then follow what it
   returns"), then one line per skill `- <name>[ [editable]]: <description>`; `if entry:` (`agent.py:167-169`) skips a skill
   deleted a second ago. `[editable]` comes from `config.py` and the folder, never from the file. With `create_skill`, three
   lines explain that `[editable]` skills may be changed and the user's may not.
4. Templates menu (`agent.py:174-180`), only with `delegate`: `templates()` is read from disk every build, so a template
   added while the program runs shows up. Descriptions only; instructions are read when a subagent is created.
5. Memory (`agent.py:181-183`): if `self.memory`, `read_text(MEMORY_FILE)` between `<memory>` tags, or `(empty)` — read
   fresh each build, which is why `write_memory` calls `refresh_system()`.
6. `if self.mode == "auto": system += "\n" + AUTO_MODE` (`agent.py:184-185`).
7. Checkpoint (`agent.py:186-189`): `read_text(.../checkpoint.md)` between `<checkpoint>` tags, with a line saying it is
   where you stand; `read_text` returns `""` for a missing file, so nothing appears before the first checkpoint.

**Example, abbreviated** — main agent with skills, templates, memory, auto mode and a checkpoint:

```
<soul text>
You have skills: step-by-step instructions for certain kinds of tasks. …
Available skills:
- pdf [editable]: read and fill PDF forms
You can create subagents with delegate: from a template below, or with your own instructions.
Templates:
- worker: Does one clearly defined task with the tools and reports the result.
<memory>…MEMORY.md…</memory>
Autonomous mode: the user is not available for questions. …
<checkpoint>…checkpoint.md…</checkpoint>
```

**Gotcha** — parts 3, 4, 5 and 7 read from disk on every call, so two builds need not be byte-identical even when nothing
changed inside the program. Called from `__init__` (`agent.py:156`), `refresh_system` (`agent.py:198`), `clear`
(`agent.py:404`) only.

## `pick_skills` (`agent.py:192-194`)

**Why** — the menu changes while the program runs (skills created, edited, deleted, added by another instance) and each
agent must follow it within its allowance. One line: `return [skill for skill in list(SKILLS) if self.skill_choice ==
"all" or skill in self.skill_choice]` (`agent.py:194`). `list(SKILLS)` snapshots the keys, so `SKILLS` being cleared and
refilled in another thread (`config.py:154-155`) cannot break the comprehension. Order is the menu's: your skills folder,
then `Learned` (`config.py:139`).

**Gotcha** — the snapshot prevents a crash, not a stale read: a skill created a millisecond later appears at the next
`refresh_system`, which the skill tools call themselves.

## `refresh_system` (`agent.py:196-198`)

**Why** — one call meaning "the world changed, rebuild the prompt". `self.skills = self.pick_skills()` (`agent.py:197`)
re-resolves the menu — also how a *new* skill becomes usable by an agent created before it existed.
`self.messages[0] = {"role": "system", "content": self.build_system()}` (`agent.py:198`) replaces message 0 in place; the
rest of the conversation is untouched.

**Gotchas** — it does **not** touch `self.tools`: a new skill never adds `create_skill`, and `load_skill` exists only if
the agent had skills at construction. Because `logged_system` still holds the old text, the next `add()` writes the new
prompt into the log (`agent.py:212-214`) — intended. Callers: `main.py:197`, `main.py:212`,
`tools/memory/write_memory.py:17`, `tools/skills/_skillfile.py:81`, `tools/skills/delete_skill.py:25`.

## `record` (`agent.py:201-207`)

**Why** — the log is the only complete record; the context gets cleared, the log never does.
`entry = {"time": datetime.datetime.now().isoformat(timespec="seconds"), "kind": kind}` (`agent.py:203`) puts `time` and `kind`
first so a reader can filter by kind (`message`, `system`, `checkpoint`, `context cleared`, `question taken back`,
`results moved to files`, `mode`); `entry.update(fields)` (`agent.py:204`) adds the caller's fields; `os.makedirs(self.folder,
exist_ok=True)` (`agent.py:205`) creates the folder lazily; `open(..., "a", encoding="utf-8")` + `json.dumps(entry,
ensure_ascii=False) + "\n"` (`agent.py:206-207`) appends one readable line, opening and closing the file each time so nothing
buffered is lost and another instance can read it.

**Example line** — `{"time": "2026-10-07T14:05:09", "kind": "message", "message": {"role": "user", "content": "hi"}}`.

**Gotcha** — no lock, and parallel tool threads do call it. On Linux, small appends to a file opened in append mode do not
interleave in practice, so lines stay whole, but the *order* inside a parallel burst is not deterministic.

## `add` (`agent.py:209-216`)

**Why** — one function keeps the two copies in sync: the list the model sees and the log a human reads. If the prompt
changed since it was last logged, log it first, or the log would contain messages the agent never worked with.
`if self.messages[0]["content"] != self.logged_system:` (`agent.py:212`) compares against the remembered copy; then
`record("system", …)` and update `logged_system` (`agent.py:213-214`); then `self.messages.append(message)` and
`self.record("message", message=message)` (`agent.py:215-216`).

**Example** — on a fresh agent the first `add({"role":"user","content":"hi"})` writes two lines (`system`, then the
message); every later plain `add` writes one.

**Gotcha** — `add` is the only way messages enter the list (`ask`, `run_tools`, `clear` all use it), which is why the log
cannot silently miss one.

## `moved` (`agent.py:218-222`)

**Why** — `/rename` moves the conversation folder on disk (`main.py:139`); every live `Agent` in that tree holds an
absolute path. `self.folder = new + self.folder[len(old):]` (`agent.py:220`) strips the old prefix and puts the new one on
— right at every depth, because a subagent's folder always sits *inside* its parent's. Then
`for child in self.children.values(): child.moved(old, new)` (`agent.py:221-222`) recurses.

**Gotcha** — if `old` is not really a prefix, the slice silently produces nonsense instead of an error. Closed subagents
are no longer in `children`, so their paths are never updated — they are gone, so nothing reads them.

## `say` (`agent.py:225-230`)

**Why** — two destinations, one call site: the main agent prints, a subagent writes into `transcript.md`. `if self.log:
self.log.write(text + end); self.log.flush()` (`agent.py:226-228`) flushes at once so `tail -f transcript.md` shows progress
live; otherwise `print(text, end=end, flush=True)` (`agent.py:229-230`). `end="\n"` by default; `print_part` passes
`end=""` to stream without line breaks.

**Gotcha** — `self.log` is one open file shared by many threads; Python serializes the writes and every call flushes, so
lines do not tear, but ordering across threads is not guaranteed.

## `print_part` (`agent.py:232-241`)

**Why** — a streaming reply arrives as tiny pieces, thinking and answer interleaved; the reader needs a `THINKING:` /
`ANSWER:` title whenever the kind changes, and nothing else.

- `if not text: return` (`agent.py:234-235`) — most chunks contain one kind only. This returns *before* the title logic, so
  an empty chunk never sets `self.printing`.
- `if kind == "THINKING" and not PRINT_THINKING and not self.log: return` (`agent.py:236-237`) — thinking is hidden in the
  terminal by default but always kept in transcripts.
- `if kind != self.printing: self.say("\n\n" + kind + ":" if self.printing else "\n" + kind + ":")`
  (`agent.py:238-239`) — the first title of a turn gets one leading newline, later ones two. Then `self.printing = kind`
  (`agent.py:240`) and `self.say(text, end="")` (`agent.py:241`).

**Example** — chunks `("THINKING","Let me "), ("THINKING","count."), ("ANSWER","There are "), ("ANSWER","three.")` print
`THINKING:Let me count.`, a blank line, `ANSWER:There are three.`, then the newline `show` adds.

## `show` (`agent.py:243-257`)

**Why** — one path for streaming and non-streaming that prints as it arrives and returns a single finished reply object.

- `chunks = []`; `self.printing = None` (`agent.py:245-246`) — collect every chunk (litellm rebuilds the reply from them), reset the
  title state per turn.
- `for chunk in (response if STREAM else [response]):` (`agent.py:247`) — with `STREAM` a generator, without it one object in a
  list, so the same body works. `chunks.append(chunk)` (`agent.py:248`); `if not chunk.choices: continue` (`agent.py:249-250`) — some chunks
  are pure bookkeeping (usage); skipping avoids an `IndexError`.
- `part = chunk.choices[0].delta if STREAM else chunk.choices[0].message` (`agent.py:251`) — `delta` is "what is new", `message` is
  "everything"; this one line is why both modes share the printing code.
- `self.print_part("THINKING", getattr(part, "reasoning_content", None))` (`agent.py:252`) — `getattr` with a default, because most
  models have no thinking field and would raise `AttributeError`; then `part.content` (`agent.py:253`); then `self.say("")` (`agent.py:254`),
  the newline the pieces did not emit.
- `if STREAM: response = litellm.stream_chunk_builder(chunks)` (`agent.py:255-256`) — glue the deltas back into a normal reply, so
  `reply.tool_calls`, `reply.content`, `reply.model_dump()` work as in the non-streaming case; `return
  response.choices[0].message` (`agent.py:257`).

**Gotcha** — `show` returns the *message*, not the response, so usage from this turn is dropped unless it is in `chunks`;
nothing in `agent.py` reads usage — `tokens()` re-counts instead.

## `run_tool` (`agent.py:260-271`)

**Why** — the adapter between "the model asked for a tool" and "a Python function runs". A failing tool must never kill
the task: its error goes back as text and the model can try something else.

- `name = call.function.name` (`agent.py:261`); `args = json.loads(call.function.arguments or "{}")` (`agent.py:263`) — arguments arrive as a
  **JSON string**, and a call without arguments arrives as `None` or `""`, hence `or "{}"`.
- `if name not in self.tool_names: raise Exception("you have no tool called '" + name + "'. yours: " + …)` (`agent.py:264-265`) — a
  hand-written allow-list; the error lists the agent's tools so the model can correct itself.
- `result = str(FUNCTIONS[name](self, **args))` (`agent.py:266`) — the calling agent first, then the model's arguments as keywords;
  `str()` because message content must be text.
- `except Exception as e: args, result = call.function.arguments, "error: " + str(e)` (`agent.py:267-268`) — errors go back as
  ordinary text; `args` reverts to the raw string, since nothing was parsed.
- `if len(result) > RESULT_TO_FILE and name not in WHOLE_RESULTS: result = preview(self.save_result(name, result),
  result)` (`agent.py:269-270`) — long results go to `results/`, the context keeps the preview.
- `results[call.id] = (args, result)` (`agent.py:271`) — the pair goes back through the shared dict; item assignment is atomic in
  CPython, so several threads can write different keys without a lock.

**Gotcha** — `269-270` sits **outside** the `try`: if `save_result` raises (disk full, permissions), the exception escapes
the thread, `results[call.id]` is never set, and `run_tools` fails on it with a `KeyError`. Rare, but it is the one
unprotected path.

## `save_result` (`agent.py:273-281`)

**Why** — a long tool result must be readable in full later (`read_result`) under a name never reused.
`with self.lock: self.results += 1; path = "results/" + str(self.results).zfill(6) + "-" + name + ".txt"`
(`agent.py:275-277`) — the lock covers counter *and* name, or parallel calls would collide; `zfill(6)` keeps names in
creation order up to 999,999. Then `os.makedirs(os.path.join(self.folder, "results"), exist_ok=True)` (`agent.py:278`),
`open(..., "w")` and `f.write(text)` (`agent.py:279-280`) — `"w"` is safe because the number is fresh — and
`return path` (`agent.py:281`), relative, exactly what the agent and `read_result` use.

**Example** — the 42nd result of a `sandbox_shell` call lands in `<folder>/results/000042-sandbox_shell.txt`, and the model
sees `[result: results/000042-sandbox_shell.txt, …]`.

**Gotcha** — the lock is released before the write, so two threads may write two files at once while the numbering stays
strict.

## `shows` (`agent.py:283-287`)

**Why** — two audiences: a transcript should contain everything (you may read it later to find out what really happened),
your terminal follows the `PRINT_*` settings. `talk = call.function.name in ("delegate", "tell")` (`agent.py:285-286`) — a message
to a subagent is *their* conversation. `return self.log or (PRINT_TOOLS and (PRINT_SUBAGENT_TALK or not talk))` (`agent.py:287`) —
true for any agent writing a transcript; for the terminal only if tools are printed and either subagent talk is on or this
is not a `delegate`/`tell` call.

**Example** — main agent with defaults (`PRINT_TOOLS=True`, `PRINT_SUBAGENT_TALK=False`): a `calculate` call is shown, a
`delegate` call hidden. The `[worker-1 started -> …]` / `[… reported DONE]` lines still appear: they are written with `say`
directly and never pass through `shows` (`agent.py:494`, `agent.py:519`).

**Gotcha** — the return is truthy-or-falsy, not `True`/`False`; with a `log` it returns the file object.

## `run_tools` (`agent.py:289-304`)

**Why** — one reply can ask for several tools at once, and that is the point: three subagents or three shell commands at
the same time.

- `results = {}` (`agent.py:290`) — `call id → (arguments, result)`, filled by the threads; `threads = []`
  (`agent.py:291`).
- First pass (`agent.py:292-297`): for each `call`, print `"\nTOOL CALL:\n<name>(<arguments>)"` if `shows(call)`, then
  `threading.Thread(target=self.run_tool, args=(call, results))`, `start()`, keep the thread. The starting line is printed
  *before* the thread runs, so the terminal shows all calls first, then their results.
- `for thread in threads: thread.join()` (`agent.py:298-299`) — wait for all.
- Second pass (`agent.py:300-304`): for each `call` **in the order the model asked**, `args, result = results[call.id]`,
  print `"\nTOOL RESULT:\n<name> -> <result>"` if `shows(call)`, then `self.add({"role": "tool", "tool_call_id": call.id,
  "name": call.function.name, "content": result})` — the tool message must carry the id of the call it answers, and the
  name, so the model can match result to request.

**Example** — one reply with two calls leaves `self.messages` like this (system message as `…`):

```python
[{"role": "system", "content": "…"},
 {"role": "user", "content": "get 2*3 and ask a worker to list the files"},
 {"role": "assistant", "tool_calls": [
     {"id": "call_1", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"2*3\"}"}},
     {"id": "call_2", "type": "function", "function": {"name": "delegate", "arguments": "{\"task\": \"list files\"}"}}]},
 {"role": "tool", "tool_call_id": "call_1", "name": "calculate", "content": "6"},
 {"role": "tool", "tool_call_id": "call_2", "name": "delegate",
  "content": "[worker-1, its files: agents/20261007-14-05-09-worker-1/] DONE: three files: a.py, b.py, c.py"}]
```

**Gotchas** — results enter the list in the order the model asked, not the order they finished. Threads are plain
(`daemon` is not set), so a tool that never returns keeps the process alive; the sandbox tool handles its own
`MAX_TOOL_TIMEOUT`, but nothing in `agent.py` forces it.

## `ask` (`agent.py:307-340`) — the loop

**Why** — this is the agent: one question in, one answer out, any number of tool rounds in between, with the context kept
small enough to keep going.

- `with self.busy:` (`agent.py:308`) — one question at a time per agent. `question = {"role": "user", "content": text}`;
  `self.add(question)` (`agent.py:309-310`) — the question joins list and log first. `if self.log: self.say("\nFROM
  PARENT:\n" + text)` (`agent.py:311-312`) — a subagent marks its parent's message in its transcript.
- `while True:` (`agent.py:315`): `self.make_room()` (`agent.py:316`) first, because the context may have grown past the
  emergency mark during the last tool round.
- `litellm.completion(...)` (`agent.py:317-325`) with `api_key=API_KEY` (from `.env` via `config.py:126`, never from the
  environment), `model=MODEL`, `messages=self.messages`, `tools=self.tools or None` (`None` = no tools), `stream=STREAM`,
  `reasoning_effort=EFFORT`, and `cache_control_injection_points=[{"location": "message", "index": -1}]` — a cache bookmark
  on the last message, so the provider can reuse the conversation prefix and you pay less for the repeat.
- `reply = self.show(response)` (`agent.py:326`); `self.add(reply.model_dump(exclude_none=True))` (`agent.py:327`) — the
  whole reply: text, thinking, tool calls. `exclude_none=True` drops empty fields, so a reply with no text has no
  `"content"` key (why `last_tasks` uses `m.get("content")`).
- `if not reply.tool_calls: break` (`agent.py:329-330`) — final answer; otherwise `self.run_tools(reply)`
  (`agent.py:331`) and loop, so the next request sees the results. Then `self.maybe_checkpoint()` (`agent.py:332`) and
  `return reply.content or ""` (`agent.py:333`).
- `except Exception:` (`agent.py:334-338`) — the model or connection failed. `if self.messages[-1] is question` is an
  **identity** check: if nothing was added after the question, no work happened, so pop it and `record("question taken
  back", …)`, then `raise` so `main.py:216` prints the error and a parent gets it as a tool error.
- `finally: self.close_children(keep_waiting=True)` (`agent.py:339-340`) — the task is over (or failed), so its subagents
  are over too, except those waiting for an answer to a `QUESTION`.

**Example** — three rounds: request 1 calls `calculate`, request 2 calls `delegate`, request 3 is plain text → `break`,
`maybe_checkpoint()`, return the text. The list grew by 1 question, 2 assistant replies, 2 tool results.

**Gotcha** — if a tool already ran, `messages[-1]` is a tool result, so the question stays and the partial work is kept
(`main.py:217`). `reply.content or ""` means an answer that was pure thinking comes back empty.

## `tokens` (`agent.py:343-344`)

**Why** — the checkpoints need a size signal and only the order of magnitude matters. One line:
`return litellm.token_counter(model=MODEL, messages=self.messages)` (`agent.py:344`).

**Gotcha** — it counts messages only, not the tool schemas or templates menu that also go into the request, and litellm's
counter is an estimate for non-OpenAI models. `CONTEXT_LIMIT` is a budget, not a guarantee.

## `maybe_checkpoint` (`agent.py:346-358`)

**Why** — the cheap, quiet moment to shrink: a task just ended, nothing is in flight, the model can afford one extra call
to write notes. `if self.depth > 1: return` (`agent.py:350-351`) — main agent only; a subagent's whole life is one task, so
the emergency path covers it (comment at `agent.py:348-349`). `before = self.tokens()`; `if before < CHECKPOINT_AT *
CONTEXT_LIMIT: return` (`agent.py:352-354`) — 60% by default (`config.py:25`). `if not
self.write_checkpoint(False): return` (`agent.py:355-356`) — a failed checkpoint keeps everything and tries again after
the next task. `self.clear(self.last_tasks())` and a line saying `[checkpoint written, context cleared: X -> Y tokens]`
(`agent.py:357-358`).

**Gotcha** — called only from `ask` (`agent.py:332`), i.e. after a task the agent finished; if you never send a message,
no checkpoint is ever written.

## `make_room` (`agent.py:360-379`)

**Why** — one task can outgrow the context in the middle (a long `sandbox_shell` loop, a big read), so this runs before
every model request, not just after a task.

- `limit = EMERGENCY_AT * CONTEXT_LIMIT`; `before = self.tokens()`; `if before < limit: return` (`agent.py:363-366`) — 80% by
  default.
- `moved = self.move_old_results()` (`agent.py:367`) — the cheap step first: old tool results become pointers to their files; if
  anything moved, `record("results moved to files", count=moved)` and a line with the token change (`agent.py:368-371`).
- `if self.tokens() < limit: return` (`agent.py:372-373`) — that was enough, no checkpoint needed.
- `task = self.last_tasks(1)[0]` (`agent.py:374`) — the question of the task it is in the middle of; `if not
  self.write_checkpoint(True): return` (`agent.py:375-376`) — checkpoint failed, go on anyway and risk a model call failing for size.
- `self.clear([{"role": "user", "content": task["content"] + GO_ON}])` (`agent.py:377`) — the new context is the system prompt (with
  the fresh checkpoint) plus the current question with `GO_ON`; everything else is dropped.

**Gotcha** — `move_old_results` runs first on purpose: it costs a file write and often removes the need for a checkpoint,
which costs a model call *and* throws context away. The emergency path ignores `KEEP_TASKS`: it keeps exactly one question.

## `write_checkpoint` (`agent.py:381-400`)

**Why** — turn "what is in the context" into a small text file that can be put back into the system prompt.

- `self.say("\n[writing checkpoint...]")` (`agent.py:384`); `request = CHECKPOINT_PROMPT + (EMERGENCY_NOTE if emergency
  else "")` (`agent.py:385`).
- `litellm.completion(...)` (`agent.py:387-390`) with `messages=self.messages + [{"role": "user", "content": request}]` —
  appended **only for this call**, so `self.messages` is not polluted and the model sees the whole conversation plus its
  old checkpoint (from the system prompt). `tools=self.tools or None` because some models need the tools listed when the
  history holds tool calls; `tool_choice="none" if self.tools else None` so none may be called.
- `text = response.choices[0].message.content` (`agent.py:391`) — not streamed, arrives at once. `except Exception as e:
  self.say("[checkpoint failed: …]"); return False` (`agent.py:392-394`) reports instead of raising; `if not text or not
  text.strip(): return False` (`agent.py:395-397`) catches models that answer an empty string when told not to use tools.
- `write_text(os.path.join(self.folder, "checkpoint.md"), text)` (`agent.py:398`) replaces the file (`write_text` strips and
  adds one newline, `config.py:80-83`); `self.record("checkpoint", content=text, emergency=emergency)` (`agent.py:399`);
  `return True` (`agent.py:400`). The *request* is never logged, only the result.

**Example** — the model gets `self.messages` plus one user message starting `CHECKPOINT. Your context is getting full and
will be cleared right after this message. Write your checkpoint now: …`, and answers with the text that becomes
`checkpoint.md`:

```
## Goal
Make the test suite pass on python 3.9.
## Decisions
Use the sandbox project `py39`, the host python is 3.12.
## Facts
- test_api.py:41 raises TypeError: `docker.py` returns a dict, the test expects a list (results/000017-sandbox_shell.txt).
## Open
- fix `docker.py`, rerun the suite. next: edit docker.py:88
## Files
- results/000017-sandbox_shell.txt
```

## `clear` (`agent.py:402-407`)

**Why** — swap the whole context for a new one built from the fresh system prompt plus a few kept messages.
`self.messages = [{"role": "system", "content": self.build_system()}]` (`agent.py:404`) replaces the list;
`self.record("context cleared", kept_messages=len(kept))` (`agent.py:405`); then `for message in kept: self.add(message)`
(`agent.py:406-407`) re-adds them, so each also lands in the log.

**Gotcha** — kept messages are logged a *second* time (they were logged when first added), so the log looks duplicated
around a clear. Deliberate: the log records events, and "this message is back in the context" is an event. And because
message 0 is new while `logged_system` is old, the first `add` writes a fresh `system` line.

## `last_tasks` (`agent.py:409-431`)

**Why** — after a checkpoint you want the most recent task word for word (it is what the user waits on), not the whole
history.

- `if count is None: count = KEEP_TASKS` (`agent.py:412-413`) — default 1 (`config.py:29`).
- The loop collects `position` for every message with `m["role"] == "user"` (`agent.py:414-419`), because every user message starts
  a task; `if count <= 0 or not starts: return []` (`agent.py:420-421`); `kept = self.messages[starts[-min(count, len(starts))]:]`
  (`agent.py:422`) — from the start of the n-th newest task to the end.
- `if litellm.token_counter(model=MODEL, messages=kept) < 0.2 * CONTEXT_LIMIT: return kept` (`agent.py:423-424`) — small enough.
- Otherwise `short` (`agent.py:425-431`): keep `user` messages and `assistant` messages that have no `tool_calls` and have content,
  re-wrapped as `{"role": "assistant", "content": …}`; tool messages and assistant tool-call messages are dropped.

**Gotcha** — the shortened history can look odd (a question, then an answer with no visible work) but it is legal to send:
no orphan tool messages, which the API would reject.

## `move_old_results` (`agent.py:433-449`)

**Why** — the cheapest way to shrink a context: tool results are usually the bulk, they are on disk or easy to put there,
and the model can read them back with `read_result`.

- `if m["role"] == "tool" and not m["content"].startswith(MOVED): tool_messages.append(m)` (`agent.py:436-439`) — only tool
  messages, only those not already pointers.
- `older = tool_messages`; `if KEEP_RESULTS: older = tool_messages[:-KEEP_RESULTS]` (`agent.py:440-442`) — the newest 3 (default)
  stay as they are; the model is probably still using them.
- `found = re.match(r"\[result: (results/[^,]+),", m["content"])` (`agent.py:445`) — if the content is already a preview, the file
  exists, so reuse that path instead of writing a duplicate; otherwise `path = self.save_result(m["name"], m["content"])`
  (`agent.py:446`).
- `m["content"] = MOVED + path + ", " + format(len(m["content"]), ",") + " characters here before. read_result shows it]"`
  (`agent.py:447`) rewrites the message in place; `return moved` (`agent.py:448-449`).

**Example** — a tool message holding a preview becomes: `[moved out of your context to make room:
results/000042-sandbox_shell.txt, 8,157 characters here before. read_result shows it]`

**Gotcha** — that "8,157 characters" is `len(m["content"])` at that moment, i.e. the size of the *preview*, not of the
original result, so it understates the real content. Cosmetic; nothing parses it.

## `delegate` (`agent.py:452-497`)

**Why** — create a subagent from a template or one-off instructions, give it one task, wait for its report, keep it alive
if it asked something back. Parallelism comes from outside: `run_tools` runs each call in its own thread, so two
`delegate` calls in one reply run two subagents at once.

- `if self.depth >= MAX_DEPTH: return "not allowed: … do the task yourself"` (`agent.py:453-454`) — defence in depth: such
  an agent did not even get the tool (`agent.py:150`), but the model could still name it.
- Template branch (`agent.py:456-462`): `blueprint = templates().get(template)`, unknown → a message listing the available
  ones; then `tools = tools or blueprint["tools"]`, `skills = skills or blueprint["skills"]` — the parent may override, and
  an empty list does **not** override (it is falsy). One-off branch (`agent.py:463-467`): no instructions → `"give a
  template, or instructions for a one-off subagent"`; otherwise `tools = tools or DEFAULT_SUBAGENT_TOOLS`
  (`config.py:43`), `skills = skills or []`.
- Tool check (`agent.py:469-475`): `if tool in MAIN_ONLY_TOOLS: continue` — silently dropped (sandbox control, memory, skill
  editing belong to the parent); an unknown tool returns a message listing every real tool. Skill check
  (`agent.py:476-478`): every requested skill must exist in `SKILLS`.
- `with self.lock:` (`agent.py:480`) — the id and slot section. `if len(self.children) >= MAX_CHILDREN: return "not allowed:
  you already have N subagents. wait for them or ask them more with tell"` (`agent.py:481-482`).
- `self.spawned += 1`; `id = (template or "sub") + "-" + str(self.spawned)` (`agent.py:483-484`) — `worker-1`, `sub-1`;
  `name = self.name + "." + id` (`agent.py:485`) — `main.worker-1`, unique in the tree. `folder = os.path.join(agents,
  free_name(agents, timestamp() + "-" + id, ""))` (`agent.py:486-487`) — `agents/20261007-14-05-09-worker-1`, `-2` if two
  are made in the same second; `os.makedirs(folder)` (`agent.py:488`).
- `log = open(.../transcript.md, "w")` (`agent.py:489`) — stays open for its life and becomes its `self.log`.
  `child = Agent(name, instructions, allowed, skills, folder, depth=self.depth + 1, log=log)` (`agent.py:490`) — `memory` is
  not passed, so it defaults to `False`: subagents never get `MEMORY.md`. `log.write("# " + name + "\ntools: …\nskills:
  …")` (`agent.py:491`) starts the transcript with what it *really* got; `self.children[id] = child` (`agent.py:492`)
  registers it before it runs, so `close_children` finds it even if `ask` failed.
- Outside the lock: `self.say("\n[" + name + " started -> …transcript.md]")` (`agent.py:494`), always shown;
  `report = child.ask(task)` (`agent.py:495`) blocks until that turn is over; `child.waiting = self.report_status(name,
  report) == "QUESTION"` (`agent.py:496`) — only a question keeps it alive; `return self.report_head(id, child) + report`
  (`agent.py:497`).

**Example** — `delegate(task="list the files in /workspace", template="worker")` returns `[worker-1, its files:
agents/20261007-14-05-09-worker-1/] DONE: three files: a.py, b.py, c.py`, and the child sits in `self.children["worker-1"]`,
alive but not waiting.

**Gotchas** — the child is registered *before* `child.ask`, so if the model call fails inside `ask`, the exception
propagates out of `delegate`, `run_tool` turns it into `"error: …"` for the parent model, and the child stays in
`self.children` with an open transcript until `close_children`. `MAX_CHILDREN` counts live children, including ones that
already reported `DONE` and are only alive for a possible follow-up.

## `tell` (`agent.py:499-506`)

**Why** — a subagent that asked a `QUESTION` is still alive with its whole context; answering must continue that
conversation. `child = self.children.get(id)`; not found → `"no live subagent called '<id>'. live: …"` (`agent.py:500-502`).
`self.say("\n[" + child.name + " continues]")` (`agent.py:503`). `report = child.ask(message)` (`agent.py:504`) — same
object, same `self.messages`, so it carries on where it stopped. `child.waiting = self.report_status(child.name, report) ==
"QUESTION"` (`agent.py:505`) — asks again, stays alive again; otherwise it ends at the next `close_children`. Returns
`self.report_head(id, child) + report` (`agent.py:506`).

**Gotcha** — `waiting` is judged on the *new* report only. A subagent that reported `DONE`, got a follow-up and answered
with plain text not starting with a status word becomes not-waiting and is closed after the parent's current task, even
though `report_status` calls that "replied".

## `report_head` (`agent.py:508-510`)

**Why** — the parent model needs two things it cannot guess: the id for `tell`, and where the subagent's files are
relative to its own folder. `return "[" + id + ", its files: " + os.path.relpath(child.folder,
self.folder).replace(os.sep, "/") + "/] "` (`agent.py:510`) — relative, so one prefix works at any depth; forward slashes,
so paths look the same on any OS. **Example** — `[worker-1, its files: agents/20261007-14-05-09-worker-1/]`.

## `report_status` (`agent.py:512-522`)

**Why** — one terminal line per report, plus a yes/no answer to "does this subagent stay alive?".
`first = report.strip().split(None, 1)[0] if report.strip() else ""` (`agent.py:514`) takes the first word;
`status = first.strip("*:#").upper()` (`agent.py:515`) turns `**DONE:**` into `DONE`. Then `QUESTION` → `"[<name> asks a
question, waiting for an answer]"` (`agent.py:516-517`); `DONE`/`BLOCKED` → `"[<name> reported DONE]"` (`agent.py:518-519`);
anything else → `"[<name> replied]"`, with the comment "the model ignored the report format" (`agent.py:520-521`).
`return status` (`agent.py:522`).

**Gotcha** — only exactly `QUESTION` changes behaviour: a report starting "I need to know …" counts as finished. The word
comes from the model's final text, so an empty final message gives `""` → "replied".

## `close_children` (`agent.py:524-532`)

**Why** — subagents hold open transcript files and a big context; when the parent's task ends they should end too, except
the ones a human may still want to answer. `for id in list(self.children):` (`agent.py:527`) iterates a copy of the keys,
because the dict changes inside the loop. `if keep_waiting and self.children[id].waiting: continue` (`agent.py:528-529`)
lets waiting children survive. `child = self.children.pop(id)`; `child.close()`; `self.say("\n[" + child.name + "
closed]")` (`agent.py:530-532`) — popped before closing, so a failing `close` would leave it out of the dict rather than
half-closed (whether that is intended is unclear from the code; `close` does not raise in normal use).

**Example** — after `main` finishes a message, `children` is empty again unless a subagent asked a question; those stay,
with open transcripts, until you answer with `tell` or the conversation ends (`main.py:223`).

## `close` (`agent.py:534-539`)

**Why** — the tidy shutdown of one agent and its whole subtree. `self.close_children()` (`agent.py:535`) first, with no
`keep_waiting`, so everything below dies. Then `if self.log: self.log.write("\n[done]\n"); self.log.close(); self.log =
None` (`agent.py:536-539`) — the transcript ends with a marker and the handle closes; `self.log = None` means a later `say`
prints to the terminal instead of raising on a closed file.

**Gotcha** — `close` does not clear `self.messages` and does not mark the agent dead, so `ask` after `close` on a subagent
would still run and print to your terminal. `main.py` calls it on `/exit` and on `/open` (`main.py:189`, `main.py:223`).

---

## What this chapter hands to the rest of the guide

- **The conversation** is `self.messages`: dicts, `{"role": "system"}` at index 0 (`agent.py:156`), `user` messages
  (`agent.py:309`), assistant replies as `reply.model_dump(exclude_none=True)` (`agent.py:327`), tool results as
  `{"role": "tool", "tool_call_id", "name", "content"}` (`agent.py:304`).
- **A tool in the model's format** is `{"type": "function", "function": {"name", "description", "parameters"}}`
  (`agent.py:47`); the runnable half is `FUNCTIONS[name]` (`agent.py:48`), called as `(agent, **arguments)`
  (`agent.py:266`).
- **A reply** is a litellm message object with `.content`, maybe `.reasoning_content`, and `.tool_calls`; each call has
  `.id`, `.function.name`, `.function.arguments` (a JSON **string**) — `agent.py:257`, `agent.py:261-266`,
  `agent.py:300-304`.
- **A tool result in flight** is `results[call.id] = (args, result)` (`agent.py:271`), a dict shared by the threads
  `run_tools` starts (`agent.py:295`).
- **Long results** live in `<folder>/results/NNNNNN-<tool>.txt` (`agent.py:277`), counted from `highest_result`
  (`agent.py:134`); the model sees the `preview` header instead (`agent.py:104-108`). A **moved result** is a tool message
  rewritten to start with `MOVED` (`agent.py:96`, `agent.py:447`), and `read_result` reads those same `results/…` paths.
- **`self.children`** is `id → Agent` (`agent.py:135`); `id` is `"<template|sub>-<n>"` (`agent.py:484`), `name` is
  `parent.name + "." + id` (`agent.py:485`), the folder is `agents/<timestamp>-<id>` (`agent.py:487`), and `waiting`
  (`agent.py:136`, set at `agent.py:496`) decides whether it survives its parent's task.
- **The log** is `log.jsonl`, one JSON object per line with `time` and `kind` (`agent.py:203`), appended only
  (`agent.py:206`); kinds here: `system`, `message`, `checkpoint`, `context cleared`, `results moved to files`, `question
  taken back`.
- **The checkpoint** is `<folder>/checkpoint.md` (`agent.py:398`), rebuilt into the system prompt at `agent.py:186-189`,
  asked for with `CHECKPOINT_PROMPT` (`agent.py:68`) in the sections Goal / Decisions / Facts / Done / Open / Files /
  Questions.
- **The prompt** is built in one function, seven parts in a fixed order (`agent.py:159-190`): instructions,
  SUBAGENT_RULES, skills menu, templates menu, memory, AUTO_MODE, checkpoint.
- **Names other chapters need**: `TOOLS_DIR`, `SKILLS` / `load_skills()`, `templates()`, `MEMORY_FILE`,
  `CONVERSATIONS_DIR`, `read_text` / `write_text` / `free_name` / `timestamp` — all from `config.py`, reached through
  `from config import *` (`agent.py:22`).
