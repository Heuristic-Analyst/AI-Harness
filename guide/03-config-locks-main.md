# 03 — config.py, locks.py, main.py: settings, "in use" signs, and the chat loop

**In this chapter:** (each section then goes function by function, or tool by tool)
- A.1 What it is, and why one file
- A.2 The top: `HERE` and `sys.path`
- A.3 Model (`config.py:12-15`)
- A.4 Terminal output (`config.py:17-21`)
- A.5 Conversation size (`config.py:23-34`)
- A.6 Subagents (`config.py:36-44`)
- A.7 Sandbox (`config.py:46-50`)
- A.8 Folders and files (`config.py:52-66`)
- A.9 `INSTANCE` (`config.py:69-71`)
- A.10 Side effects at import time
- A.11 The functions
- B.1 The core idea
- B.2 The two globals — `locks.py:22-23`
- B.3 The functions, in file order
- B.4 Real output: two processes contending
- B.5 Which locks exist in practice
- B.6 Gotchas, collected
- C.1 Startup order: from `python main.py` to the first `>>>`
- C.2 The helper functions, in file order
- C.3 Every command
- C.4 The main loop, line by line
- C.5 Shutdown order, and why it matters
- C.6 Example terminal output
- C.7 Surprising or easy-to-miss things

---

Three small files, three jobs. **`config.py`** (173 lines) holds every setting and folder path in one place, plus a few tiny helpers everybody uses. **`locks.py`** (151 lines)
provides "in use" signs, so you can run `main.py` several times at once without two copies overwriting each other's conversation, memory, skills or notebook. **`main.py`** (225
lines) is the front door: `python main.py` starts here, builds the main agent and runs the chat loop.

Everything later in the guide leans on the names defined here. A reference like `config.py:24` means line 24 of that file.

---

# Part A — config.py

## A.1 What it is, and why one file

`config.py` is the single place for settings. Every other module starts with `from config import *` (`agent.py:22`, `sandbox.py:25`, `locks.py:15`, `main.py:22`), so every name
in config.py is available everywhere: `MODEL`, `read_text`, `SKILLS`, `LOCKS_DIR`. Three reasons: "which model am I using?" has one answer; move `Conversations/` and you edit
one line (`config.py:64`) while every reader follows — the comment at `config.py:52` says *"want to rename something? change it here, nowhere else"*; and since config imports
nothing from the project, it breaks the import web between `locks.py` (needs `LOCKS_DIR`), `sandbox.py` (needs `SHARED_DIR`) and the tools (need `SKILLS`).

The cost: at `agent.py:319` you cannot see where `MODEL` came from without remembering this file. One obvious source, less explicitness at the use site — that is the trade.

## A.2 The top: `HERE` and `sys.path`

`HERE = os.path.dirname(os.path.abspath(__file__))` (`config.py:8`) is the project folder. `config.py:9-10` then put it at the front of Python's search path, unless it is
already there — because tools are not imported as packages: `agent.py:40-43` loads each tool **file** by path with `importlib`, so that file's `import sandbox` or
`from config import *` has nothing to resolve against. Adding `HERE` makes those imports work from any starting folder and any depth inside
`tools/`. The `if` prevents duplicates; position 0 means "this project wins over a same-named module elsewhere".

## A.3 Model (`config.py:12-15`)

`MODEL = "deepseek/deepseek-flash"` (`:13`) is read at `agent.py:319` and `agent.py:387` (the two `litellm.completion` calls — this is the model that answers), at
`agent.py:344` and `agent.py:423` (`litellm.token_counter`, the estimate that drives checkpoints) and printed at `main.py:167`. Editing it changes the model, the token counting
**and** which API key is looked for (A.10). `STREAM = True` (`:14`) means piece-by-piece replies: passed at `agent.py:322` (`stream=`), and at `agent.py:247,251,255` the reply
is unpacked differently — streaming chunks carry a `delta` ("what's new"), a non-streamed one carries `message` ("everything"). `False` feels frozen until the whole answer
lands. `EFFORT = "high"` (`:15`) is thinking depth, passed as `reasoning_effort=` at `agent.py:323,387`; the comment warns that models accept `low/medium/high` except DeepSeek,
which wants `low/high/max` — and litellm is told to drop unsupported parameters (`agent.py:25`), so a wrong value may be silently ignored.

## A.4 Terminal output (`config.py:17-21`)

These control only **your screen**; transcripts and logs always get everything (`agent.py:236`, `agent.py:287`). `PRINT_THINKING = False` (`agent.py:236`: `if kind ==
"THINKING" and not PRINT_THINKING and not self.log`) hides the reasoning blocks — `True` shows them, a lot of scrolling on long tasks. `PRINT_TOOLS = True` (`agent.py:287`,
`shows()`) hides `TOOL CALL:` blocks and results when `False`, leaving only prose — much harder to debug. `PRINT_SUBAGENT_TALK = False` is the same line: `self.log or
(PRINT_TOOLS and (PRINT_SUBAGENT_TALK or not talk))`, where `talk` is true for `delegate` and `tell`, so the agent↔subagent chat stays hidden while `[name started -> …]`
(`agent.py:494`) and the `[reported DONE]` lines still print.

## A.5 Conversation size (`config.py:23-34`)

The comment at `:23` is the key idea: nothing is summarised by the harness — the agent writes its own checkpoints.

- `CONTEXT_LIMIT = 500_000` (`:24`) — token budget per main agent. Used at `agent.py:353` (`CHECKPOINT_AT * CONTEXT_LIMIT`), `agent.py:363` (`EMERGENCY_AT * CONTEXT_LIMIT`) and
  `agent.py:423` (`< 0.2 * CONTEXT_LIMIT`). Above the model's real limit, requests fail.
- `CHECKPOINT_AT = 0.60` (`:25`) — after a finished task, above 60% the agent writes a checkpoint and its context becomes the system prompt (with the checkpoint) plus the last
  `KEEP_TASKS` tasks. Lower = more frequent checkpoints.
- `EMERGENCY_AT = 0.80` (`:27`) — mid-task: above 80%, old tool results first become pointers to their files; still above, the agent writes its checkpoint immediately and carries
  on.
- `KEEP_TASKS = 1` (`:29`) — how many recent tasks stay word-for-word after a checkpoint (`agent.py:413`). One task = one user message to the next. `0` saves tokens and loses
  continuity.
- `RESULT_TO_FILE = 8_000` (`:31`) — a tool result longer than this goes to `Conversations/<name>/results/000042-name.txt` and the model gets a head+tail preview
  (`agent.py:269`).
- `KEEP_RESULTS = 3` (`:33`) — in an emergency the newest this-many results stay verbatim (`agent.py:441-442`).
- `REPORT_LIMIT = 8_000` (`:34`) — not enforced by truncation: it is spliced into the subagent rules at `agent.py:59` ("Keep the report under 8,000 characters…"), so it changes
  the instruction, not the machinery.

## A.6 Subagents (`config.py:36-44`)

`MAX_CHILDREN = 5` (`:37`) limits live subagents per agent, enforced at `agent.py:481-482` with the tool error "not allowed: you already have 5 subagents…" and quoted in the
`delegate` description (`tools/subagents/delegate.py:15`). `MAX_DEPTH = 3` (`:38`): you are depth 1; `agent.py:453` refuses `delegate` at the deepest level and `agent.py:150`
does not even **give** `delegate`/`tell` to depth-3 agents, so they cannot see the tool. `MAIN_ONLY_TOOLS` (`:39-42`) lists 14 tools a subagent never gets, whatever a template
says — `read_memory`, `write_memory`, `open_sandbox`, `close_sandbox`, `check_sandbox`, `check_projects`, `mount_project`, `unmount_project`, `create_project`,
`delete_project`, `rename_project`, `create_skill`, `edit_skill`, `delete_skill` — enforced at `agent.py:471`; the reason in the comment is that a subagent works inside its
parent's sandbox and only the main agent may touch memory and skills. `DEFAULT_SUBAGENT_TOOLS` (`:43-44`) gives a template-less subagent eight tools (`calculate`, `load_skill`,
`sandbox_shell`, `delegate`, `tell`, `read_result`, `search_result`, `copy_result`), used at `agent.py:466`.

## A.7 Sandbox (`config.py:46-50`)

`CONTAINER_CMD = "podman"` (`:47`) — every call goes through one helper, so `"docker"` would swap the whole layer (`sandbox.py:43,45,51,395`). `SANDBOX_MEMORY = "2g"` and
`SANDBOX_CPUS = "2"` (`:48-49`) reach `podman run` at `sandbox.py:162` next to `--pids-limit 512`; they are what stops a runaway script from taking your machine down, and
nothing else reads them. `MAX_TOOL_TIMEOUT = 600` (`:50`) is how long one sandbox command may run — the same for every command, no per-call override: `sandbox.py:375` (the
default), `tools/sandbox/sandbox_shell.py:5,14`, and `tools/notebook/_notebook.py:50` (`MAX_TOOL_TIMEOUT - 30`, so a slow cell stops a little earlier).

## A.8 Folders and files (`config.py:52-66`)

All built with `os.path.join(HERE, …)`, so the project moves as one unit.

| Constant | Line | Value | Read by |
|---|---|---|---|
| `ENV_FILE` | 53 | `.env` | `config.py:127` only |
| `SOUL_FILE` | 54 | `Ego/SOUL.md` | `main.py:29` |
| `MEMORY_FILE` | 55 | `Ego/MEMORY.md` | `agent.py:183`, `tools/memory/read_memory.py:4`, `write_memory.py:10,13` |
| `SKILLS_DIR` | 56 | `Skills/` | `config.py:139` (`load_skills`) |
| `LEARNED_SKILLS_DIR` | 57 | `Skills/Learned/` | `config.py:139`, `tools/skills/_skillfile.py:21,22,30` |
| `TEMPLATES_DIR` | 59 | `Templates/` | `config.py:163-166` |
| `TOOLS_DIR` | 60 | `tools/` | `agent.py:34` (the `os.walk` that loads every tool) |
| `SANDBOXES_DIR` | 61 | `Sandboxes/` | `sandbox.py:56,57,58,69,137,550,567` |
| `SHARED_DIR` | 62 | `Shared/` | `sandbox.py:73,150,157,163,168,…`, `tools/results/copy_result.py:4,26` |
| `CONVERSATIONS_DIR` | 64 | `Conversations/` | `main.py:33,36,102-104` |
| `LOCKS_DIR` | 66 | `Locks/` | `locks.py:27,66,143` |

Two carry a security rule in their comment. `SKILLS_DIR` vs `LEARNED_SKILLS_DIR`: your skills are read-only to the agent; `Skills/Learned/` is the **only** place it may create,
edit and delete, checked in `tools/skills/_skillfile.py:21-30` with `os.path.realpath`, so a symlink cannot sneak a write out of `Learned/`. `SHARED_DIR` is the **only** folder
of your machine a container sees, and only parts of it: `common/` always, one project folder, and `Notebooks_Engine` read-only (`sandbox.py:163-168`). `.gitignore` backs this
up: `.env`, `Conversations/`, `__pycache__/` and `Locks/` never reach GitHub, and `Shared/*` is ignored except `Shared/Notebooks_Engine/`.

## A.9 `INSTANCE` (`config.py:69-71`)

```python
INSTANCE = str(os.getpid()) + "-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")   # e.g. 48213-20261018165603
```

This run's id: process number plus start time to the second. Both halves are needed — a PID repeats after a restart, a timestamp repeats when two instances start in the same
second, together they are unique for good (exactly what the comment says). Read at `locks.py:135` (is this me?), `locks.py:142` (its instance lock) and
`sandbox.py:112,152,155`, where it becomes part of the container name and the `harness.owner` label — that is how each instance finds its own container and never touches
another's.

## A.10 Side effects at import time

`from config import *` **runs** the module once, top to bottom, and four things happen.

First, `sys.path` gets `HERE` (A.2). Second, `INSTANCE` is computed (A.9), so the id is fixed the moment anything imports config. Third, the `.env` file is scanned
(`config.py:124-129`):

```python
provider = MODEL.split("/")[0].upper()          # config.py:125   "deepseek/…" -> "DEEPSEEK"
API_KEY = None                                  # config.py:126
for line in read_text(ENV_FILE).splitlines():   # config.py:127
    if line.startswith(provider + "_API_KEY="): # config.py:128
        API_KEY = line.split("=", 1)[1].strip().strip('"\'')   # config.py:129
```

`read_text` returns `""` for a missing file, so no `.env` is not a crash — `API_KEY` stays `None` and the first model call fails. The key **name follows `MODEL`**: switch to
`openai/gpt-5` and this looks for `OPENAI_API_KEY=` and ignores `DEEPSEEK_API_KEY=`. And, as the comment stresses, it **never touches the environment** — the key is handed
explicitly to litellm (`agent.py:318,387`), so nothing leaks into child processes; what litellm does with `api_key=None` is litellm's business (unclear from the code).

Fourth, `load_skills()` runs at module level (`config.py:157`), so the skills menu exists before any agent is built. Python caches modules, so this whole block happens exactly
once, even though `agent.py:22` and every tool import config.

## A.11 The functions

**`read_text(path)`** — `config.py:74-78`. A missing file gives `""`, not an exception, and the result is stripped: `if not os.path.isfile(path): return ""`, then `open(...,
encoding="utf-8").read().strip()`. That is why `main.py:29` can write `read_text(SOUL_FILE) or "You are a helpful assistant."` and `agent.py:183` `read_text(MEMORY_FILE) or
"(empty)"`. Real output: `read_text("/tmp/demo/nope.txt")` → `''`. UTF-8 is forced, so a file in another encoding raises; nothing guards that.

**`write_text(path, text)`** — `config.py:80-83`. Makes the parent folder (`os.makedirs(..., exist_ok=True)`), replaces the whole file (`"w"`), and writes `text.strip() + "\n"`
— exactly one trailing newline. Real output: `write_text("/tmp/demo/x/y/z.txt", " hi there ")` created the folders and left `'hi there\n'` — the spaces around the text were stripped too. `"w"` is not atomic: a crash
mid-write leaves half a file, and the locks (Part B) only narrow the window where two instances write the same file. Callers: `main.py:59,69,71`, `agent.py:398`,
`tools/memory/write_memory.py:13`, `tools/skills/_skillfile.py:79`.

**`timestamp()`** — `config.py:85-86`. `now().strftime("%Y%m%d-%H-%M-%S")`: sortable, no colons or spaces (safe on Windows). Real output `20261019-20-18-26`. Used for
conversation names (`main.py:47`) and subagent folders (`agent.py:487`).

**`free_name(folder, name, ending)`** — `config.py:88-96`. `name`, else `name-2`, `name-3`, … — the first name with no file in `folder`, so two things named in the same second
do not overwrite each other.

Real output: with `20261019-20-00-00.lock` and `20261019-20-00-00-2.lock` present → `20261019-20-00-00-3`. Only caller: `agent.py:487`. It is check-then-use and **not**
race-free — which is exactly why `main.py` does the same job differently (`new_name`, C.2).

**`read_front_matter(path)`** — `config.py:98-113`. `SKILL.md` and templates start with a header between two `---` lines, one `key: value` each. Returns `(header_dict,
body_text)`:

```python
header, body, dashes = {}, "", 0
for line in f:
    if line.strip() == "---" and dashes < 2:      # opens or closes the header
        dashes += 1
    elif dashes == 1 and ":" in line:             # inside: "key: value"
        key, value = line.split(":", 1)
        header[key.strip()] = value.strip().strip('"\'')
    elif dashes != 1:                             # outside: the body
        body += line
return header, body.strip()
```

`dashes` counts `---` lines and stops at 2, so a `---` later in the body is plain text. Inside the header a line counts only if it has a colon, and `split(":", 1)` keeps
everything after the **first** colon (so `description: Use when: x` survives). Key and value are stripped and quotes removed, so `name: "x"` equals `name: x`. Everything else
is body, stripped at the end. Real input, `Skills/notebook/SKILL.md`:

```
---
name: notebook
description: Use when you work in a Jupyter notebook with the nb_* tools, for data analysis, step-by-step code, plots, or anything where variables should stay alive between steps.
---
```

Real output (actually run): `{"name": "notebook", "description": "Use when you work in a Jupyter notebook with the nb_* tools, for data analysis, step-by-step code, plots, or
anything where variables should stay alive between steps."}`, with the body starting `# Notebooks\n\nA notebook is a .ipynb file in one of the user's folders …`. Real input
`Templates/worker.md` has four keys and an empty one (`skills:` with nothing after it) and comes back as `{"name": "worker", "description": …, "tools": "calculate,
sandbox_shell, …", "skills": ""}`. Gotchas: no existence check (`open()` raises on a missing path) and no validation — both callers guard first (`config.py:146` with `isfile`,
`config.py:165` by listing only `*.md`); a header line without a colon is silently dropped.

**`names_from(text)`** — `config.py:115-121`. `"a, b, c"` → `["a", "b", "c"]`, empty pieces dropped. Real output: `names_from("a, b ,c,, d")` → `['a','b','c','d']`. Only used
by `templates()` (`:170-171`). Deliberately dumb — commas only, no YAML, no quoting — which is why templates write tools as a plain comma list. `names_from("")` → `[]` ("no
skills").

**The API-key block** — `config.py:124-129`. Not a function but import-time behaviour (A.10); it leaves `provider` (`DEEPSEEK`) and `API_KEY`. `API_KEY` is read at
`agent.py:318,387`; `provider` is read nowhere else in the repo — a leftover, handy when debugging.

**`SKILLS` and `load_skills()`** — `config.py:133-155`. `SKILLS` is the **menu**: name → description, path, `editable`. Only names and one-liners live in memory; the
instructions are read on demand by `load_skill` (`tools/basic/load_skill.py:6`). `load_skills()` walks `(SKILLS_DIR, False)` then `(LEARNED_SKILLS_DIR, True)` — the second
value becomes `editable` — and for each entry: a missing folder is skipped (`:140`); `sorted(os.listdir(...))` keeps the order stable; a plain file is skipped (`:143`, real
example `Skills/Learned/README.md`); a folder without `SKILL.md` is skipped (`:146`, e.g. `Skills/Learned/` itself); `skill = header.get("name", name)` means the name inside
the file wins and the folder name is the fallback; `if skill in fresh: continue` (`:150`) means your skills were read first, so **on a clash yours wins**; and `editable` comes
from the folder, never from what the file claims (`:153`). Then the swap:

```python
SKILLS.clear()          # config.py:154
SKILLS.update(fresh)    # config.py:155
```

Why not `SKILLS = fresh`? Because `from config import *` binds the **object**. `agent.py`, `load_skill.py` and `_skillfile.py` all hold that same dict, and rebinding the name
would leave them on the old one forever; filling it in place gives every holder the new menu with no message passing. Real output on a copy of this repo's `Skills/`:

```python
{"memory":   {"description": "Use when the user asks you to remember, forget or update something, …",
              "path": "…/Skills/memory/SKILL.md",   "editable": False},
 "notebook": {"description": "Use when you work in a Jupyter notebook with the nb_* tools, …",
              "path": "…/Skills/notebook/SKILL.md", "editable": False}}
```

Honest nuance: the comment at `:154` claims the swap is "at once, so an agent starting in another thread right now never sees a half-filled menu". `clear()` and `update()` are
two calls, so a reader landing exactly between them sees fewer skills. The window is microseconds and readers snapshot with `list(SKILLS)` (`agent.py:194`), so it is fine in
practice — but it is not the atomicity the comment claims, and there is no lock around it (the `skills` lock in Part B protects *writers*).

**`templates()`** — `config.py:161-173`. Ready-made subagents, read **fresh on every call** (`:160`), so a `.md` dropped into `Templates/` while the program runs shows up
without a restart — `agent.py:177,179` calls it while building the system prompt. For each `*.md`, `read_front_matter` splits header and body, and it builds
`result[header.get("name", file[:-3])] = {"description": …, "instructions": body, "tools": names_from(...), "skills": names_from(...)}`. Fallbacks: a missing `name:` uses the
file name without `.md`; missing keys become `""`/`[]`. The body becomes the subagent's `instructions` (`agent.py:458-460`); subfolders are ignored. Real output from this repo:
keys `coder` and `worker`, each with description, instructions and a list of eight tools.

---

# Part B — locks.py

## B.1 The core idea

Two instances of `main.py` may want to touch the same thing: one conversation folder, `Ego/MEMORY.md`, a skill file, an open notebook. If both write, one silently destroys the
other's work.

The usual fix is a lock file with "locked" inside plus the rule "delete it when done". Its weakness is deadly: if the program crashes, is killed, or the power goes, nobody
deletes the file. It says "locked" forever, and you either remove it by hand or invent a timeout that guesses whether the holder is dead.

`locks.py` does something smarter, and it is the whole trick.

**A lock is a file in `Locks/`, and holding it means keeping that file open with the operating system's own lock on it** (`fcntl.flock` on Linux/macOS, `msvcrt.locking` on
Windows).

The OS releases that lock **by itself** when the file is closed or the process ends — `/exit`, a crash, a closed terminal, `kill -9`, a power cut: the kernel closes a dead
process's handles for it. So **a forgotten lock cannot exist**. The file may still sit in `Locks/`, but nobody holds the OS lock, and the next instance can tell "a file is
there" from "somebody holds it" — the line `locks.py:6` draws: *"what counts is only that OS lock, never whether a file is there."*

Leftovers are handled by two rules (`locks.py:7-9`): an instance deletes its own lock files when it releases a lock and all of them at exit; a crash skips that, so **at every
start the files nobody holds are deleted**. A file another running instance holds is never touched — holding the OS lock is precisely what stops it from being taken for
deleting. Payoff: `kill -9` mid-task, start again, it just works. No stale-lock chore, ever.

## B.2 The two globals — `locks.py:22-23`

```python
held = {}                  # lock name -> its open file object: what this instance holds
guard = threading.Lock()   # parallel tool calls: one changes `held` at a time
```

`held` maps a lock name (`"conversation-2026…"`) to the **open file** — the object that must stay alive, because closing it drops the OS lock. `guard` exists because tools run
in threads: `agent.py:294-298` starts one thread per tool call, so `memory`, `skills` and `notebook-…` locks are taken and released concurrently. Every change to `held` happens
under `guard`.

## B.3 The functions, in file order

**Windows vs the rest** — `locks.py:17-20`: `import msvcrt` on Windows, `import fcntl` elsewhere, once at import. On Windows `msvcrt.locking` locks a **byte range** from the
current position, which is why every call does `f.seek(0)` first (byte 0 of an empty file).

**`file_of(name)`** — `locks.py:26-27`: `LOCKS_DIR/<name>.lock`. One rule for everybody, which is what makes "the name exists" and "the file exists" the same question.

**`lock_file(f)`** — `locks.py:29-39`: try to put the OS lock on an already-open file, and **return `True`/`False` without ever blocking** (`f.seek(0)`, then
`msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)` or `fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)`; on `OSError` return `False`). `LOCK_EX` = exclusive, one holder.
`LOCK_NB` = non-blocking: a busy lock errors immediately instead of hanging, and that error is caught and turned into `False`. Deliberate — the caller decides to wait
(`wait_take`) or to say "busy"; a blocking call would freeze the program silently.

**`unlock_file(f)`** — `locks.py:41-50`: unlock (`LK_UNLCK` / `LOCK_UN`), then `f.close()`, swallowing `OSError`. Closing alone would drop the lock; the explicit unlock is belt
and braces, and errors are ignored because releasing runs during shutdown and cleanup and must never fail loudly.

**`same_file(f, path)`** — `locks.py:52-59`: the subtle one. Is the open file `f` still the file at `path`? Compares `st_ino` and `st_dev` of `os.stat(path)` with
`os.fstat(f.fileno())`; `False` if the path is gone. The race it defends against: instance A releases `conversation-x`, and `drop` **deletes the file first**; at that instant B
opens `Locks/conversation-x.lock` with `"a+"`, which happily *creates a new* file of the same name (different inode), locks it and believes it owns the lock — while A is still
finishing its release. `same_file` closes the hole: after locking, B asks "is the file I locked the one at that path?"; if A deleted it in between, the answer is no and `take`
retries (`:75-76`). The docstring: *"not if another instance deleted it while we were opening it"*. On Windows `st_ino` is not always meaningful; whether the comparison is
reliable there is **unclear from the code** (the Windows-specific retry in `drop` suggests symptoms were worked around, not the cause).

**`take(name)`** — `locks.py:61-76`: take the lock. **`True` = this instance holds it now (or already did); `False` = another instance has it.** It never waits.

```python
with guard:
    if name in held: return True          # already mine: taking twice is fine
    os.makedirs(LOCKS_DIR, exist_ok=True)
    while True:
        f = open(file_of(name), "a+")     # open, create if missing
        if not lock_file(f): f.close(); return False      # someone else holds it
        if same_file(f, file_of(name)): held[name] = f; return True   # normal case
        unlock_file(f)                    # the holder deleted it while we opened it: try again
```

It is **re-entrant within an instance** (`if name in held`), which is why `rename_conversation` can take the lock of the conversation you are in (`main.py:125`: *"yours, the
current one, is taken already: that's fine"*). Real output: `take('skills')` twice in a row returned `True` both times, with `held` still listing `skills` once. `"a+"` creates
the file — the only place besides `start` that makes files in `Locks/`. The retry loop only spins when another instance is releasing that exact lock at that instant. The whole
body is under `guard`, so two threads of this process cannot race into `held`. "Someone else holds it" looks like: `False`, no exception, no message — printing is the caller's
job.

**`wait_take(name, seconds=5)`** — `locks.py:78-86`: `take`, else time check, else `time.sleep(0.1)`, up to `seconds`. The docstring is precise — *"for locks that are only held
for a moment"*: a skill or memory write, milliseconds, so 5 seconds is huge slack. Not for conversation locks, which are held for a whole session; waiting would freeze your
typing and then say "busy" anyway, which is why `main.py:81-83` uses plain `take`. Real output: with another process holding `conversation-demo`,
`wait_take("conversation-demo", 2)` returned `True` after exactly `2.0 s`, the moment the holder released; with a longer holder it returns `False`.

**`drop(f, name)`** — `locks.py:88-99`: let go of a lock and delete its file — `os.remove` first (errors swallowed), then `unlock_file`, then on Windows a second `os.remove` if
the file is still there. **Delete before unlock**, and the comment at `:91` says why: if you unlocked first, another instance could grab the lock and your `os.remove` would
delete the file out from under it; deleting first makes the name disappear while you still own it. Windows cannot delete an open file, hence the second attempt — if another
instance already opened that path, the delete fails again and the file stays as a leftover for the next `start()`.

**`release(name)`** — `locks.py:101-106`: `with guard: f = held.pop(name, None); if f: drop(f, name)`. `pop(…, None)` makes releasing something you do not hold a **no-op**, and
so does releasing twice — real output confirmed: two `release("skills")` calls left `held` empty and raised nothing. That forgiveness is what makes `finally:
locks.release(...)` (`edit_skill.py:12`, `create_skill.py:12`, `delete_skill.py:13`, `write_memory.py:16`) safe even when the take failed or the body threw.

**`release_all(start)`** — `locks.py:108-112`: release every held lock whose name starts with a prefix. One real use: `sandbox.forget()` (`sandbox.py:185`) calls
`release_all("notebook-")`, because when the container stops its notebook kernels are gone, so their locks must go too. `for name in list(held)` — the copy is essential, since
mutating a dict while iterating raises `RuntimeError`.

**`free(name)`** — `locks.py:114-129`: "is nobody holding this lock right now?" — **and it cleans up while asking**.

The path: `if name in held` → `False` (mine). `open(..., "r")`, `FileNotFoundError` → `True` (no file, free). `lock_file(f)` fails → close, `False` (busy, leave their file
alone). It succeeds and `same_file` holds → `drop` deletes the leftover → `True`; `same_file` fails → `unlock_file` and `True`.

Three outcomes: no file → free; file with the OS lock held → busy, untouched; file with the OS lock free → a leftover, so `drop` deletes it → free. Gotcha: it is a probe **with
a side effect** — calling `free("x")` can delete `Locks/x.lock`. Every caller knows; the name does not say. It opens with `"r"` so a probe never creates the thing it measures.
Callers: `main.py:111`, `locks.py:137,145`.

**`alive(owner)`** — `locks.py:133-137`: `if owner == INSTANCE: return True`, else `return not free("instance-" + owner)`. An instance is alive exactly as long as its instance
lock is held. Real output: `alive('999-20200101000000')` → `False`; `alive(INSTANCE)` → `True`. The only caller is `sandbox.cleanup()` (`sandbox.py:113`), and this is the
payoff of the design: a container left by a crashed instance is removed at the next start because its owner's lock is no longer held. With an "alive" flag in a file, a crash
would leave containers running forever.

**`start()`** — `locks.py:139-145`: `take("instance-" + INSTANCE)` first, then walk `sorted(os.listdir(LOCKS_DIR))` and call `free(file[:-len(".lock")])` on every `.lock`.
Called once, at `main.py:158`. `take` first because it creates `Locks/` (`os.makedirs`, `:66`), so the `listdir` cannot fail, and because an instance must never be swept by its
own cleanup. Held files stay, crash leftovers are deleted, so **every start tidies `Locks/` for free** — no daemon, no timeouts. Real output in a scratch copy: `Locks/` held
`conversation-demo.lock` and `notebook-abc123.lock` (both leftovers of dead processes); after `locks.start()` only `instance-605-20261019201823.lock` remained and `held` was
`['instance-605-20261019201823']`.

**`stop()`** — `locks.py:147-151`: `for name in list(held): release(name)` — give everything back, which deletes the files. Registered with `atexit` at `main.py:159`. After it,
`Locks/` is empty except other instances' files. A crash skips it, and that is fine: the OS drops the locks and the next `start()` removes the files.

## B.4 Real output: two processes contending

`locks.py` is pure Python plus `fcntl`, with no litellm or podman, so this was actually run: `config.py` and `locks.py` were copied to `/tmp/demo/` (so `HERE`, and therefore
`LOCKS_DIR`, point at the scratch folder — the repo was never written to) and small scripts took and probed locks.

**Real output — one holder, one loser, then the hand-over:**

```
holder: take('conversation-demo') -> True | Locks/ now: ['conversation-demo.lock']
second process: take() -> False
second process: free() -> False
wait_take(2s) -> True 2.0 s waited
holder: released | Locks/ now: []
after release: take() -> True
mine held: ['conversation-demo']
```

A takes the lock and the file appears; B's `take` says `False` and `free` says "busy"; B's `wait_take` polls and succeeds the instant A releases; the file is gone; B takes it.

**Real output — a crash leaves a file but no lock, and `start()` sweeps it:**

```
holder: take('notebook-abc123') -> True | Locks/ now: ['conversation-demo.lock', 'notebook-abc123.lock']
--- Locks/ after the crash (the file is a leftover, the OS lock is gone):
conversation-demo.lock
notebook-abc123.lock
free(notebook-abc123) -> True
Locks/ after free(): ['conversation-demo.lock']
after start(): Locks/ = ['instance-605-20261019201823.lock']
instance lock held: ['instance-605-20261019201823']
alive(me): True
```

The whole philosophy on one screen: the file survived the crash, the lock did not, and `free`/`start` deleted the file because **nobody held it**. `conversation-demo.lock` was
a leftover from an earlier short-lived process, and `start()` removed that too.

## B.5 Which locks exist in practice

Grepped across the repo (`locks.take/wait_take/release/free/release_all/alive`, `locks.py` excluded):

| Lock name (`Locks/<name>.lock`) | Who takes it | Protects | What you/the agent sees when busy |
|---|---|---|---|
| `instance-<pid>-<yyyymmddHHMMSS>` | `locks.start()` → `locks.py:142`, called `main.py:158`; released by `locks.stop()` (`atexit`, `main.py:159`) | "this instance is alive"; read by `locks.alive` → `sandbox.cleanup()` (`sandbox.py:113`) to find orphan containers | nothing waits on it; indirectly, a crashed instance's containers are removed at the next start |
| `conversation-<name>` | `main.py:50` (`new_name`), `:81` (`/open`), `:125`/`:127` (`/rename`); released at `:96,129,136,141,180` | all of `Conversations/<name>/`: `state.json`, `log.jsonl`, `checkpoint.md`, results, subagent transcripts | `/open` → `'<name>' is open in another instance. close it there first`; `/rename` → `'<new>' is in use by another instance`; `/list` → ` (open in another instance)`; `/new` never fails, it picks another name |
| `skills` | `wait_take` in `tools/skills/create_skill.py:6`, `edit_skill.py:6`, `delete_skill.py:7`; released in each `finally` | `Skills/Learned/<name>/SKILL.md` — one instance at a time writes, then calls `load_skills()` | tool result: `not saved: another instance is changing a skill right now. try again` (`not deleted: …` for delete) |
| `memory` | `wait_take` at `tools/memory/write_memory.py:7`, released `:16` | `Ego/MEMORY.md` | tool result: `not saved: another instance is saving the memory right now. try again` |
| `notebook-<12 hex of md5(path)>` | `tools/notebook/_notebook.py:37`, only for `create`/`open`; released on `nb_close` (`:44`) or if opening failed (`:43`), and all at once by `sandbox.forget()` → `release_all("notebook-")` (`sandbox.py:185`) | one open notebook: its kernel lives in *this* instance's container, so two instances would overwrite the same `.ipynb` | tool result: `<notebook> is open in another running instance. use another notebook, or try again when it is closed there` |

Two structural notes: every long-lived lock (`conversation-…`, `notebook-…`) uses plain `take` and reports "busy", while every short-lived one (`skills`, `memory`) uses
`wait_take` with its 5-second patience; and paths are hashed where they would make bad file names (`_notebook.py:35`, after `normpath` + `.lower()`, so `B.ipynb` = `b.ipynb` on
macOS/Windows).

## B.6 Gotchas, collected

`take` never waits — all waiting is explicit in `wait_take`, so decide per lock which you want. `free()` deletes things (probe *and* cleaner); nobody here relies on it being
side-effect-free. Releasing an unheld lock is silent: good for `finally`, but a typo in a lock name fails quietly instead of loudly. Locks are per-machine (`Locks/` is
git-ignored), and a network filesystem would undermine `flock` — not handled. A held lock is a held **file handle**, so losing the reference would still keep the lock; `held`
is the only place those handles live. `guard` protects `held`, not the files: two *processes* coordinate only through the OS lock.

---

# Part C — main.py

## C.1 Startup order: from `python main.py` to the first `>>>`

`main.py` has no side effects on import beyond loading config, agent, sandbox and locks (`main.py:19-25`); everything else is inside `if __name__ == "__main__":`
(`main.py:157`), so the helpers can be imported without starting a chat.

1. `import os, json, atexit` (`:19-21`) — `atexit` is the shutdown hook.
2. `from config import *` (`:22`) — runs config.py once: `HERE` into `sys.path`, `INSTANCE`, `.env` scan, `load_skills()` (A.10).
3. `from agent import Agent` (`:23`) — which loads every tool from `tools/` at import time (`agent.py:34-51`), so a broken tool file stops you here.
4. `import sandbox` (`:24`), `import locks` (`:25`) — nothing started yet.
5. `locks.start()` (`:158`) — take `instance-<INSTANCE>`, then sweep `Locks/`.
6. `atexit.register(locks.stop)` (`:159`), then `atexit.register(sandbox.shutdown)` (`:160`). `atexit` runs callbacks in **reverse** order, so `sandbox.shutdown` runs first and
   `locks.stop` last — that is what "runs last (atexit goes backwards)" means, and it matters: `sandbox.shutdown` → `stop` → `forget` → `release_all("notebook-")` needs the lock
   bookkeeping still alive.
7. `sandbox.available()` (`:161`) — runs `podman info`. Missing or not started (macOS/Windows: `podman machine start`) → prints `podman not found: sandbox tools will not work`
   (`:164`) and carries on.
8. `sandbox.cleanup()` (`:162`) — deletes containers of dead instances.
9. `current = new_name()` (`:165`) — a fresh conversation name **with its lock already taken**.
10. `agent = new_main_agent(current)` (`:166`).
11. The banner (`:167-169`): model, tool count, skills, templates, sandboxes, then the conversation name and a `/help` hint.
12. `while True:` (`:172`) — `input("\n>>> ")`: the prompt is `>>> ` after a blank line.

## C.2 The helper functions, in file order

**`new_main_agent(name)`** — `main.py:28-30`: `soul = read_text(SOUL_FILE) or "You are a helpful assistant."`, then `Agent("main", instructions=soul, tools="all", skills="all",
folder=conversation_folder(name), memory=True)`. `SOUL_FILE` is `Ego/SOUL.md`, *who the agent is* — you write it, the agent only reads it, and an empty file falls back to the
one-liner. `tools="all"`/`skills="all"` mean no filtering (depth 1, so it may delegate). `folder=` is where `log.jsonl`, `checkpoint.md`, `results/` and subagents go.
`memory=True` is what makes `agent.py:183` paste `Ego/MEMORY.md` into the system prompt — main agent only. Called at startup (`:166`), on `/new` (`:182`) and inside
`open_conversation` (`:91`).

**`conversation_folder(name)`** — `main.py:32-33`: `Conversations/<name>`. Nothing creates a directory here, so a fresh conversation has no folder until the agent writes
something — which is why `/list` can print `(nothing said yet, not saved)` (`:115`).

**`old_file(name)`** — `main.py:35-36`: `Conversations/<name>.json`, how conversations were saved before folders. Kept so old chats still open (`convert_old`).

**`exists(name)`** — `main.py:38-39`: `os.path.isdir(folder) or os.path.isfile(old_file)` — modern folder or legacy `.json`. Used by `new_name`, `open_conversation` (`:78`) and
`rename_conversation` (`:121,123`).

**`lock_of(name)`** — `main.py:41-42`: `"conversation-" + name`. One place decides the lock name, so `new_name`, `open_conversation`, `list_conversations` and
`rename_conversation` cannot disagree.

**`new_name()`** — `main.py:44-53`: `base = timestamp()`, then `while exists(name) or not locks.take(lock_of(name))` bump to `base-2`, `base-3`, … A name that is (a) not on
disk and (b) **successfully locked**. The lock half is the important one: it is taken *here*, before anything is written, so two instances starting in the same second cannot
both pick `20261019-20-18-26` — the loser's `take` returns `False` and it moves to `-2`. That is why `main.py` has its own version instead of config's `free_name()`, which can
only check, not reserve.

**`save_conversation(agent, name)`** — `main.py:55-59`: writes `Conversations/<name>/state.json` as `{"mode": agent.mode, "messages": agent.messages[1:]}`, `indent=1`,
`ensure_ascii=False`. The system message is dropped because `/open` rebuilds it (`:93`) — memory or the skill menu may have changed since. The file is **replaced every time**
and holds only what the agent carries since its last checkpoint; the full history is `log.jsonl`, append-only via `agent.record` (`agent.py:201-207`). So state.json = "where we
are now", log.jsonl = "everything ever said". With an empty conversation this would write `[]`, and the caller only saves when `len(agent.messages) > 1` (`:218`), so a
conversation where nothing happened never creates a folder.

**`convert_old(name)`** — `main.py:61-73`: one-time migration of a legacy `Conversations/<name>.json` into a folder: load the JSON, `os.makedirs(folder)` (no `exist_ok`:
converting twice is a bug), write `state.json` with `{"mode": …, "messages": …}` (defaults `"ask"` and `[]`), and if the old file had a `summary`, write it to `checkpoint.md`
under `## Earlier conversation (a summary, from before checkpoints existed)`. Finally `os.rename` the old `.json` **into** the folder as `old.json`, so nothing of yours is ever
deleted. Only called from `open_conversation` when the folder is missing (`:84-85`).

**`open_conversation(name, current)`** — `main.py:75-98`: the delicate one; returns a new agent or `None`. It checks `exists(name)` → `no conversation called '<name>'. /list
shows them`; then `locks.take(lock_of(name))` → `'<name>' is open in another instance. close it there first`; then converts a legacy file if needed; then `data = {"mode":
"ask", "messages": []}` unless `state.json` exists, in which case it is loaded. Then `agent = new_main_agent(name)` and `agent.mode = data["mode"]`.

Lines `main.py:93-97` then set `agent.messages` to a freshly built system message plus the saved turns, call `agent.record("opened", …)`, release the old conversation's lock if
you switched, and print `opened <name>: N messages`.

The lock is taken **before** any reading or conversion, so two instances cannot both convert the same legacy file. `build_system()` runs *before* the messages are replaced, so
the prompt reflects **current** memory and skills, not what they were when the chat was saved. `record("opened", …)` writes the first `log.jsonl` line — which is also what
creates the folder for a conversation that only had a name. The old lock is released only if you actually switched. `mode` and `messages` are indexed, not `.get`, so a
hand-edited `state.json` missing a key raises `KeyError`.

**`list_conversations(current)`** — `main.py:100-115`: collects, then prints. A folder counts if it holds `state.json` **or** `log.jsonl` (a half-created folder is not
advertised); a legacy `.json` counts by its name without the extension. Then per name, `mark = " (open in another instance)"` when `name != current and not
locks.free(lock_of(name))` — skipped for the current one, since you hold that lock yourself and it would always look busy. Prints `* <name>` with `*` on the current
conversation, two spaces otherwise; if the current conversation has not been saved yet it is printed anyway with `(nothing said yet, not saved)`. Note `sorted(os.listdir(...))`
plus `YYYYMMDD-HH-MM-SS` names means alphabetical order = chronological order — that is why the timestamp format puts the year first.

**`rename_conversation(old, new, current, agent)`** — `main.py:117-142`: returns the current conversation's name afterwards (it changes if you renamed the one you are in). The
checks, in order, each with its own message: an invalid name (empty, or containing `/` or `\`, or starting with `.`) → `invalid name` — a name becomes a folder name, so this is
the path-traversal guard; `not exists(old)` → `no conversation called '<old>'`; `exists(new)` → `'<new>' exists already` (renaming never overwrites); `not
locks.take(lock_of(old))` → `'<old>' is open in another instance. it can be renamed when it is closed there` (for the current conversation this succeeds at once, take being
re-entrant); and `not locks.take(lock_of(new))` → release the lock just taken on `old` (unless it is yours) and print `'<new>' is in use by another instance`.

Then: if the conversation is a folder, `os.rename` the folder, else `os.rename` the legacy `.json` (a legacy one stays a file until it is opened); release the old lock; print
`renamed <old> -> <new>`; and if you renamed the conversation you are in, `agent.moved(...)` (`agent.py:218-222`) re-points the agent and every live subagent at the new folder and the new
name stays locked for you. Otherwise release the new name — the lock was only borrowed for the rename.

**`HELP`** — `main.py:145-154`: module-level string printed by `/help`, and the authoritative command list (`/new`, `/list`, `/open <name>`, `/rename <old> <new>`, `/mode
ask|auto`, `/sandbox ...`, `/help`, `/exit` or `/quit`) plus "anything else is a message to the agent. ctrl+c also leaves."

## C.3 Every command

The loop compares `words[0]`, the first whitespace-separated token. Anything starting with `/` that is not recognised gets one message; anything without `/` goes to the agent.

| Input | Code | What it does | Files touched | Printed |
|---|---|---|---|---|
| *(empty line)* | `:174-175` | `continue` | — | nothing |
| `/new` | `:178-183` | `agent.close()` (subagents end), release current lock, new name, new agent | `[done]` in the old transcript; new folder only when something is written | `new conversation: 20261019-20-21-04` |
| `/list` | `:184-185` | list conversations, `*` on the current, mark ones open elsewhere | reads `Conversations/`, probes `Locks/` (`free` may delete leftovers) | one line per conversation |
| `/open <name>` | `:186-191` | `open_conversation`; on success close the agent you leave and switch `agent`/`current` | takes the new conversation lock, releases the old; may convert a legacy `.json`; writes an `opened` log line | `opened <name>: N messages`, or one of the two error lines |
| `/open` with wrong word count | falls to `:208` | nothing | — | `unknown command. /help shows the list` |
| `/rename <old> <new>` | `:192-193` | `rename_conversation`; its return value becomes `current` | renames folder or legacy `.json`; takes/releases conversation locks | `renamed <old> -> <new>`, or `invalid name` / `no conversation called '…'` / `'…' exists already` / `… open in another instance …` |
| `/rename` with wrong word count | falls to `:208` | nothing | — | `unknown command. /help shows the list` |
| `/mode` | `:194-201` | print the current mode | — | `mode: ask` |
| `/mode ask` / `/mode auto` | `:195-200` | set `agent.mode`, rebuild the system prompt (the mode text is part of it, `agent.py:184-185`), record it, save if the conversation has content | a `mode` line in `log.jsonl`; rewrites `state.json` | `mode: auto` |
| `/sandbox …` | `:202-203` | hands the rest to `sandbox.command(words[1:])` | podman, `Sandboxes/`, `Shared/` | `/sandbox list\|check\|remove\|rename\|net on\|off\|shell`; bare `/sandbox` prints that help (`sandbox.py:570-576`) |
| `/help` | `:204-205` | print `HELP` | — | the list verbatim |
| `/exit`, `/quit` | `:206-207` | `break` → shutdown code | — | shutdown output, then `bye` |
| any other `/…` | `:208-209` | nothing — a typo'd command is **not** sent to the model | — | `unknown command. /help shows the list` |
| anything else | `:210-219` | refresh skills, refresh system prompt, `agent.ask(text)`, then save | `log.jsonl`, `state.json`, `checkpoint.md`, `results/`, `agents/` | the streaming answer, tool blocks, … |

Three details easy to miss: `/mode fast` does not complain — `words[1] in ("ask","auto")` fails, the `if` is skipped and it just prints the current mode (`:201`); `/mode` saves
only `if len(agent.messages) > 1`, so an empty conversation gets no folder but a later `/open` restores the mode; and `/new` calls `agent.close()` first (`:179`), which writes
`[done]` into the transcript (`agent.py:534-539`) instead of leaving it half-open.

## C.4 The main loop, line by line

```python
try:                                                        # main.py:171
    while True:                                             # :172
        text = input("\n>>> ").strip()                      # :173
        if text == "": continue                             # :174-175
        words = text.split()                                # :176
```

The blank line before the prompt separates answers visually; `.strip()` means a stray space is not a message; an empty line costs nothing, no model call. `words` is for
dispatch, but the **original `text`** goes to the agent, so your formatting survives. The plain-message branch (`:210-219`):

```python
else:
    load_skills()                # skills another instance made or changed meanwhile
    agent.refresh_system()       # rebuild the system prompt; unchanged text stays the same
    try:
        agent.ask(text)
    except Exception as e:
        print("\nerror: " + type(e).__name__ + ": " + str(e))
        print("(what the agent did so far is kept. if it did nothing yet, your message was taken back: just send it again)")
    if len(agent.messages) > 1:
        save_conversation(agent, current)
```

**`load_skills()` before every question** — another instance may have created or deleted a skill while you typed; it re-reads two folders and refills the same dict.
**`agent.refresh_system()` before every question** — `agent.py:196-198` re-picks the skills and rebuilds `messages[0]` from soul + skills + templates + memory + mode. It runs
every time even when nothing changed; if the text is identical the prompt is byte-identical, so provider-side prompt caching still hits ("an unchanged system prompt stays the
same text").

**The error handling.** `agent.ask` can raise for a missing key, the network, a rate limit, a provider rejecting `reasoning_effort`, a missing module (`:216` names
`ModuleNotFoundError: No module named 'mcp'`). Two lines print: `error: <Type>: <message>` and the reassurance. The parenthetical is accurate because of `agent.py:334-338`: if
the **first** model call fails, the question is popped off `messages` and a `question taken back` entry goes into the log — so "just send it again" really works, with no
half-finished turn left behind. If the failure came later, after some tool calls, the work so far stays in context: the other half of the message. **Saving** happens only `if
len(agent.messages) > 1`, i.e. something besides the system message, so an empty conversation leaves no folder and every completed exchange rewrites `state.json`; note the save
sits *after* the error handler, so a partially successful turn is saved too.

`except KeyboardInterrupt:` (`:220-221`) wraps the **whole loop** — ctrl+c is the normal exit — and only does `print()`: a newline so shutdown output does not start on the
prompt line. No "are you sure?", and nothing is lost, because the conversation was saved after the last answer.

## C.5 Shutdown order, and why it matters

1. `agent.close()` (`agent.py:534-539`) closes the subagents first (`close_children`), then writes `[done]` into each transcript and closes it — before the sandbox stops, so
   transcripts finish while their files still exist.
2. `sandbox.shutdown()` (`sandbox.py:400-404`) prints `[sandbox] stopping <name>` if a container runs, then stops it: it is removed by itself (`--rm`), its project folder is free
   again, and `forget()` releases the `notebook-…` locks of kernels that no longer exist. After `agent.close()` is the right order, since tools still finishing may need the
   sandbox.
3. `print("bye")` — the last thing you see.

Then `atexit` runs backwards: `sandbox.shutdown` (already done, `if my_container` is false) and then `locks.stop` (releases what is left, including the instance lock, deleting
its file). Registering both is deliberate insurance, since `atexit` also fires on an uncaught exception or a `sys.exit` elsewhere — and a container left running holds CPU and
memory until the next `cleanup`. One line: **finish writing (agent), stop the machine (sandbox), say bye, drop the remaining signs (locks).**

## C.6 Example terminal output

**example output (reconstructed from the code)** — a normal start, a question, `/exit`:

```
podman not found: sandbox tools will not work
model: deepseek/deepseek-flash | tools: 31 | skills: memory, notebook | templates: coder, worker | sandboxes: python, ubuntu
conversation: 20261019-20-18-26   (/help for commands)

>>> what is 17 * 4?

TOOL CALL:
calculate({"expression": "17 * 4"})
68

>>> /exit
bye
```

Line contents come from `main.py:161-169` (banner, `>>> ` prompt) and `main.py:223-225` (`bye`); `tools: 31` is the number of tool files under `tools/` that do not start with `_` (the main
agent takes `tools="all"`). The `podman not found` line appears when podman is missing or not started (`:163-164`).

**example output (reconstructed from the code)** — two instances, the second tries to open the first one's conversation:

```
>>> /list
* 20261019-20-18-26 (nothing said yet, not saved)
  20261018-09-12-40
  20261017-22-03-11 (open in another instance)

>>> /open 20261017-22-03-11
'20261017-22-03-11' is open in another instance. close it there first

>>> /open 20261018-09-12-40
opened 20261018-09-12-40: 42 messages

>>> /list
  20261019-20-18-26
* 20261018-09-12-40
  20261017-22-03-11 (open in another instance)
```

Shapes from `main.py:113,115,82,97`. The `*` moved to the opened conversation, and the one you left lost both the `*` and the "(nothing said yet, not saved)" note — it has a
folder now, so it is simply listed.

**example output (reconstructed from the code)** — a failing model call, then a retry that works:

```
>>> summarise my notes

error: AuthenticationError: No API key provided for deepseek/deepseek-flash
(what the agent did so far is kept. if it did nothing yet, your message was taken back: just send it again)

>>> summarise my notes
Here are the three points from your notes: ...
```

The two error lines are `main.py:216-217`; the exception text itself comes from litellm, and `type(e).__name__` is exactly what the code prefixes. Because nothing had happened
yet, `agent.ask` took the question back (`agent.py:334-338`), so re-sending does not duplicate your message.

## C.7 Surprising or easy-to-miss things

**Every launch starts a new conversation** (`:165`) — you continue an old one with `/open`, and the previous one stays saved. **The current conversation's lock is taken by
`new_name()` before the folder exists**, so "locked" and "exists" are independent facts, hence `(nothing said yet, not saved)` while the lock is real. **`/open` reloads memory
and skills into the system prompt** but keeps the messages, so the resumed agent may behave differently from the one that wrote them — intended (fresh memory), worth knowing.
**An unknown `/command` never reaches the model**: `/ls` does nothing but print the help hint. **Two files, two jobs**: `state.json` is rewritten wholesale after every turn,
`log.jsonl` is only appended, so if `state.json` is ever corrupted the log still has everything. And **a broken tool file stops you before the banner**, before the instance
lock is taken — and because locks are file-free, a half-start leaves nothing stale behind.
