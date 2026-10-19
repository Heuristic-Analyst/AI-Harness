# 06 — Tools: the protocol, and the five groups that run the harness

**In this chapter:** (every tool is then explained line by line)
- 6.1 The tool protocol
- 6.2 `tools/basic/` — the two tools everyone gets
    - `calculate` — do arithmetic without trusting the model's mental maths
    - `load_skill` — turn a skill's one-line menu entry into its full instructions
- 6.3 `tools/memory/` — one file, replaced whole
    - `read_memory` — the file as it is right now
    - `write_memory` — replace the whole file, but only if nothing moved
- 6.4 `tools/skills/` — the agent writes instructions for its future self
    - `_skillfile.py` — the shared rules, not a tool
    - `create_skill` — save a new skill
    - `edit_skill` — rewrite one of its own skills, if nothing moved
    - `delete_skill` — remove one of its own skills
- 6.5 `tools/subagents/` — two one-line tools over `agent.py`
    - `delegate` — create a subagent, give it one task, get its report
    - `tell` — one more message to a live subagent
- 6.6 `tools/sandbox/` — the ten tools that own the container and the projects
    - `sandbox_shell` — the only way to run a command
    - `check_sandbox` — read-only look at the sandboxes
    - `open_sandbox` — start the chosen sandbox (optionally with a project)
    - `close_sandbox` — stop it, keep the files
    - `check_projects` — who has which project
    - `create_project` — a new empty folder in `Shared/`
    - `mount_project` — make a project the working folder (restarts)
    - `unmount_project` — give it back (restarts)
    - `rename_project` — rename a folder no sandbox is using
    - `delete_project` — remove a project with everything in it
- What this chapter hands to the rest of the guide

---

Everything the agent can *do* is a tool, and every tool is one Python file (tools/README.md:3). There is no other way in: no function calling through some SDK, no special framework, no
magic. A tool file is a dictionary that describes what the model sees, plus a function that is what actually happens. The harness reads the dictionary, hands it to the model as part of
the request, and when the model asks for a tool it calls the function.

This chapter covers the protocol once, properly, and then the five tool groups that make up the core of the harness: `tools/basic/`, `tools/memory/`, `tools/skills/`,
`tools/subagents/`, `tools/sandbox/`. That is 19 tool files plus one shared helper (`_skillfile.py`). The notebook tools (`tools/notebook/`) and the result-file tools (`tools/results/`)
are their own chapters; they obey exactly the protocol described here.

Two words are used all through the codebase, so define them now:

- **instance** — one running `main.py`. Its id is process number + start time (config.py:71), e.g. `48213-20261018165603`. You can run several at once; they coordinate through lock files
  (locks.py:1-10) and through the labels on their containers.
- **tool result** — the string a tool hands back. It goes into the conversation as a `role: "tool"` message (agent.py:304).

---

## 6.1 The tool protocol

### A tool file is a dict and a function

The model only ever sees `TOOL`. The program only ever calls `run`. Here is `tools/basic/calculate.py`, complete — it is the model for all 31 tools in the repo:

```python
# every tool file has two things: run (what we execute) and TOOL (what the model sees).
# run always gets the calling agent as its first argument, then the arguments the model passed. ignore agent if you don't need it.

import sys
import subprocess

TIMEOUT = 5   # seconds. a safety net for large calculations like 9**9**9**9, not a setting

def run(agent, expression):
    if not set(expression) <= set("0123456789+-*/().% "):        # only digits and math symbols. never let a model run code.
        return "invalid expression"
    try:                                                          # in its own small python process: one that never ends can be killed
        done = subprocess.run([sys.executable, "-I", "-c", "print(eval(input()))"], input=expression + "\n",
                              capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:                             # e.g. 9**9**9**9: the process is stopped
        return "too big: no result after " + str(TIMEOUT) + " seconds"
    if done.returncode != 0:                                      # e.g. 1/0 -> "error: ZeroDivisionError: division by zero"
        lines = done.stderr.strip().splitlines()
        return "error: " + (lines[-1] if lines else "exit code " + str(done.returncode))
    return done.stdout.strip()

TOOL = {
    "name": "calculate",
    "description": "Evaluate a math expression, e.g. 2 * (3 + 4).",
    "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
}
```

Four rules follow from that file, and every other tool follows them:

1. `TOOL["name"]` is the name the model uses, and the name templates list. It is **not** the file name and not the folder: `create_skill` lives in `tools/skills/create_skill.py`, and
   `sandbox_shell` in `tools/sandbox/sandbox_shell.py`. Moving a file breaks nothing as long as `TOOL["name"]` stays the same (tools/README.md:36).
2. `run(agent, ...)` gets the calling agent object first, then exactly the arguments the model passed, as keyword arguments (agent.py:266). A tool that needs nothing from the agent still
   declares `agent` (`calculate.py:9` says so in a comment).
3. `run` returns a **string** — every return in every tool file is a string. See "the shape of a result" below.
4. There is no registration, no decorator, no base class. The dict at module level *is* the registration, because the loader looks for exactly that name.

### Where the dicts come from: discovery at startup

`agent.py` is imported before anything else runs, and its top level does the loading. Mechanically (agent.py:31-49):

- `os.walk(TOOLS_DIR)` walks the whole `tools/` tree, as deep as it goes (agent.py:34). `TOOLS_DIR` is `<repo>/tools` (config.py:60).
- Subfolders starting with `.` or `_` are skipped, and so are files starting with `_` or not ending in `.py` (agent.py:35-37). So `_skillfile.py` and `_results.py` are *helpers*, not
  tools; `__pycache__` is ignored; the READMEs are ignored.
- Each surviving file is imported by its path with `importlib.util.spec_from_file_location(...)` (agent.py:41-43). Its module name is derived from the path (`tools.skills.create_skill`),
  which is why `from . import _skillfile` works inside `tools/skills/create_skill.py:2` — the repo root is on `sys.path` (config.py:9-10) and Python treats the folders as namespace
  packages.
- `name = module.TOOL["name"]` (agent.py:44). Two tools with the same name stop the program at startup with both file paths in the message (agent.py:45-46).
- Then two dicts are filled: `TOOLS[name] = {"type": "function", "function": module.TOOL}` (agent.py:47) — that is litellm's (OpenAI's) wrapper around our dict — and `FUNCTIONS[name] =
  module.run` (agent.py:48). `FOUND_IN` (agent.py:33) remembers the file, only for the duplicate-name error.

So `TOOLS` is "what the model sees" and `FUNCTIONS` is "what gets called", both keyed by the same name, both built once at startup. Adding a tool = adding a file; there is no list to
edit anywhere.

### The JSON schema, field by field

`TOOL["parameters"]` is a JSON Schema object. The model's API requires this format, and the model reads it as text. Take `tools/skills/edit_skill.py:36-41` as the example:

```python
"parameters": {"type": "object",
               "properties": {"name": {"type": "string"},
                              "body": {"type": "string", "description": "the complete new instructions in markdown"},
                              "description": {"type": "string", "description": "a new one-line 'Use when ...'. leave it "
                                              "out to keep the current one"}},
               "required": ["name", "body"]},
```

- `"type": "object"` — the arguments always arrive as one JSON object, i.e. Python keyword arguments. Every tool in this repo uses `object`; there is no other shape.
- `"properties": {...}` — one entry per argument: its name (the keyword `run` will receive) and its type.
- Inside a property, `"type"` is what kind of value is expected: `"string"`, `"integer"`, `"array"`. `"array"` needs `"items"` to say what is in it — `delegate.py:20` has `"tools":
  {"type": "array", "items": {"type": "string"}}`.
- `"description"` on a property is **prompt text**. It is the only place to tell the model the *format* of an argument, and the tools use it hard. Compare `create_skill.py:36-41`: `name`
  → "lowercase letters, digits and hyphens, e.g. clean-csv-files"; `description` → "ONE line that says when to use it, starting with 'Use when ...'. It is all you see of the skill until
  you load it, so it decides whether you ever use it"; `body` → "... no header, the tool writes it". Those sentences are why the model passes `clean-csv-files` and not `Clean CSV Files!`,
  and why it does not paste a `---` header into the body.
- `"required": ["name", "body"]` — arguments the model must supply. Anything not listed is optional and simply absent from `**args`, so the Python function needs a default for it
  (`edit_skill.py:5` has `description=None`; `check_sandbox.py:3` has `name=None`; `open_sandbox.py:3` has `project=None`).
- There is no `"default"` and no `"minimum"` anywhere in this repo, and exactly one `"enum"` (`nb_add`'s `kind`, tools/notebook/nb_add.py:13). The tools do their own validation in
  Python and answer with a sentence (that is the style, see "what an error looks like").
- A tool with no arguments passes `{"type": "object", "properties": {}}` and no `required` (`read_memory.py:10`, `close_sandbox.py:11`).

The top-level `TOOL["description"]` (the one next to `name`) is different: it is the *manual page* for the tool, shown to the model whenever the tool list is sent. `calculate`'s is one
short line because the tool is trivial. The others are long on purpose — they say **when** to call the tool and **what not to do**. `create_skill.py:29-34` is the extreme case: it tells
the model when a skill is worth creating, what is *not* a skill ("Not for facts about the user (that is memory) and not for one-off tasks"), to check the existing list first, and to
tell the user afterwards. Rewording a description is the cheapest behaviour change in the whole codebase; nothing else in the program reads that text.

### What the model sends back, and how `run()` is called

One turn of the agent loop (agent.py:315-331): send `self.messages` plus `tools=self.tools` to the model, store the reply, and if `reply.tool_calls` is empty that was the final answer.
Otherwise:

- Each tool call has a name and `call.function.arguments`, a **JSON string**, e.g. `{"expression": "2 * (3 + 4)"}` (agent.py:294 prints it exactly like that).
- Every call of the reply gets its own thread (agent.py:292-297), so `delegate` calls in one reply really do run at the same time; then the threads are joined and the results are handed
  back **in the order the model asked** (agent.py:300-304).
- In the thread: `args = json.loads(call.function.arguments or "{}")` (agent.py:263) — `or "{}"` covers a call with no arguments at all. A JSON that does not parse raises, and becomes an
  error string (next section).
- `if name not in self.tool_names: raise Exception("you have no tool called ...")` (agent.py:264-265). The model can *name* any tool; it can only *run* one it was given. This matters for
  subagents, which get a subset.
- `result = str(FUNCTIONS[name](self, **args))` (agent.py:266). That is the call: our `run`, the agent, the model's arguments as keywords.
- Then, for each call, `{"role": "tool", "tool_call_id": ..., "name": ..., "content": result}` is appended (agent.py:304) and the loop goes round again, so the model can read the result
  and either call another tool or answer.

### The shape of the result: always a string

The loader does not enforce a type — it calls `str(...)` on whatever comes back (agent.py:266). In practice **every tool in this repo returns `str`, and none returns a dict** (checked
with `grep -n "return {" tools/*/*.py`: no hits). That is on purpose:

- A dict would reach the model as Python's `repr`, i.e. `{'a': 1}` with single quotes — not JSON, easy to mis-read.
- A string can be formatted for the model: `read_result` returns `file: lines 1-37 of 1,204` followed by `12: text` lines (tools/results/read_result.py:25,34), `check_projects` returns a
  small prose report (sandbox.py:275-311).
- Some tools return another tool's return unchanged, which is only possible because it is a string: `tell` returns `agent.tell(...)` (tools/subagents/tell.py:2), `delegate` returns
  `agent.delegate(...)` (tools/subagents/delegate.py:4).
- `_skillfile.write` returns `None` on success (tools/skills/_skillfile.py:82); its three callers translate that `None` into their own sentence (`create_skill.py:22-25`,
  `edit_skill.py:24-29`) — nobody ever lets a `None` reach `str()`, which would show the model the word `None`.
- A tool result that is long is not shown whole: above `RESULT_TO_FILE` characters (8,000, config.py:31) the result is written to `results/000042-<tool>.txt` and the model gets a preview
  — where the file is, its size, the first 40 lines and the last 20 (agent.py:99-108, 269-270). Four tools are exempt because their whole text is the point: `load_skill`, `read_memory`,
  `read_result`, `search_result` (`WHOLE_RESULTS`, agent.py:94).

### What an error looks like to the model

Two flavours, and they look almost the same on purpose:

- **An exception** anywhere in the call is caught and turned into a string starting `error: ` (agent.py:267-268, comment: "errors go back to the model as text, so it can retry"). So
  `calculate` given a wrong argument name produces `error: run() got an unexpected keyword argument 'expr'`; addressing a tool the agent was not given produces `error: you have no tool
  called 'open_sandbox'. yours: calculate, load_skill, ...`.
- **A returned sentence** for the failures the tool expects: `"invalid expression"` (calculate.py:11), `"no sandbox runs in this instance. start one with open_sandbox (check_sandbox shows
  which ones there are)"` (sandbox.py:378), `"not saved: the memory file changed since you read it ... call read_memory again, ..."` (write_memory.py:11-12).

Why return instead of raise? Because the wording is then under the tool's control, and it can say what to do next in the model's own terms — "call read_memory first", "unmount_project
first, then delete it". An exception message would still be prefixed `error: `, but it would read like a Python failure, and the code that wants to catch it (the agent loop) cannot
distinguish a deliberate refusal from a bug. Several tools also *do* raise, for the case that must never happen: `_skillfile.path_of` and `file_of` raise `PermissionError` when a path
turns out to be outside `Skills/Learned/` (_skillfile.py:23-24, 30-31). That is a last line of defence behind the name check, and the model would see it as `error: that path is outside
Skills/Learned`.

One more convention worth spotting: refusals in this repo almost always start with a category word — `not saved: `, `not allowed: `, `no ... called '...'`, `invalid ...`, `error: `. A
model that sees `not saved:` knows nothing changed on disk, which is exactly the fact it needs to decide whether to retry.

### Who gets which tool

The tool list of an agent is fixed when the agent is constructed (agent.py:148-154) and never changes afterwards; `refresh_system()` rebuilds only the system prompt (agent.py:196-198).
Four rules decide membership:

- The main agent is built with `tools="all"`, `skills="all"`, `memory=True` (main.py:30), so it gets every tool the loader found — 31 of them today (README.md:54).
- A subagent gets the tools its template lists (agent.py:461) or, for a one-off subagent, `DEFAULT_SUBAGENT_TOOLS` (agent.py:466; config.py:43-44).
- `MAIN_ONLY_TOOLS` (config.py:39-42) are silently dropped from any subagent's list (agent.py:471-472) — no error, whatever a template says. That is the line of code behind "subagents
  never get sandbox/memory/skill tools, they work in their parent's sandbox".
- At `depth >= MAX_DEPTH` the tools `delegate` and `tell` are not added at all (agent.py:150), and `Agent.delegate` refuses anyway (agent.py:453-454). `MAX_DEPTH` is 3 (config.py:38), so
  depth 3 exists but cannot delegate.
- Small extra: any agent with at least one skill gets `load_skill` even if it was not listed (agent.py:152), because a skill list without a way to load a skill is useless.

The folders themselves are only for humans (tools/README.md:36). The groups, and what this chapter covers:

| Folder | Tool files | Tools |
|---|---|---|
| `basic/` | 2 | `calculate`, `load_skill` |
| `memory/` | 2 | `read_memory`, `write_memory` |
| `skills/` | 3 + helper | `create_skill`, `edit_skill`, `delete_skill` (+ `_skillfile.py`) |
| `subagents/` | 2 | `delegate`, `tell` |
| `sandbox/` | 10 | `sandbox_shell`, `check_sandbox`, `open_sandbox`, `close_sandbox`, `check_projects`, `mount_project`, `unmount_project`, `create_project`, `delete_project`, `rename_project` |
| `notebook/` | 9 | `nb_*` — chapter of its own |
| `results/` | 3 | `read_result`, `search_result`, `copy_result` — chapter of its own |

---

## 6.2 `tools/basic/` — the two tools everyone gets

README claim (tools/basic/README.md:3): "Two small tools every agent can use" — true for `calculate`, which is in every agent's list. `load_skill` is added
automatically for an agent with at least one skill (agent.py:152), and it is also in `DEFAULT_SUBAGENT_TOOLS` (config.py:43-44), so a subagent with no skills
still has it, where it can only answer "no skill called ...".

### `calculate` — do arithmetic without trusting the model's mental maths

**The description the model reads** (calculate.py:24): `"Evaluate a math expression, e.g. 2 * (3 + 4)."` One line, one example. Nothing about safety, nothing about limits: the model
does not need to know how it is implemented, only that it takes an expression and hands back a number. The example is where the format lives — the model sees `2 * (3 + 4)`, not
`2*(3+4)=` and not a sentence.

**`run(...)` line by line**

- `if not set(expression) <= set("0123456789+-*/().% ")` (calculate.py:10) — every character of the input must be in that whitelist. No letters, so `import`, `__class__`, `open` are
  impossible; no quotes or brackets. This one line is the whole security model, and it is why the tool can use `eval` at all.
- The evaluation happens in a **separate Python process**: `subprocess.run([sys.executable, "-I", "-c", "print(eval(input()))"], input=expression + "\n", ..., timeout=TIMEOUT)`
  (calculate.py:13-14). `-I` = isolated mode (no user site-packages, no environment tricks), `input()` reads the expression from stdin, so the expression itself is never spliced into
  Python source.
- `TIMEOUT = 5` (calculate.py:7) with the comment "a safety net for large calculations like 9**9**9**9, not a setting". A separate process is what makes the timeout possible: the parent
  kills it and carries on. `9**9**9**9` is legal input (only digits and `*`), so it passes the whitelist and then never finishes.
- On timeout: `"too big: no result after 5 seconds"` (calculate.py:16).
- On a non-zero exit: the **last line of stderr**, prefixed `error: ` (calculate.py:17-19). The last line is the exception line, which is exactly the useful part of a traceback.
- On success: `done.stdout.strip()` (calculate.py:20) — the printed result, no decoration.

**Gotchas**

- Only digits and `+-*/().% ` and spaces. `1,000` is invalid, `sqrt(2)` is invalid, `2^3` is invalid (`^` is not in the set; `**` is). The model gets `invalid expression` with no hint
  about which character was wrong.
- `.` in the whitelist allows float syntax and also nonsense like `1..2`, which then fails at eval and comes back as `error: SyntaxError: ...`.
- The result is Python's `print` of a number, so a float can arrive as `0.30000000000000004`.
- It ignores `agent` completely — a pure tool.

**Example** (reconstructed from the code): `calculate(expression="2 * (3 + 4)")` → `14`. `calculate(expression="1/0")` → `error: ZeroDivisionError: division by zero`.
`calculate(expression="9**9**9**9")` → `too big: no result after 5 seconds`. `calculate(expression="import os")` → `invalid expression`.

### `load_skill` — turn a skill's one-line menu entry into its full instructions

**The description the model reads** (load_skill.py:12): `"Load the full instructions of a skill from the list in your system prompt. Call it before doing a task that matches a skill."`
It points at *where the list is* (the system prompt), because the model has to look there for a name, and it says **before**, because loading a skill after doing the work is useless.
The system prompt repeats the same instruction in its own words (agent.py:164-165).

**`run(...)` line by line**

- `if name not in agent.skills or name not in SKILLS:` (load_skill.py:4) — two checks. `agent.skills` is the names this agent was allowed to load (agent.py:146, `pick_skills` at 192-194);
  `SKILLS` is the live menu read from disk (config.py:135-155). The second check catches a skill deleted between one refresh and this call.
- The failure text is a **list of what it does have**: `"no skill called '" + name + "'. yours: " + ", ".join(...) or "none"` (load_skill.py:5). That is deliberate: the model's next move
  should be to retry with a real name.
- `text = read_text(SKILLS[name]["path"])` (load_skill.py:6) — the path comes from the menu, **never from the model**. The only thing the model supplies is a name, so there is no path to
  escape with.
- `agent.skills_seen[name] = text` (load_skill.py:7) — remembers exactly what the model was shown. `edit_skill` compares the file against this before writing (edit_skill.py:21) so that a
  change made meanwhile is not silently overwritten.
- `return text` (load_skill.py:8) — the whole `SKILL.md`, header and all, goes into the conversation.

**Gotchas**

- Its result is in `WHOLE_RESULTS` (agent.py:94), so it is never moved into a results file even if long: a skill must be in context to be followed. Skills the agent writes are capped at
  15,000 characters (tools/skills/_skillfile.py:12), but a **user** skill has no cap anywhere in the code — a huge `Skills/<name>/SKILL.md` goes in whole.
- `load_skill` is added automatically to any agent with skills (agent.py:152); templates list it anyway (Templates/worker.md).
- It does not "activate" anything: what the model does next is follow text. The harness cannot check that it did.
- A skill whose folder name and header `name:` disagree is listed under the header name (config.py:149) — load it by that.

**Example** (reconstructed from the code): `load_skill(name="memory")` → the entire `Skills/memory/SKILL.md`, starting `---\nname: memory\ndescription: Use when the user asks you to
remember ...`. `load_skill(name="deploy")` → `no skill called 'deploy'. yours: memory, notebook`.

---

## 6.3 `tools/memory/` — one file, replaced whole

The memory is `Ego/MEMORY.md` (config.py:55). For the main agent its content is pasted into the system prompt on every rebuild (agent.py:181-183), inside `<memory>` tags. Subagents
never see it: `memory=True` is only passed by `main.py:30`, and both memory tools are in `MAIN_ONLY_TOOLS` (config.py:39). README claim (tools/memory/README.md:16) "Only the main agent
gets them" is enforced twice, by that config list and by the construction of subagents in `Agent.delegate`.

### `read_memory` — the file as it is right now

**The description the model reads** (read_memory.py:9): `"Read your memory file as it is right now. Always call it right before write_memory."` The second sentence is the important one:
it is a *sequencing instruction*, and it exists because `write_memory` refuses to write unless `read_memory` was called (and nothing has changed since). The phrase "right now" is there
because the copy in the system prompt can be stale — another instance, or the user, may have written since the prompt was built.

**`run(...)` line by line**

- `agent.memory_seen = read_text(MEMORY_FILE)` (read_memory.py:4) — reads the file, and records it as "what this agent has seen". This single line is what arms `write_memory`.
- `return agent.memory_seen or "(memory is empty)"` (read_memory.py:5) — an empty or missing file gives an explicit sentence instead of an empty result. (`read_text` returns `""` for a
  missing file, config.py:74-78.)

**Gotchas**

- No arguments at all (`"properties": {}`, read_memory.py:10) — it cannot be pointed anywhere else.
- `read_text` strips leading and trailing whitespace (config.py:78), so `memory_seen` is the stripped text. `write_text` also strips before writing (config.py:83): the round trip is
  stable, which is what makes the comparison in `write_memory` work.
- It is in `WHOLE_RESULTS` (agent.py:94): the memory file is meant to be small anyway ("keep it small: the whole file is sent with every request", Skills/memory/SKILL.md), and splitting
  it would defeat the point.

**Example** (reconstructed from the code): `read_memory()` → `# Memory\n\n## User\n\n## Preferences\n\n## Projects\n\n## Notes` — that is the current content of `Ego/MEMORY.md` in this
repo.

### `write_memory` — replace the whole file, but only if nothing moved

**The description the model reads** (write_memory.py:22): `"Replace your memory file. Pass the WHOLE new file, not only the change: anything you leave out is deleted."` All caps on
WHOLE. That is the one misunderstanding this tool cannot survive: a model that passes a diff quietly wipes the memory. The same sentence appears in the memory skill
(Skills/memory/SKILL.md, "How to change it" step 3) and in the error text at write_memory.py:6, so the model meets it three times.

**`run(...)` line by line**

- `if agent.memory_seen is None: return "not saved: call read_memory first. write_memory replaces the whole file"` (write_memory.py:5-6) — the tool refuses to write blind. `memory_seen`
  starts as `None` (agent.py:141).
- `if not locks.wait_take("memory")` (write_memory.py:7) — take the cross-instance lock named `memory`; `wait_take` retries every 0.1 s up to 5 s (locks.py:78-86). Lock = an OS file lock
  in `Locks/memory.lock`, released by the OS even on a crash (locks.py:1-10). Failure: `"not saved: another instance is saving the memory right now. try again"` (write_memory.py:8).
- Inside the lock: `if read_text(MEMORY_FILE) != agent.memory_seen:` (write_memory.py:10) — compare-and-swap, done on the file itself. Someone else wrote in between → refuse with a
  three-sentence explanation ending in "call read_memory again, put your change into what is there now, then write_memory" (write_memory.py:11-12).
- `write_text(MEMORY_FILE, content)` (write_memory.py:13) — one plain overwrite: the whole file, nothing appended.
- `agent.memory_seen = read_text(MEMORY_FILE)` (write_memory.py:14) — remember what this agent just wrote, so a second write in the same task does not trip over its own change.
- `finally: locks.release("memory")` (write_memory.py:15-16) — always give the lock back, also on an exception.
- `agent.refresh_system()` (write_memory.py:17) — rebuild the system prompt, so the `<memory>` block is current from the very next model call (agent.py:196-198).
- `return "saved (" + str(len(content)) + " characters)"` (write_memory.py:18) — note: the length of what the model *passed*, not of what is on disk (`write_text` strips and appends a
  newline, config.py:83), so the number can be off by one or two.

**Gotchas**

- The model never passes a path — the signature is `run(agent, content)` (write_memory.py:4), so `MEMORY.md` is the only file reachable. There is nothing to validate because there is
  nothing to point.
- Ordering matters: `read_memory` → `write_memory`, in that order, every task. If the model calls `write_memory` twice without re-reading, the second call succeeds because line 14 updated
  `memory_seen`.
- The lock is held for microseconds, but it is per lock *name*, so two instances writing at the same moment serialise; the second one then fails the comparison and has to re-read.
- A failure is a string, never an exception: the memory file is simply unchanged, and the model is told so with `not saved:`.

**Example** (reconstructed from the code): `read_memory()` then `write_memory(content="# Memory\n\n## User\n- name: Sam\n...")` → `saved (58 characters)`. A second instance writing in
between → `not saved: the memory file changed since you read it (another running instance, or the user). call read_memory again, put your change into what is there now, then
write_memory`.

---

## 6.4 `tools/skills/` — the agent writes instructions for its future self

A skill is a folder with a `SKILL.md`: header (`name`, `description`, and for learned ones `editable: yes` and `updated:`) plus markdown instructions. The menu is `SKILLS` in
config.py:133, built by `load_skills()` (config.py:135-155): it reads `Skills/` first (not editable) and then `Skills/Learned/` (editable), and the `editable` flag comes from **which
folder the file is in**, never from the header (config.py:139, 153; repeated in tools/skills/README.md:21 and Skills/Learned/README.md:7). The three skill tools are main-only
(config.py:42).

### `_skillfile.py` — the shared rules, not a tool

One line of the loader skips it (`agent.py:37`: no file starting with `_` is a tool), which is exactly why the shared code lives there: one name check, one path check, one writer, used by all three
tools. What is inside:

- `MARK` (lines 10-11): the sentence `> Editable: you wrote this skill yourself...` written at the top of every learned skill by the tool, never by the agent. `MAX_BODY = 15_000` (line
  12), because a skill goes into the conversation whole.
- `check_name` (14-18): `re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)` and `len(name) > 40`. Lowercase, digits, single hyphens between groups. The name is also the folder name, hence the
  strictness. Failure: `invalid name: lowercase letters, digits and hyphens only, at most 40 characters, e.g. clean-csv-files`.
- `path_of` (20-25): `<LEARNED_SKILLS_DIR>/<name>/SKILL.md`, then `os.path.realpath(path)` must start with the real path of `Skills/Learned/` **plus a separator** — that trailing `os.sep`
  is what stops a sibling folder like `Skills/Learned-x/` from passing. It raises `PermissionError("that path is outside Skills/Learned")` otherwise. Belt and braces: `check_name` already
  makes `..` impossible, so this raise is unreachable through the model.
- `file_of` (27-32): the same containment check, but for an *existing* skill, taken from `SKILLS[name]["path"]` — the folder may be spelled differently from the header `name:`. Also
  raises `PermissionError`.
- `editable_names` (34-35): `", ".join(...)` of the editable skills, or `none yet` — used in every "you can't do that" message, so the model is told what it *can* change.
- `may_change` (37-46): the gate for edit and delete. Order: bad name → no such skill → not editable. The middle message is `there is no skill called 'x'. your editable skills: ...`; the
  last one is `'x' is one of the user's skills: you can't change or delete it. your editable skills: ...`.
- `header_value` (48-53): collapses whitespace and quotes the value if it contains `:` or `#` or starts with a YAML-hostile character, because GitHub reads the header as YAML.
- `clean_body` (55-64): the model is allowed to pass back the whole text it got from `load_skill` — this strips a leading `---`/`name:` header block and a leading `> Editable:` line, so
  the tool can write its own. A plain `---` divider is left alone (the `"\nname:"` test).
- `write` (66-82): validates (description non-empty, body non-empty, `len(body) <= MAX_BODY`), then writes `---\nname: ...\ndescription: ...\neditable: yes\nupdated:
  <today>\n---\n\n<MARK>\n\n<body>`, calls `load_skills()` to re-read the menu and `agent.refresh_system()` so the new skill is in the prompt at once. Returns `None` on success or a
  problem string. That `None`/string convention is exactly the str-vs-None rule from 6.1: the caller turns `None` into a sentence.

### `create_skill` — save a new skill

**The description the model reads** (create_skill.py:29-34, shortened): "Save a new skill: step-by-step instructions you follow the next time a similar task comes up. Create one when
you solved a task that will likely come again and you had to work out how ... Not for facts about the user (that is memory) and not for one-off tasks. Check your skill list first:
improve an existing skill instead of making a second one. ... Tell the user in one short sentence what you saved." Every sentence steers a failure mode: skills for one-offs (clutter),
skills duplicating memory (wrong file), duplicate skills (the list rots), and silent saving (the user should know their agent just wrote itself instructions).

**`run(...)` line by line**

- `if not locks.wait_take("skills")` (create_skill.py:6) → `"not saved: another instance is changing a skill right now. try again"`. One lock name, `skills`, shared by all three tools, so
  create/edit/delete across instances never interleave.
- `load_skills()` inside the lock (line 9) — re-read the menu, so a skill another instance created a second ago counts as a name collision here.
- `return create(agent, name, description, body)` inside `try`, lock released in `finally` (lines 10-12).
- `create` (14-25): `check_name` first; then `if name in SKILLS` — already editable → `"you already have a skill called 'x'. change it with edit_skill, or pick another name"`; already the
  user's → `"'x' is the name of one of the user's skills. pick another name"`. Then `_skillfile.write(...)`, and on success `"created skill 'x' in Skills/Learned (editable). it is in your
  skill list now; load it with load_skill"` (line 25).

**Gotchas**

- No `load_skill` needed first — there is nothing to see yet. (`edit_skill` is the opposite.)
- The body limit is on the *cleaned* body: pass 20,000 characters including a header and you may still get in, pass 20,000 of real instructions and you get `too long (20000 characters, at
  most 15000). a skill should be short: cut it down`.
- A name that collides with a *learned* skill is a refusal, not an overwrite; a learned skill whose header name equals a user skill's name is ignored in the menu entirely
  (config.py:150-151), so `create_skill` will say the name belongs to the user.

**Example** (reconstructed from the code): `create_skill(name="clean-csv-files", description="Use when the user asks to clean a CSV file.", body="# Clean a CSV\n\n1. read it with pandas
...")` → `created skill 'clean-csv-files' in Skills/Learned (editable). it is in your skill list now; load it with load_skill`. File written: `Skills/Learned/clean-csv-files/SKILL.md`.

### `edit_skill` — rewrite one of its own skills, if nothing moved

**The description the model reads** (edit_skill.py:33-35): "Rewrite one of your own skills (those marked [editable] in your skill list). Load it with load_skill first, then pass the
WHOLE new body, not only the change: what you leave out is gone. The user's skills can't be edited. Tell the user in one short sentence what you changed." It names the `[editable]` tag
the system prompt uses (agent.py:169), states the read-first rule, and repeats the WHOLE warning because it is the same trap as memory.

**`run(...)` line by line**

- Lock `skills`, `load_skills()`, then `edit(...)` (edit_skill.py:6-12) — same pattern as create.
- `_skillfile.may_change(name)` (line 15) — name, existence, editability. A user skill gives `'memory' is one of the user's skills: you can't change or delete it. your editable skills:
  clean-csv-files`.
- `seen = agent.skills_seen.get(name)`; `if seen is None: return "not saved: load the skill with load_skill first. edit_skill replaces its whole text"` (lines 18-20). This is the
  read-before-write guard, keyed by skill name.
- `if read_text(_skillfile.file_of(name)) != seen:` (line 21) — compare-and-swap against the file. Changed meanwhile → `"not saved: the skill changed since you loaded it (another running
  instance, or the user). load_skill it again, put your change into what is there now, then edit_skill"` (lines 22-23).
- `_skillfile.write(agent, name, description or SKILLS[name]["description"], body, path=_skillfile.file_of(name))` (24-25) — `description or <current>` keeps the old one-line `Use when
  ...` when the model omits it; `path=` targets the real file, so a folder whose name differs from the header is still edited in place.
- `agent.skills_seen[name] = read_text(...)` (line 28) then `return "updated skill 'x'"` (line 29).

**Gotchas**

- State lives in the agent object (`skills_seen`, agent.py:143), so "loaded it" means *this agent, in this conversation*. A new conversation must `load_skill` before it can `edit_skill`.
- The description is optional in the schema (`required: ["name", "body"]`) — a natural place for a model to accidentally drop the trigger phrase; the code protects against that with `or`.
- Editing does not change the folder name: the file stays at `Skills/Learned/<original-folder>/SKILL.md`, and the header `name:` is rewritten to the name the model passed. Since the menu
  keys on the header name (config.py:149), a header rename effectively renames the skill in the list while the folder keeps the old name.

**Example** (reconstructed from the code): `load_skill(name="clean-csv-files")`, then `edit_skill(name="clean-csv-files", body="# Clean a CSV\n\n1. read it with pandas, dtype=str ...")`
→ `updated skill 'clean-csv-files'`. Without the `load_skill` first: `not saved: load the skill with load_skill first. edit_skill replaces its whole text`.

### `delete_skill` — remove one of its own skills

**The description the model reads** (delete_skill.py:30-32): "Delete one of your own skills (those marked [editable] in your skill list), e.g. when it turned out wrong or is no longer
useful. It can't be undone. The user's skills can't be deleted. Tell the user in one short sentence what you deleted." It gives a *reason* to delete (wrong, useless), says it is
irreversible, and repeats the ownership rule — deletion is the one operation where a mistake is not recoverable by `load_skill`.

**`run(...)` line by line**

- Lock `skills`, `load_skills()`, `delete(...)` (delete_skill.py:7-13); failure to get the lock → `"not deleted: another instance is changing a skill right now. try again"` — note the
  different first word, so the model can tell which tool refused.
- `_skillfile.may_change(name)` (line 16), then `path = _skillfile.file_of(name)` (line 19) — the real file, containment-checked.
- `os.remove(path)` (line 20), then `if not os.listdir(folder): os.rmdir(folder)` (21-23) — the folder goes **only if empty**; any other file the user put in it stays, so the tool cannot
  destroy data it does not own.
- `load_skills()` and `agent.refresh_system()` (24-25) — gone from the menu and from the prompt immediately.
- `return "deleted skill 'x'"` (line 26).

**Gotchas**

- No `load_skill` first, unlike `edit_skill` — deleting does not replace text, so there is nothing to be stale.
- No confirmation prompt: the model is trusted to only delete what the user agreed to, which is why the description says "tell the user". The harness itself has no veto.
- The user's own skills are unreachable twice over: `may_change` refuses non-editable names, and `file_of` would raise if a path outside `Skills/Learned/` ever got into the menu under an
  editable flag.

**Example** (reconstructed from the code): `delete_skill(name="clean-csv-files")` → `deleted skill 'clean-csv-files'`. On a user skill: `delete_skill(name="memory")` → `'memory' is one
of the user's skills: you can't change or delete it. your editable skills: none yet`.

---

## 6.5 `tools/subagents/` — two one-line tools over `agent.py`

tools/subagents/README.md:3 says it plainly: "The logic lives in `agent.py` (`Agent.delegate` and `Agent.tell`); these two files only call it." That is literally the code:
`delegate.py:4` and `tell.py:2` are single delegating returns. The reason is that a subagent is not a side effect of a tool — it is another `Agent` object in the same process, sharing
the tool registry, the sandbox, and the event loop's threads.

### `delegate` — create a subagent, give it one task, get its report

**The description the model reads** (delegate.py:8-15, shortened): "Create a subagent and give it one task; you get its report back. Either name a template ... OR write instructions for
a one-off subagent, optionally with its tools and skills. The subagent starts with an empty context: it knows only its instructions ... and your task, so put every fact it needs into
the task. Several delegate calls in one reply run at the same time = parallel. The report starts with DONE, BLOCKED or QUESTION; answer a QUESTION with the tool tell ... Limits: 5 live
subagents, 3 levels of depth in total." Note the numbers are **interpolated at import time** from `MAX_CHILDREN` and `MAX_DEPTH` (delegate.py:1, 15), so the text cannot drift from the
code.

**`run(...)` line by line**

- `return agent.delegate(task, template, instructions, tools, skills)` (delegate.py:4) — everything else happens in `Agent.delegate` (agent.py:452-497):
- Depth gate: `if self.depth >= MAX_DEPTH: return "not allowed: agents at depth N may not create subagents. do the task yourself"` (agent.py:453-454).
- Template or instructions: a template must exist (`"no template called 'x'. available: worker, coder"`, agent.py:457-459) and supplies instructions, tools and skills, which the parent
  may still override (agent.py:461-462). No template and no instructions → `"give a template, or instructions for a one-off subagent"` (agent.py:464). A one-off gets
  `DEFAULT_SUBAGENT_TOOLS` (agent.py:466).
- `MAIN_ONLY_TOOLS` are silently skipped and unknown names are errors: `"unknown tool 'x'. available: ..."` / `"unknown skill 'x'. available: ..."` (agent.py:469-478).
- Under `self.lock` (parallel delegate calls): the `MAX_CHILDREN` check → `"not allowed: you already have 5 subagents. wait for them or ask them more with tell"`; then the id `worker-1`,
  `sub-2` (agent.py:483-484), the folder `agents/<timestamp>-<id>/`, and the child `Agent` itself (agent.py:485-492). The child's `transcript.md` is opened and stays open while it lives
  (agent.py:489).
- `report = child.ask(task)` (agent.py:495) — this call **blocks** until the child's turn is over. Parallelism comes from `run_tools` putting each tool call in its own thread
  (agent.py:292-297), not from inside this function.
- `child.waiting = ... == "QUESTION"` (agent.py:496) — a QUESTION keeps the child alive for `tell`.
- `return self.report_head(id, child) + report` (agent.py:497) — the head is `[worker-1, its files: agents/20261019-20-16-00-worker-1/] ` (agent.py:508-510), so the parent knows the id
  *and* where the child's result files are.

**Gotchas**

- The child starts empty: it does not see the parent's conversation, files, or reasoning. Anything missing from `task` is missing forever — that is why the parameter description is
  "objective, all needed context, expected output, limits" (delegate.py:17).
- The tool name is absent at depth 3 (agent.py:150) *and* refused inside `delegate` (agent.py:453): two independent guards, so a hand-written tool list cannot create a fourth level.
- Children inherit the sandbox because `sandbox` keeps its state in module globals (`my_container`, sandbox.py:34-36) — every `Agent` in the process sees the same container. There is no
  per-agent sandbox to pass.
- The parent's report is the child's *final message*, unvalidated: if the child ignores the format, `report_status` prints `[name replied]` and the parent gets the text as-is
  (agent.py:520-522).
- A child that ends is closed with its parent's task (`close_children(keep_waiting=True)`, agent.py:339-340, 524-532) — live subagents do not outlive the task that made them.

**Example** (reconstructed from the code): `delegate(task="Count the functions in agent.py and report the number.", template="worker")` → `[worker-1, its files:
agents/20261019-20-16-00-worker-1/] DONE: agent.py has 2 module-level functions and 28 methods. Counted with grep -c "^def " agent.py -> 2 and grep -c "^    def " agent.py -> 28.` At
depth 3 the same call → `not allowed: agents at
depth 3 may not create subagents. do the task yourself`.

### `tell` — one more message to a live subagent

**The description the model reads** (tell.py:6-7): "Send a follow-up message to one of your live subagents (it keeps its full context) and get its next report. Use the id delegate
returned, e.g. worker-1. One message per subagent per reply." Two facts the model needs: the id comes from the report head, and "keeps its full context" means you do not have to repeat
the task. "One message per subagent per reply" mirrors the agent loop — the same id twice in one reply would run two `ask()` calls on the same child, serialised by `self.busy`
(agent.py:308).

**`run(...)` line by line**

- `return agent.tell(id, message)` (tell.py:2) → `Agent.tell` (agent.py:499-506):
- `child = self.children.get(id)`; not found → `"no live subagent called 'x'. live: worker-1"` (agent.py:500-502). "Live" is the key word: a subagent whose last report was DONE is already
  closed.
- `report = child.ask(message)` (agent.py:504) — the same `Agent` object, so its `messages` list still holds everything.
- `child.waiting = ... QUESTION ...` (agent.py:505), then `return self.report_head(id, child) + report` (agent.py:506) — same head as `delegate`, so the parent always has the id in front
  of every report.

**Gotchas**

- The id is per parent (`worker-1`, `worker-2`, `sub-1`), not global; two parents can both have a `worker-1`.
- `tell` blocks exactly like `delegate`; "while they work" in the README means the harness can hold several children at once, not that `tell` returns early.
- Answering a `QUESTION` is the only way to keep a child alive across tasks: `close_children(keep_waiting=True)` keeps only those with `waiting == True` (agent.py:524-532). A child that
  reported DONE cannot be told anything afterwards.
- `MAIN_ONLY_TOOLS` does not contain `tell`/`delegate`; they are governed by the depth rule instead (config.py:39-42 vs agent.py:150).

**Example** (reconstructed from the code): `tell(id="worker-1", message="Use grep -c instead of reading the whole file.")` → `[worker-1, its files: agents/20261019-20-16-00-worker-1/]
DONE: recounted: 2 module-level functions and 28 methods, as before.` Wrong id → `no live subagent called 'worker-2'. live: worker-1`.

---

## 6.6 `tools/sandbox/` — the ten tools that own the container and the projects

Every one of these files has the same shape: `run` validates nothing itself, it calls one function in `sandbox.py` and returns its string (`check_sandbox.py:3-4`, `sandbox_shell.py:4-5`, ...). All the
state is module-level in `sandbox.py`: `my_container`, `my_sandbox`, `my_project` and a `threading.Lock` (sandbox.py:34-38). That has two consequences worth holding on to:

- **One container per instance, shared by every agent in the process.** `my_container` is global, so a subagent's `sandbox_shell` runs in its parent's container
  (tools/sandbox/README.md:33) — nothing is passed, nothing is per-agent.
- **Only the main agent gets the nine management tools** (`open_sandbox`, `close_sandbox`, `check_sandbox`, `check_projects`, `mount_project`, `unmount_project`, `create_project`,
  `delete_project`, `rename_project`) because they are listed in `MAIN_ONLY_TOOLS` (config.py:39-42); `sandbox_shell` is the one every agent gets. A subagent therefore cannot restart or
  steal a sandbox out from under the task it is working on.

Three rules that the whole folder rests on: a **project** is a folder directly in `Shared/` except `common` and `Notebooks_Engine` (sandbox.py:75-77, 224-230); a project name must match
`[A-Za-z0-9][A-Za-z0-9._-]*` and be at most 60 characters (sandbox.py:31, 242-250); and any change to the mounts **restarts** the container because podman cannot add a folder to a
running container (sandbox.py:201-211).

### `sandbox_shell` — the only way to run a command

**The description the model reads** (sandbox_shell.py:9-16, shortened): "Run a bash command inside this instance's sandbox (a Linux container, you are root in it). Two folders in it are
the user's and are kept: /workspace/common ... and /workspace/<project> ... The command starts in the project, or in /workspace/common when none is mounted. Everything else inside is
yours, install and build freely, but it is gone when the sandbox stops. Files in the user's folders can't be executed directly: run them with an interpreter (python x.py, bash x.sh).
... A command still running after 600 seconds is stopped ... for longer jobs, start them in the background with their output in a file (nohup ... > x.log 2>&1 &)". It is written as a
map of the world, because a model that thinks it is on the user's machine will do terrible things. The `noexec` and timeout facts are in there for the same reason: they are surprises
otherwise. `600` is interpolated from `MAX_TOOL_TIMEOUT` (sandbox_shell.py:2, 14; config.py:50).

**`run(...)` line by line**

- `return sandbox.exec(command, MAX_TOOL_TIMEOUT)` (sandbox_shell.py:5). In `exec` (sandbox.py:375-388): no container → `"no sandbox runs in this instance. start one with open_sandbox
  (check_sandbox shows which ones there are)"`; then `podman exec -w <workdir> <container> timeout -k 5 600 bash -c <command>` (sandbox.py:380-381) — a timeout **inside** the container
  (so the container reaps the process) and a Python-side timeout of `timeout + 10` as a backstop.
- `workdir()` is `/workspace/<project>` or `/workspace/common` (sandbox.py:79-83).
- Exit code 124 (the inner `timeout` fired) → `out + "\nerror: stopped after 600 seconds"`; any other non-zero → `out + "\n(exit code N)"`; empty output → `"(no output)"`; otherwise the
  output alone (sandbox.py:384-388).

**Gotchas**

- Failure is still a normal tool result: the command's own stderr *plus* an exit-code line, so the model sees both the error and that it was an error. Nothing is raised.
- `(exit code N)` is the only signal that a command failed — no prefix, no `error:`. One reason a model sometimes misses it.
- Output size is unbounded here; that is what `RESULT_TO_FILE` (8,000 characters, config.py:31) and `read_result` are for.
- The 600 s limit is fixed, not a parameter (sandbox_shell.py:5 comment: "the limit is fixed").
- Inside, the agent is root (tools/sandbox/README.md:30), but the mounts are `noexec`, so `./script.sh` fails and `bash script.sh` works (sandbox.py:163-168).

**Example** (reconstructed from the code): `sandbox_shell(command="python -c 'print(6*7)'")` → `42`. `sandbox_shell(command="ls /nope")` → `ls: cannot access '/nope': No such file or
directory\n(exit code 2)`. With no container: `no sandbox runs in this instance. start one with open_sandbox (check_sandbox shows which ones there are)`.

### `check_sandbox` — read-only look at the sandboxes

**The description the model reads** (check_sandbox.py:8-11, shortened): "Look at the sandboxes without changing anything: each one's whole Containerfile (what is installed in it, so
what it is good for), whether its image is built, and which one runs in this instance (one at most). Without a name: all of them. Call it to pick the right sandbox before open_sandbox
...". "Without changing anything" and "before open_sandbox" are the load-bearing parts: this is the *choosing* tool, and a model that believes a check might have side effects will not
call it.

**`run(...)` line by line**

- `return sandbox.status(name)` (check_sandbox.py:4). `status` (sandbox.py:336-371): podman missing → `NOT_AVAILABLE`; unknown name → `"no sandbox called 'x'. sandboxes: python, ubuntu"`;
  no sandboxes at all → a sentence telling the user to make one.
- Without a name it first prints `running in this instance: none. one sandbox per instance.` and a line about every start rebuilding the image, then one block per sandbox: `=== sandbox:
  python ===`, `image: built 2026-10-11 18:12:03` (or "not built yet, it is built at the first start (can take a while)"), `state: ...`, `also running in N other instance(s) ...`, and
  finally `Containerfile:` followed by the **whole** file (sandbox.py:346-371).

**Gotchas**

- It calls `cleanup()` (sandbox.py:345), which removes containers of instances that are gone (sandbox.py:108-114) — so "changes nothing" is true of your setup, not of the podman process
  list.
- The whole Containerfile is printed for every sandbox on every call: with several big sandboxes that is a long result and goes to a results file.
- It reflects *other* instances too (`also running in N other instance(s)`, sandbox.py:328-334), not just yours.

**Example** (reconstructed from the code): `check_sandbox()` → `running in this instance: none. one sandbox per instance.` then the explanation line, then `=== sandbox: python ===` /
`image: built 2026-10-19 20:20:41` / `state: not running in this instance` / `Containerfile:` / `FROM python:3.12` ...

### `open_sandbox` — start the chosen sandbox (optionally with a project)

**The description the model reads** (open_sandbox.py:8-12, shortened): "Start a sandbox, so sandbox_shell and the notebooks work. Pick it by what it is made of: check_sandbox shows
every sandbox's Containerfile. Only one sandbox runs per instance: to switch, close_sandbox first. Every start is clean, exactly as its Containerfile says. /workspace/common is always
mounted ... Give a project to mount that project folder too ...: mounting it later with mount_project restarts the sandbox, so if you already know the project, give it here." The last
sentence saves a restart; the "you are not asked" behaviour is not in the text — the agent decides, the user is not prompted (open_sandbox.py:4 comments it).

**`run(...)` line by line**

- `return sandbox.open_sandbox(name, project)` (open_sandbox.py:4) → sandbox.py:408-431, all under the module lock: podman missing → `NOT_AVAILABLE + ". tell the user"`; already running →
  `"a sandbox already runs in this instance: python. only one per instance: close_sandbox first if you need another one"`; unknown name → `"no sandbox called 'x'. sandboxes: python,
  ubuntu (check_sandbox shows what is in them)"`; a project is validated with `check_project` **before** anything starts (sandbox.py:420-423).
- `start(name, project, False)` (sandbox.py:142-177): build the image from the Containerfile (failure → the end of the build log, sandbox.py:134-140), then `podman run -d --rm` with
  labels `harness.owner`, `harness.sandbox`, `harness.shared` (sandbox.py:154-157), `--network podman` sealed right after, `--pids-limit 512 --memory 2g --cpus 2`, mounts
  `common:...:z,noexec`, the engine `:ro`, and the project `:Z,noexec`, working dir `/workspace/<project or common>`, command `sleep infinity` (sandbox.py:163-169).
- Success: `"running " + name + ", " + network + ". " + where()` (sandbox.py:431) where `network` is `"network off"` or `"network could NOT be sealed, careful"` (sandbox.py:427-430) and
  `where()` describes the mounts (sandbox.py:213-220).

**Gotchas**

- The network is off at every start; only the user can turn it on with `/sandbox net on` (tools/sandbox/README.md:32). The model is told "network off" in the result.
- A project mounted here behaves exactly like one mounted later, minus the restart.
- `cleanup()` inside `start` (sandbox.py:146) removes crashed instances' containers, which is what frees their projects.
- There is no "start the default one": the model must name a sandbox, and the names are the folders in `Sandboxes/` (sandbox.py:53-60).

**Example** (reconstructed from the code): `open_sandbox(name="python", project="website")` → `running python, network off. /workspace/common = Shared/common, shared with every other
instance; /workspace/website = Shared/website, your project, no other instance can mount it now. working folder: /workspace/website. everything outside these folders is gone when the
sandbox stops`.

### `close_sandbox` — stop it, keep the files

**The description the model reads** (close_sandbox.py:8-10): "Stop this instance's sandbox. Everything installed or started inside is gone; the files in /workspace/common and in the
mounted project stay, and the project is free for other instances again. Needed before open_sandbox can start another one. When the user exits, the sandbox is stopped anyway." It
answers the two questions a model has after a stop: did I lose my work, and can I start another.

**`run(...)` line by line**

- `return sandbox.close_sandbox()` (close_sandbox.py:4) → nothing running: `"no sandbox runs in this instance"` (sandbox.py:436-437); otherwise `stop()` = `podman stop -t 2` plus
  resetting the globals and releasing notebook locks (sandbox.py:187-189, 179-185), then `"stopped python. whatever was installed or started inside is gone; the files in the mounted
  folders stay"` plus `". website is free for other instances again"` when a project was mounted (sandbox.py:440-443).

**Gotchas**

- The container is started with `--rm` (sandbox.py:154), so stopping deletes it: there is nothing to restart, the next `open_sandbox` builds and runs a fresh one.
- The project is freed because its container is gone, not because anything is written down (`holder()` asks podman every time, sandbox.py:232-240).
- It is the required first step before switching sandboxes (one per instance, sandbox.py:414-416).

**Example** (reconstructed from the code): `close_sandbox()` → `stopped python. whatever was installed or started inside is gone; the files in the mounted folders stay. website is free
for other instances again`.

### `check_projects` — who has which project

**The description the model reads** (check_projects.py:8-10): "List the project folders in the user's Shared/ folder, and for each whether it is free, mounted by you, or mounted by
another instance. Also says what this instance has mounted, and about /workspace/common, the folder every instance shares. Call it before mount_project or open_sandbox with a project."
The three states are the whole point: mounting is exclusive, so the model must know whether it can.

**`run(...)` line by line**

- `return sandbox.projects_status()` (check_projects.py:4) → sandbox.py:275-311. Podman missing → `NOT_AVAILABLE`. Then three fixed explanation lines (projects, common, Notebooks_Engine),
  one line about this instance (`no sandbox runs` / `sandbox python, project website mounted at /workspace/website (the working folder)`), and then per project: `- website: free`, `-
  website: mounted by you`, `- website: mounted by another instance, not available now`, or `- my data!: can't be mounted, its name has other characters than letters, digits, - _ . (the
  user can rename it)`.

**Gotchas**

- A folder with a name the regex rejects is listed as unmountable rather than hidden — that is how the model learns why `mount_project("my data!")` would fail.
- It also calls `cleanup()` (sandbox.py:280), so a crashed instance's leftover container disappears and its project shows as free.
- `common` and `Notebooks_Engine` are never projects (sandbox.py:224-230); the header lines say so every time, so the model is not tempted to mount them.

**Example** (reconstructed from the code): `check_projects()` → the three explanation lines, `this instance: sandbox python, project website mounted at /workspace/website (the working
folder)`, `projects:`, `- website: mounted by you`.

### `create_project` — a new empty folder in `Shared/`

**The description the model reads** (create_project.py:8-9): "Create a new, empty project folder in the user's Shared/ folder. Then mount_project mounts it into your sandbox. Check the
list first (check_projects): if the work belongs to an existing project, use that one." The last clause is steering against project sprawl — one folder per task is a mess the user has
to clean up.

**`run(...)` line by line**

- `return sandbox.create_project(name)` (create_project.py:4) → sandbox.py:470-481: `name_problem` (reserved names, regex, length); existing name in any spelling → `"a project called
  'web' exists already"`; a *file* with that name → `"there is a file called 'x' in Shared/ already: pick another name"`; then `os.makedirs` and `"created project sales-2026
  (Shared/sales-2026). mount_project mounts it"`.

**Gotchas**

- `spelled()` (sandbox.py:252-258) keeps mac/windows case-insensitive folders from creating two projects that are one folder.
- It does not mount anything: creating and mounting are separate, so a model can create a project and still have to mount it.
- The name is validated *before* any filesystem call, so `../etc` is rejected as `invalid project name`, never resolved.

**Example** (reconstructed from the code): `create_project(name="sales-2026")` → `created project sales-2026 (Shared/sales-2026). mount_project mounts it`.
`create_project(name="common")` → `common is not a project: it is always mounted in every sandbox, at /workspace/common, and no tool changes it`.

### `mount_project` — make a project the working folder (restarts)

**The description the model reads** (mount_project.py:8-13, shortened): "Mount a project folder into this instance's sandbox, at /workspace/<name>. It becomes the working folder. A
project is a folder directly in the user's Shared/ folder ... One project at a time: mounting another one unmounts the current one. A project another instance has mounted can't be
mounted. This RESTARTS the sandbox ... whatever was installed or started inside since its start is gone, open notebooks are closed. So mount first, then install and work." "So mount
first, then install and work" is the operational takeaway; caps on RESTARTS because a model that mounts after a 10-minute install wastes it.

**`run(...)` line by line**

- `return sandbox.mount_project(name)` (mount_project.py:4) → sandbox.py:445-459, under the lock: no container → `"no sandbox runs in this instance. open_sandbox first (it can mount the
  project right away)"`; same project → `"website is mounted already, at /workspace/website"`; `check_project` for name, existence, spelling, and other-instance holder.
- `restart(project)` (sandbox.py:201-211): stop, start again with the same sandbox name and the same network state, then `"restarted python with the new folders: whatever was installed or
  started inside since its start is gone, open notebooks are closed (nb_open them again), network off. " + where()`. If the old mount was a different project, the answer is prefixed
  `"unmounted website (free for other instances again). "` (sandbox.py:457-458).

**Gotchas**

- Mounting is exclusive per project per *host*: `holder()` looks at every container of every instance (`sandbox.py:232-240`), so a project another instance has is refused with a sentence
  naming the reason.
- If the restart fails to start, the message is `"the sandbox was stopped, but could not start again: ..."` (sandbox.py:208-209) — the model is left with no sandbox and has to
  `open_sandbox`.
- The project folder must already exist; `create_project` or the user makes it.

**Example** (reconstructed from the code): `mount_project(name="website")` → `restarted python with the new folders: whatever was installed or started inside since its start is gone,
open notebooks are closed (nb_open them again), network off. /workspace/common = Shared/common, shared with every other instance; /workspace/website = Shared/website, your project, no
other instance can mount it now. working folder: /workspace/website. everything outside these folders is gone when the sandbox stops`.

### `unmount_project` — give it back (restarts)

**The description the model reads** (unmount_project.py:8-10): "Unmount the project from this instance's sandbox, so other instances can mount it. Its files stay in the user's Shared/
folder. /workspace/common stays mounted, it can't be unmounted. This RESTARTS the sandbox: whatever was installed or started inside since its start is gone, open notebooks are closed."
Same restart warning; the "files stay" sentence prevents the model from copying data out in a panic.

**`run(...)` line by line**

- `return sandbox.unmount_project()` (unmount_project.py:4) → sandbox.py:461-468: no container → `"no sandbox runs in this instance"`; nothing mounted → `"no project is mounted. (common
  is always mounted and can't be unmounted)"`; otherwise `"unmounted website, it is free for other instances again. " + restart(None)`.

**Gotchas**

- It restarts even though the container could in principle just be stopped — because the same code path must keep `common` mounted and the working folder correct, and `restart` is the
  only thing that knows how to start this instance's sandbox (sandbox.py:201-211).
- No name argument: it unmounts *the* project, since there is at most one.

**Example** (reconstructed from the code): `unmount_project()` → `unmounted website, it is free for other instances again. restarted python with the new folders: ... working folder:
/workspace/common. ...`.

### `rename_project` — rename a folder no sandbox is using

**The description the model reads** (rename_project.py:8-10): "Rename a project folder in the user's Shared/ folder. Not possible while any sandbox has it mounted (yours too:
unmount_project first), and common and Notebooks_Engine can't be renamed. Tell the user in one short sentence what you renamed." The parenthetical "(yours too)" exists because the
model's first guess is that its own mount is fine.

**`run(...)` line by line**

- `return sandbox.rename_project(name, new_name)` (rename_project.py:4) → sandbox.py:503-522: reserved old → `name_problem(old)`; missing old → `"no project called 'x'. projects: ..."`;
  new name validated; a clash in any spelling → `"a project called 'web' exists already"`; `holder(old)` → `"website is mounted in your sandbox: unmount_project first, then rename it"` or
  `"website is mounted by another instance right now: it can only be renamed when no sandbox has it mounted"`; then `os.rename` and `"renamed project website -> site (Shared/site)"`.

**Gotchas**

- Renaming `web` → `Web` is allowed (the clash test skips the folder itself, sandbox.py:513-515); other spellings of an existing name are refused.
- Because it is a plain `os.rename` inside `Shared/`, any open file inside the folder follows it; nothing in the container is touched because nothing can be mounted at that moment.
- The new name must pass the same 60-character regex as `create_project` (sandbox.py:248-249).

**Example** (reconstructed from the code): `rename_project(name="website", new_name="site")` → `renamed project website -> site (Shared/site)`.

### `delete_project` — remove a project with everything in it

**The description the model reads** (delete_project.py:8-11): "Delete a project folder in the user's Shared/ folder, with EVERYTHING in it. It can't be undone: only do it when the user
asked you to delete that project. Not possible while any sandbox has it mounted (yours too: unmount_project first). common and Notebooks_Engine can't be deleted. Tell the user in one
short sentence what you deleted." This is the most dangerous tool in the repo, and the description is written like a warning label: it is the only one that says "only do it when the
user asked".

**`run(...)` line by line**

- `return sandbox.delete_project(name)` (delete_project.py:4) → sandbox.py:483-501: reserved name → the `common`/`Notebooks_Engine` explanation; wrong spelling → `"that project is called
  'Web': use that spelling"`; not a project → `"no project called 'x'. projects: ..."`.
- `if os.path.islink(path): return "x is a link to another folder, not a folder in Shared/: the user has to remove it"` (sandbox.py:493-494) — the one explicit symlink check in the
  folder. Nothing is ever deleted *through* a link.
- `holder(name)`: mounted by you → `"website is mounted in your sandbox: unmount_project first, then delete it"`; mounted by someone else → `"... it can only be deleted when no sandbox
  has it mounted"`.
- `shutil.rmtree(path)` (sandbox.py:500) — folder and contents, no trash, no undo. Answer: `"deleted project sales-2026 and everything in it"`.

**Gotchas**

- `reserved()` is checked first and case-insensitively (`Common` is `common` on mac), sandbox.py:75-77, 486-487.
- `create_project` and `mount_project` do **not** test `os.path.islink`; only delete does. A symlink the *user* put in `Shared/` is listed by `projects()` (which follows `isdir`) and
  could be mounted, but never deleted through. Whether that is intended is unclear from the code.
- There is no confirmation and no dry run: `check_projects` is the only way to see what a name is before it goes.

**Example** (reconstructed from the code): `delete_project(name="sales-2026")` → `deleted project sales-2026 and everything in it`. While mounted: `delete_project(name="website")` →
`website is mounted in your sandbox: unmount_project first, then delete it`.

---

## What this chapter hands to the rest of the guide

**Result shape.** Every tool hands back a `str` — no tool in the repo returns a dict (`grep -n "return {" tools/*/*.py`: no hits) — and the loader stringifies anyway
(agent.py:266). `None` is never allowed through: `_skillfile.write` returns `None` on success and its callers translate it (`create_skill.py:22-25`). The string travels
as `{"role": "tool", "tool_call_id": ..., "name": ..., "content": result}` (agent.py:304), in the order the model asked (agent.py:300-304), after all parallel calls are
joined (agent.py:298-299). Above `RESULT_TO_FILE` = 8,000 characters (config.py:31) the result becomes `results/NNNNNN-<tool>.txt` plus a preview of the first 40 lines
(at most 3,000 characters) and the last 20 (agent.py:99-108, 273-281) — except `WHOLE_RESULTS`: `load_skill`, `read_memory`, `read_result`, `search_result`
(agent.py:94). Two "empty" conventions to recognise: `"(no output)"` (sandbox.py:388) and `"(memory is empty)"` (read_memory.py:5).

**Error-text conventions.** All of these arrive as ordinary tool results; none raises to the user.

| Prefix | Written by | Example | Code |
|---|---|---|---|
| `error: ` | the agent loop, for any exception (also the unknown-tool case) | `error: you have no tool called 'open_sandbox'. yours: calculate, load_skill, ...` | agent.py:265, 268 |
| `error: ` | tools, deliberately, when a command or expression failed | `error: ZeroDivisionError: division by zero`, `error: stopped after 600 seconds` | calculate.py:19, sandbox.py:383,385 |
| `not saved: ` | memory and skill writes; nothing changed on disk | `not saved: call read_memory first. write_memory replaces the whole file` | write_memory.py:6,8,11; edit_skill.py:20,22; create_skill.py:7 |
| `not deleted: ` | delete_skill, when the skills lock is busy | `not deleted: another instance is changing a skill right now. try again` | delete_skill.py:8 |
| `not allowed: ` | delegate limits | `not allowed: agents at depth 3 may not create subagents. do the task yourself` | agent.py:454, 482 |
| `no ... called 'x'` | every lookup by name, always followed by what does exist | `no skill called 'deploy'. yours: memory, notebook` | load_skill.py:5; sandbox.py:341,418,491; agent.py:459,502 |
| `invalid ...` | name and expression validation | `invalid project name: letters, digits, - _ . only, at most 60 characters, e.g. sales-2026` | calculate.py:11; _skillfile.py:17; sandbox.py:245-249 |
| `(exit code N)` | suffix on failed sandbox commands | `ls: cannot access '/nope': No such file or directory\n(exit code 2)` | sandbox.py:387 |

**Tool names per agent type** (each list is what ends up in `Agent.tool_names`, agent.py:154, and therefore in `self.tools` sent to the model, agent.py:321):

- **Main agent** — `tools="all"`, `skills="all"`, `memory=True` (main.py:30), depth 1, so it gets all 31 tools the loader found (agent.py:149-153): the 19 in this chapter
  plus `nb_create`, `nb_open`, `nb_close`, `nb_add`, `nb_edit`, `nb_run`, `nb_remove`, `nb_show`, `nb_rerun`, `read_result`, `search_result`, `copy_result`. It is also the
  only agent with `MEMORY.md` in its system prompt (agent.py:181-183).
- **Any agent with at least one skill** — `load_skill` is added even if not listed (agent.py:152).
- **One-off subagent** (no template, instructions only) — `DEFAULT_SUBAGENT_TOOLS` (agent.py:466; config.py:43-44): `calculate`, `load_skill`, `sandbox_shell`,
  `delegate`, `tell`, `read_result`, `search_result`, `copy_result`.
- **Template subagent** — the template's `tools:` line (agent.py:461). `worker`: `calculate`, `sandbox_shell`, `load_skill`, `delegate`, `tell`, `read_result`,
  `search_result`, `copy_result` (Templates/worker.md:4). `coder`: the same without `calculate` (Templates/coder.md:4).
- **Every subagent, whatever the template says** — minus `MAIN_ONLY_TOOLS` (agent.py:471-472; config.py:39-42): `read_memory`, `write_memory`, `open_sandbox`,
  `close_sandbox`, `check_sandbox`, `check_projects`, `mount_project`, `unmount_project`, `create_project`, `delete_project`, `rename_project`, `create_skill`,
  `edit_skill`, `delete_skill`. Dropped silently, no error.
- **At depth 3** (`MAX_DEPTH`, config.py:38) — minus `delegate` and `tell` (agent.py:150), and `Agent.delegate` refuses anyway (agent.py:453-454).
- **Every agent** — `sandbox_shell` (it is in neither `MAIN_ONLY_TOOLS` nor depth-gated; config.py:39-44) and `calculate`, which is in every list above.

**What later chapters can lean on.** The registry contract is just `TOOL` + `run` (agent.py:44-48), so any new tool file appears everywhere automatically and the only
startup failure mode is a duplicate name (agent.py:45-46). Subagents are `Agent` objects that share the process, the tool registry and the sandbox globals
(sandbox.py:34-36); only their *tool list*, instructions, folder and depth differ (agent.py:490). The `/sandbox` commands bypass these tools and call `sandbox.py`
directly (sandbox.py:580), which is why the user can do things the agent cannot, like switching the network on (sandbox.py:117-130).

**Unclear from the code, or worth a second look.** (1) `delete_project` refuses to delete a symlink (sandbox.py:493-494) but `projects()`, `check_project` and
`mount_project` do not test `islink`, so a link the user placed in `Shared/` would be listed and mountable — whether that is intended is unclear from the code.
(2) Nothing validates that a `load_skill` result was actually followed; the harness only supplies the text. (3) `create_skill`, `edit_skill`, `delete_skill` share one
lock name, `skills` (create_skill.py:6), so a slow filesystem write blocks all three across instances for up to 5 s (locks.py:78-86) — by design, but it is the one
place where unrelated skills serialise. (4) `write_memory` reports the length of the text the model *sent* (write_memory.py:18), which can differ from the file on disk
by a newline (config.py:83).
