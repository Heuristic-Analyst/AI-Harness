# 08 — The interconnected picture: every shape, who writes it, who reads it

Chapters 03–07 describe each file on its own. This one is about the **joints**: the handful of data shapes that travel between the parts, the identifiers that tie a result to a request, and the paths by which one subsystem's output becomes another one's input.

If you understand this chapter, you understand the program, because the program is mostly plumbing between about eight dictionaries.

Marking of examples:

- **real** = actually produced by running the repository's own code (with the model client replaced by a stub). The stub only replaces `litellm`, so `agent.py`, `config.py` and all 31 tools are the real ones.
- **reconstructed** = built by reading the code, for things that need a model or podman to actually happen.

---

## 8.1 The eight shapes

Everything that moves through the system is one of these.

### Shape 1 — the message (`agent.py:156`, `:209`, `:304`, `:327`)

The list `agent.messages`. Four roles, and only four:

| role | keys | who writes it | the model sees it as |
|---|---|---|---|
| `system` | `content` | `build_system()` at construction, `refresh_system()` before each turn | standing instructions |
| `user` | `content` | `ask()` — your text, a parent's task, or the checkpoint request | something it must answer |
| `assistant` | `content`, `reasoning_content`, `tool_calls` | `add(reply.model_dump(exclude_none=True))` | what it said last time |
| `tool` | `tool_call_id`, `name`, `content` | `run_tools()` | the answer to something it asked for |

A **real** tool message, produced by running the loop with the real `calculate` tool:

```json
{
  "role": "tool",
  "tool_call_id": "call_1",
  "name": "calculate",
  "content": "397.8"
}
```

Three rules hide in those four lines:

1. `content` is **always a string**. No tool returns a dict; `run_tool` does `str(...)` (`agent.py:266`). A tool that wants to return structure returns JSON *as text*.
2. `tool_call_id` is the only link back to the request. The model sent `call_1`; this message says "here is `call_1`'s answer". Get it wrong and the provider rejects the whole list.
3. `name` is repeated, although it is redundant with the id — for humans reading `log.jsonl`.

An **assistant** message is the whole reply object dumped, not just the text: `reply.model_dump(exclude_none=True)` keeps `content`, `reasoning_content` (the thinking) and `tool_calls` in the provider's own nested form, with `arguments` still a **JSON string** (not a dict). It is stored exactly as received so it can be sent back exactly as received.

### Shape 2 — the tool schema (`agent.py:47`)

What the model gets in the `tools=` argument:

```python
{"type": "function",
 "function": {"name": "calculate",
              "description": "Evaluate a math expression, e.g. 2 * (3 + 4).",
              "parameters": {"type": "object",
                             "properties": {"expression": {"type": "string", "description": "…"}},
                             "required": ["expression"]}}}
```

This dict is built once, at import, out of each tool file's `TOOL`. The `description` is not documentation for you — it is *prompt text* that decides when the model calls the tool. That is why the tool descriptions in this repo are written as instructions ("Use when …", "sets the metadata in the module docstring").

### Shape 3 — the request for a tool call (in the reply)

```
reply.tool_calls[0].id                        "call_1"
reply.tool_calls[0].function.name             "calculate"
reply.tool_calls[0].function.arguments        '{"expression": "0.17*2340"}'   ← a string, needs json.loads
```

`arguments` being a string is a frequent source of bugs in home-made harnesses. Here it is parsed in exactly one place, `agent.py:263`.

### Shape 4 — the in-flight results dict (`agent.py:271`, `:295`)

Because tool calls run in parallel threads, `run_tools` passes one shared dict to every thread:

```python
results[call.id] = (args, text)      # written by run_tool
args, result = results[call.id]      # read afterwards, in the order the model asked
```

The id is the key precisely because thread completion order is arbitrary and the message order must not be.

### Shape 5 — the tool's answer text

Conventions the model learns from the descriptions and from experience:

| Situation | Text |
|---|---|
| success | plain text, e.g. `397.8`, `opened analysis.ipynb …` |
| too long (>8000 chars) | a preview (`Shape 6`) |
| refused | a sentence starting with the reason: `not saved: …`, `not allowed: …`, `unknown tool 'x'. available: …` |
| inside the tool, an exception | `error: ValueError: …` (caught in `run_tool`, `agent.py:267`) |
| a command in the container | the command's output, ending with nothing if it worked; a non-zero exit code is reported as `(exit code N)` |

### Shape 6 — the preview (`agent.py:99-109`)

**Real** output, from the real `preview()` on a 28,291-character, 400-line result:

```
[result: results/000042-sandbox_shell.txt, 28,291 characters, 400 lines. this is only the start and the end: read_result and search_result show the rest]
line 1: xxxx…
…
line 40: xxxx…
...
line 381: xxxx…
…
line 400: xxxx…
```

Rules: first 40 lines (max 3,000 chars), last 20 lines (max 1,500 chars), and a header that says where the whole thing is. The path is **relative to the conversation folder**, which is why `read_result("results/000042-sandbox_shell.txt")` works from the model's point of view without ever mentioning an absolute path.

### Shape 7 — the pointer (`agent.py:96`, `:447`)

When space runs out, an old tool message is not deleted, it is **replaced by a sentence with its file in it**. **Real** output after `move_old_results()` on five tool messages with `KEEP_RESULTS = 3`:

```
'[moved out of your context to make room: results/000001-calculate.txt, 1 characters here before. read_result shows it]'
'[moved out of your context to make room: results/000002-calculate.txt, 1 characters here before. read_result shows it]'
'9'
'16'
'25'
```

Two things to notice: the newest three stay verbatim, and `1 characters` is the length of the *preview that was there*, not of the original result — the number is cosmetic and nothing parses it. (Quirk, see 8.6.)

### Shape 8 — the notebook command / answer (`tools/notebook/_notebook.py:50`)

Host → container, one dict per `nb_*` call, base64-encoded onto a command line:

```json
{"cmd": "run", "notebook": "analysis.ipynb", "cells": ["3f9a1c0b"], "timeout": 570}
```

Container → host, one string: the human-readable answer, plus the overview of the notebook. The kernel never answers with a dict; the dicts travel *towards* the kernel. (Details and the full command table: chapter 07.)

---

## 8.2 The identifiers that tie shapes together

| Identifier | Form | Made by | Used by |
|---|---|---|---|
| `tool_call_id` | `call_1` (provider's) | the model | the `tool` message, the `results` dict |
| agent name | `main`, `main.worker-1`, `main.worker-1.coder-2` | `delegate` (`agent.py:487`) | terminal output, transcripts, reports |
| child id | `worker-1`, `coder-2` | `delegate` (`:486`) | `children` dict, `tell(id, …)`, `[worker-1 continues]` |
| agent folder | `Conversations/x/agents/20261019-221747-worker-1/` | `timestamp()` + `free_name` | the child's log, checkpoint, results, its own `agents/` |
| result file | `results/000042-sandbox_shell.txt` | `save_result` (`:277`) | previews, `read_result`, `copy_result`, `move_old_results` |
| result counter | highest existing number, +1 | `highest_result` (`:111`) | never reuses a name, also after `/open` |
| conversation | folder name, e.g. `harness-guide` | you, `/new`, `/rename` | `state.json`, lock name `conversation-<name>` |
| instance | `48213-20261018165603` | `config.py:71` | container labels, `instance-<id>.lock`, "is that other instance still alive?" |
| container | `sandbox-<sandbox>-<instance>-<n>` | `sandbox.py:151` | podman, `/sandbox`, cleanup |
| notebook lock | `notebook-<md5 of path>` | `_notebook.py:37` | `Locks/` on the host; a second `flock` in `/tmp` inside |
| skill identity | folder name = skill name | `SKILLS` dict | `load_skill`, `[editable]` flag, `skills_seen` |

The pattern to appreciate: **every identifier is a human-readable string, and it appears in a file name or a folder name.** There is no database assigning ids, so you can always go from a message in the log to a file on disk by eye.

---

## 8.3 One turn, end to end (with real intermediate values)

You type `what is 17% of 2340?` in a conversation. Here is every step, with the shapes that pass between them.

1. `main.py` calls `agent.ask("what is 17% of 2340?")` (`main.py:214`).
2. `ask` takes `self.busy` (a second question would wait), builds `{"role": "user", "content": …}`, calls `add()` — which first logs the system prompt **if it changed**, then appends the message and logs it (`agent.py:209`). The log line is real:

```json
{"time": "2026-10-19T20:32:24", "kind": "message", "message": {"role": "tool", "tool_call_id": "call_1", "name": "calculate", "content": "397.8"}}
```

3. `make_room()`: token estimate below 80% of the limit → returns immediately (`agent.py:360`).
4. `litellm.completion(messages=self.messages, tools=self.tools, …)` — the whole list, every time (`agent.py:318`).
5. `show(response)` prints the streamed reply (`THINKING`/`ANSWER` blocks) and returns the finished message (`agent.py:243`).
6. `add(reply.model_dump(exclude_none=True))` — now the list has an `assistant` message whose `tool_calls` is `[{id: "call_1", function: {name: "calculate", arguments: '{"expression": "2340*0.17"}'}}]`.
7. `run_tools(reply)`: prints `TOOL CALL: calculate({"expression": "2340*0.17"})`, starts one thread per call, each running `run_tool` (`agent.py:289`).
8. `run_tool`: `json.loads(arguments)` → `FUNCTIONS["calculate"](self, expression="2340*0.17")` → `str(397.8)`; on an exception the text becomes `error: …` (`agent.py:260`). The result is short, so it stays as it is.
9. Back in `run_tools`: `results[call.id]` is read **in the model's order**, the `tool` message is added, and the loop repeats from step 4.
10. Second pass: the model answers `17% of 2340 is 397.8` with no tool calls → `break`.
11. `maybe_checkpoint()`: below 60% → nothing.
12. `ask` returns the text; `main.py` calls `save_conversation(agent, name)`, which writes `state.json` from `agent.messages`.

The list at the end of such a turn (system message shortened). The `tool` message and its keys are **real**, produced by the real loop; the two assistant messages are what the code stores for a reply like that — there is no model here to produce them:

```json
[{"role": "system", "content": "# Who you are\n\nYou are a personal assistant …"},
 {"role": "user", "content": "what is 17% of 2340?"},
 {"role": "assistant",
  "tool_calls": [{"id": "call_1", "type": "function",
                  "function": {"name": "calculate", "arguments": "{\"expression\": \"2340*0.17\"}"}}]},
 {"role": "tool", "tool_call_id": "call_1", "name": "calculate", "content": "397.8"},
 {"role": "assistant", "content": "17% of 2340 is 397.8"}]
```

(Note the missing `"content"` in the assistant tool-call message: the model sent no text with that request, the value was `None`, and `exclude_none=True` dropped the key.)

That is the entire state of the conversation. Nothing else exists: no hidden variables, no summary, no memory of the tools. If you deleted everything except this list, the model could continue perfectly.

---

## 8.4 How the subsystems interlock

Each subsection is one "intertwining": output of A is input of B.

### 8.4.1 The system prompt is assembled from four files and two globals

`build_system()` (`agent.py:159-190`) concatenates, in this fixed order:

1. `self.instructions` — `Ego/SOUL.md` for the main agent, a template body or one-off text for a subagent;
2. `SUBAGENT_RULES` — only if `depth > 1`;
3. the skills menu — names and descriptions from the global `SKILLS` dict, `[editable]` for those under `Skills/Learned/`;
4. the templates menu — from `templates()`, but only if the agent has the `delegate` tool;
5. `<memory>` — the contents of `Ego/MEMORY.md`, only if `memory=True` (main agent only);
6. `AUTO_MODE` — only if `mode == "auto"`;
7. `<checkpoint>` — the contents of `<its folder>/checkpoint.md`, if that file exists.

So the system prompt is a **view over files**, rebuilt on demand, never edited in place. `refresh_system()` (`:196`) rebuilds it and replaces `messages[0]` before every turn, which is how a skill created in another instance, or a memory edit, or a `/mode auto`, takes effect without restarting.

**Real** system prompt of the main agent, from this very repository (memory section kept, middle shortened):

```
# Who you are

You are a personal assistant running on your user's own computer, in a small agent they built themselves.
…
You have skills: step-by-step instructions for certain kinds of tasks. When a task matches a skill, first call load_skill with its name, then follow what it returns.
Available skills:
- memory: Use when the user asks you to remember, forget or update something, …
- notebook: Use when you work in a Jupyter notebook with the nb_* tools, …
Skills marked [editable] are ones you wrote yourself: …
You can create subagents with delegate: from a template below, or with your own instructions.
Templates:
- coder: Writes, runs and tests code inside the sandbox. …
- worker: Does one clearly defined task with the tools and reports the result. …
Your memory, saved across conversations. To change it, load the memory skill first.
<memory>
# Memory
## User
## Preferences
## Projects
## Notes
</memory>
```

Note what is **not** there: no tool list (tools go in the `tools=` argument, not the prompt), no checkpoint (this agent has none yet), no `AUTO_MODE` (mode is `ask`).

### 8.4.2 The checkpoint: the model writes the file it will read next

```
tokens() ──> above 60 % after a task ──> write_checkpoint()
                                          │  one completion call: messages + CHECKPOINT_PROMPT,
                                          │  tool_choice="none"  (it may not use tools)
                                          ▼
                                    checkpoint.md   (7 fixed sections)
                                          │
clear(kept) ──> messages = [ system(build_system()), …last KEEP_TASKS tasks ]
                                          │
                               next call: the system prompt now CONTAINS <checkpoint>
```

Three interlock points worth seeing:

- `write_checkpoint` appends the request **to the same message list** but does not store it (`agent.py:385`): the "write your notes" instruction never becomes part of the conversation.
- The old checkpoint is still visible to the model while it writes the new one, because it is in the system prompt — the prompt literally says "carry over everything from it that is still true".
- `clear()` **re-logs** the kept messages, so `log.jsonl` has them twice (once before the checkpoint, once after). The log is append-only; that is the price.

In the middle of a task the order is different and cheaper first: `make_room` → `move_old_results` (pointers) → still too full → `write_checkpoint(True)` → `clear([question + GO_ON])`. So an emergency keeps the *question* and a note saying "you were in the middle of this", while a normal checkpoint keeps the last whole task.

### 8.4.3 Long results: one file, four tools, three readers

```
tool returns 30,000 chars
      │  run_tool → save_result(name, text)          agent.py:273
      ▼
results/000042-sandbox_shell.txt        ← the truth, on disk
      │  preview(path, text)                          agent.py:99
      ▼
"tool" message = header + first 40 lines + last 20 lines
      │
      ├── read_result(path, from_line, lines)      paging, ≤200 lines / 6,000 chars per call
      ├── search_result(text, file, regex)         grep, ≤50 hits, returns file + line numbers
      ├── copy_result(file, to)                    copies into /workspace/... so code can open it
      └── move_old_results()                       replaces the preview with a pointer sentence
```

Why four tools and not one: each answers a different question. *What does it say on line 900?* (read). *Where does it mention `KeyError`?* (search). *I want pandas to load it* (copy). *This is too big for my context* (move). And `WHOLE_RESULTS = ["load_skill","read_memory","read_result","search_result"]` (`agent.py:94`) is the exception list: these four results are never written to a file, because they are the tools you use to *read* files — putting their output in a file would need a file to read the file.

### 8.4.4 Memory: three places must agree

```
Ego/MEMORY.md ──read_text──> <memory> in the system prompt      (every turn, refresh_system)
      ▲
      │ write_memory(agent, content)
      │  1. read the file now, compare with agent.memory_seen  ← "did anybody change it since you last looked?"
      │  2. locks.take("memory")                               ← "is another instance writing right now?"
      │  3. write_text, return "saved …"
read_memory(agent) ──> returns the file, and stores it in agent.memory_seen
```

The `memory_seen` check (`agent.py:141`) is a *conflict detector*, not a lock: it catches "you read it, the user edited it, you wrote it back" — a lost update. The lock catches "two instances save at the same time". Two different races, two different mechanisms, both needed.

### 8.4.5 Skills: a menu, a body, and a permission model in the file system

```
Skills/<name>/SKILL.md            → SKILLS[name] = {description, path, editable: False}
Skills/Learned/<name>/SKILL.md    → SKILLS[name] = {…, editable: True}

SKILLS ──> system prompt menu (name + description + "[editable]")
       └──> load_skill(name) ──> the body, plus agent.skills_seen[name] = the text it showed

create_skill / edit_skill / delete_skill
    · only names in Skills/Learned/ are allowed (never the user's)
    · locks.wait_take("skills") around the write
    · edit_skill compares skills_seen[name] with the file on disk first (same lost-update check as memory)
    · afterwards load_skills() re-reads the folder, so the next turn's menu is current
```

`load_skills()` is called at import and again in `main.py`'s loop before every `ask` (`main.py:211`), which is how a skill created by *another* instance appears in your menu without a restart.

### 8.4.6 Subagents: the same class, a different configuration

`delegate` is not a special kind of agent — it is the same `Agent` with different arguments, plus bookkeeping in the parent:

```
delegate(task, template="worker")
  ├── templates()["worker"] → instructions, tools, skills        (Templates/worker.md, front matter)
  ├── filter tools: drop MAIN_ONLY_TOOLS, error on unknown        (agent.py:471-478)
  ├── lock: MAX_CHILDREN alive? id = "worker-1", name = "main.worker-1"
  ├── folder = <parent folder>/agents/<timestamp>-<id>/          (+ free_name if same second)
  ├── open transcript.md  ← the child's log handle, written live
  ├── child = Agent(name, instructions, allowed, skills, folder, depth+1, log=transcript)
  ├── children["worker-1"] = child
  ├── report = child.ask(task)          ← blocks this thread; other delegations run in their own threads
  ├── child.waiting = (report_status(report) == "QUESTION")
  └── return report_head(id, child) + report     ← "[worker-1] DONE: …" prefix so the parent knows whom to tell
```

What flows back up is **text** — the report — not the child's message list. That is the point: 300k tokens of trial and error collapse into 2,000 characters. What flows down is also text — the task string.

`tell(id, message)` reuses the same child object (`children[id]`), calls `child.ask(message)` again, so the child continues with its *full* context. `close_children(keep_waiting=True)` at the end of every task closes every child **except** those whose last report was a `QUESTION`, which is why a waiting child can still be answered in the next turn after its parent's task ended.

### 8.4.7 Sandbox: three globals, podman labels, and the mount list

`sandbox.py` holds, per process: `my_container`, `my_project`, `starts`. Everything else about containers is *discovered* by asking podman, filtered by labels:

```
harness.owner   = INSTANCE      → "is this container mine, alive, or a leftover?"
harness.sandbox = "python"      → which Containerfile it was built from
harness.project = "agent-explainer"  → which project it holds (this is the project "lock")
harness.shared  = "/path/Shared" → two checkouts on one machine don't collide
```

The chain that makes `sandbox_shell` work:

```
open_sandbox(name) → build (podman build) → run (mounts, limits, network off) → my_container set
sandbox_shell(cmd) → workdir() = /workspace/<project> or /workspace/common
                   → podman exec -w <workdir> <container> timeout -k 5 600 bash -c '<cmd>'
                   → output string → tool message (or a result file if long)
mount_project(p)   → stop + start the container with one more -v  → workdir changes
close_sandbox()    → podman stop → my_container = None → notebooks: their kernels die, locks released
```

Every tool that needs the container (shell, notebooks, copy_result) goes through these globals. That is why a subagent "shares the parent's sandbox": it has no sandbox state of its own at all.

### 8.4.8 Notebooks: three layers, one string answer

```
nb_run(cell)                        host, tool file
  └─ _notebook.call(cmd)            host, base64-encodes the dict
      └─ sandbox.exec("python3 -B client.py <b64>")     → inside the container
          └─ client.py              delivers the dict over a socket to the kernel
              └─ kernel.py          Notebook.run_cell → saves the .ipynb, returns text
          ← answer text printed by client.py
      ← stdout of the exec = the tool result string
  ← "tool" message
```

Two consequences people get wrong: the **kernel** is the only thing that lives between cells (so variables survive, shell variables do not), and the **`.ipynb` file** is written by the kernel after every change (so you can open it in Jupyter at any moment). The host never parses the notebook JSON — `kernel.py` owns the format. A second `nb_*` call while the first is still running is prevented by the notebook lock on the host (`Locks/notebook-<md5>.lock`) plus a `flock` on `/tmp/nb-<md5>.lock` inside the container.

### 8.4.9 Conversations: the list on disk

```
agent.messages  ──save_conversation──>  state.json      (what /open reloads: messages, mode, name)
      │
      └── add()/record() ──> log.jsonl   (append-only: system, message, checkpoint, context cleared,
                                          results moved to files, question taken back, …)
                              checkpoint.md  (the model's own notes; part of the next system prompt)
                              results/       (long tool results)
                              agents/        (each subagent: transcript.md, log.jsonl, results/, checkpoint.md)
```

`/open` rebuilds an `Agent` from `state.json`, re-reads `checkpoint.md` into the system prompt via `build_system()`, and continues numbering result files after the highest existing one (`highest_result`). That is why reopening a conversation does not overwrite `000001-…`.

---

## 8.5 Three traces you can follow in the code

### Trace A — a big output, then paging (reconstructed, but every step is one line in the code)

1. The model calls `sandbox_shell({"command": "python analyze.py"})`.
2. `run_tool` → `sandbox.exec(...)` returns 42,000 characters.
3. `save_result("sandbox_shell", text)` → `results/000007-sandbox_shell.txt`; the counter came from `highest_result` at construction, so it cannot clash with an earlier file.
4. The context gets the preview: path, `42,000 characters`, 1,200 lines, first 40 and last 20 lines.
5. The model calls `read_result({"file": "results/000007-sandbox_shell.txt", "from_line": 900, "lines": 60})`. `_results.py` resolves the path **inside the conversation folder only**, so `../../.env` fails, and returns lines 900–959 with line numbers.
6. Later, `make_room` runs at 80%: that tool message turns into `[moved out of your context to make room: results/000007-sandbox_shell.txt, …]`.
7. If the model needs the data *as data*, it calls `copy_result({"file": "results/000007-sandbox_shell.txt", "to": "common/data"})` and then `pandas.read_csv("/workspace/common/data/000007-sandbox_shell.txt")` inside the container.

### Trace B — delegate, QUESTION, tell

1. Main: `delegate({"task": "Find the licence and report it", "template": "worker"})`.
2. `delegate` builds `main.worker-1` in `Conversations/x/agents/20261019-221747-worker-1/`, with `DEFAULT_SUBAGENT_TOOLS` minus the main-only ones (so no sandbox tools — it uses the parent's container through the tools it *did* get, or none at all).
3. Child runs its own loop in its own thread; its `say()` writes to `transcript.md`, not your terminal.
4. Child's last message begins `QUESTION: which of the two licence files do you mean?` → `report_status` returns `"QUESTION"` → `child.waiting = True`.
5. Parent's tool result is `"[worker-1] QUESTION: …"` (text). Parent answers: `tell({"id": "worker-1", "message": "the LICENSE one"})`.
6. `child.ask("the LICENSE one")` — same list, same context, continues.
7. Child ends `DONE: …` → `waiting = False` → next `close_children` closes its transcript and drops it from `children`.

### Trace C — a conversation that outgrows its context

1. Task ends; `tokens()` (a real token count from LiteLLM, not a character guess) is 340,000 of 500,000 → 68% > 60%.
2. `write_checkpoint(False)`: one extra completion call with `CHECKPOINT_PROMPT`, tools listed but `tool_choice="none"`.
3. The model writes the seven sections; `write_text(checkpoint.md)`; `record("checkpoint", …)`.
4. `clear(last_tasks())`: `messages = [system]` + the last task verbatim (or, if even that is >20% of the limit, only its question and final answer).
5. Terminal: `[checkpoint written, context cleared: 340,112 -> 21,905 tokens]`.
6. Next turn: `build_system()` now contains `<checkpoint>…</checkpoint>`, so the model starts with its own notes. The full transcript is still in `log.jsonl`, and every tool result is still in `results/`.

---

## 8.6 Loose ends worth knowing (all real, none fatal)

These are the places where the joints do not line up perfectly. Useful to know before you modify anything.

| Where | What | Why it matters |
|---|---|---|
| `agent.py:269-270` | `save_result`/`preview` sit **outside** the `try` in `run_tool` | a failing write leaves `results[call.id]` unset → `KeyError` in `run_tools` |
| `agent.py:447` | the pointer's "N characters here before" counts the preview, not the result | **verified**: five short results gave `1 characters` |
| `agent.py:218` | `moved()` assumes `old` is a prefix of `self.folder` | a bad rename would silently produce a nonsense path |
| `agent.py:196` | `refresh_system()` rebuilds the prompt but **not** `self.tools` | a tool set is frozen at construction; a subagent made with no skills never gains `load_skill` |
| `agent.py:471` vs `:477` | `tools or blueprint["tools"]` | an empty list cannot override a template's tools |
| `kernel.py` | answers are strings | the host never gets structured notebook data back |
| `preview`/`read_result` | paths start at `results/` | a subagent's file needs `agents/<id>/results/…`, which `move_old_results`'s regex would not recognise |
| `sandbox.py:147` | `build()` runs on every open | correctness over speed: podman's layer cache decides what actually rebuilds |
| `sandbox.py:158-176` | the container is created with `--network podman`, then disconnected | a very short window with a network exists at start-up |
| `config.py:154-155` | `SKILLS.clear()` then `update()` | not atomic despite the comment; readers snapshot with `list(SKILLS)` |
| `locks.py` `free()` | a "probe" that can delete a file | calling it has a side effect |
| `main.py` `new_name()` | takes a lock on every candidate it rejects | leaves unlocked lock files until the next start sweeps them |
| `calculate` | whitelist allows `.` and `**` | `9**9**9**9` is legal input; only the 5-second limit stops it |
| `sandbox.py:493` vs `:224` | `delete_project` refuses symlinks, `projects()` does not | a symlinked folder in `Shared/` is listed and mountable |

---

## 8.7 The cheat sheet: every dict, in one place

| Dict | Keys | Written by | Read by |
|---|---|---|---|
| message | `role` + (`content` \| `tool_call_id`,`name`,`content`) | `add`, `run_tools`, `clear` | LiteLLM, `save_conversation`, `last_tasks`, `move_old_results` |
| tool schema | `type`, `function.name/.description/.parameters` | tool loader | `litellm.completion(tools=…)` |
| `TOOLS` / `FUNCTIONS` | name → schema / name → `run` | tool loader | `agent.tools`, `run_tool`, `delegate` validation |
| `results` (in-flight) | `call.id` → `(args, text)` | `run_tool` threads | `run_tools` |
| `SKILLS` | name → `{description, path, editable}` | `config.load_skills()` | system prompt, `load_skill`, `delegate`, skill tools |
| `skills_seen` | name → the body shown | `load_skill` | `edit_skill` (lost-update check) |
| `memory_seen` | the file text | `read_memory` | `write_memory` (lost-update check) |
| `templates()` | name → `{description, instructions, tools, skills}` | every call | system prompt menu, `delegate` |
| `children` | id → `Agent` | `delegate` | `tell`, `close_children`, `report_status` |
| notebook command | `cmd`, `notebook`, `cells`/`cell`/`source`, `timeout` | `tools/notebook/*` | `client.py`, then `kernel.handle` |
| `state.json` | `mode`, `messages` (the name is the folder name) | `save_conversation` (`main.py:56`) | `/open` |
| log line | `time`, `kind`, + fields | `record` | you, grep |
| podman labels | `harness.owner/.sandbox/.project/.shared` | `sandbox.start` | `containers()`, `cleanup()`, `projects_status` |

If you can name, for any two of those rows, **which one produces the other's input**, you can read the whole codebase without getting lost. That is the interconnected picture.
