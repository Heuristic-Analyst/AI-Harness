# 02 — The map: files, processes, folders, and who talks to whom

This is the chapter you keep open while reading the others. It has no explanations of algorithms — just *where things are* and *what runs where*. Every later chapter assumes you know this map.

---

## 2.1 The codebase in numbers

About 3,100 lines of Python in 41 files, and 16 markdown files that are **data** (skills, templates, soul, memory, READMEs). The Python splits into five sizes of thing:

| Layer | File | Lines | What only it does |
|---|---|---|---|
| Program start | `main.py` | 225 | terminal loop, `/commands`, conversations, shutdown |
| The engine | `agent.py` | 539 | the loop, message list, tools dispatch, checkpoints, subagents, result files |
| Settings | `config.py` | 173 | every constant, every path, `.env` key, skills/templates loading, small helpers used everywhere |
| Containers | `sandbox.py` | 616 | podman: build/start/exec/stop, mounts, projects, the `/sandbox` command |
| Concurrency | `locks.py` | 151 | OS-level "in use" signs for conversations, projects, notebooks, memory, skills |
| Tools | `tools/**/*.py` | ~1,100 | 31 tool files + 3 private helpers |
| Notebook engine | `Shared/Notebooks_Engine/` | 574 | `client.py` (messenger, inside container) + `kernel.py` (the real kernel, inside container) |

31 tool files, sorted into folders:

```
tools/basic/      calculate, load_skill
tools/memory/     read_memory, write_memory
tools/skills/     create_skill, edit_skill, delete_skill   (+ _skillfile.py, helper)
tools/subagents/  delegate, tell
tools/sandbox/    check_sandbox, open_sandbox, close_sandbox, sandbox_shell,
                  check_projects, create_project, mount_project, unmount_project,
                  rename_project, delete_project
tools/notebook/   nb_create, nb_open, nb_close, nb_add, nb_edit, nb_remove,
                  nb_rerun, nb_run, nb_show                  (+ _notebook.py, helper)
tools/results/    read_result, search_result, copy_result   (+ _results.py, helper)
```

A file whose name starts with `_` is **not** a tool: the loader skips it, so helpers can sit next to their users and use relative imports (`from . import _notebook`).

## 2.2 Four processes, not one

This surprises almost everyone the first time. When you use the harness, up to four kinds of process are alive at once, and knowing which one you are reading about prevents most confusion:

```
1. main.py (your machine)
   └─ python process, no sandbox needed, holds: message lists, tools dicts, locks
      │
      ├─ (a) podman container "sandbox-<name>-<instance>-<n>"  (rootless)
      │     └─ bash -c "<command>"   ← what sandbox_shell runs; lives ≤600 s
      │
      │     └─ (b) jupyter kernel process (kernel.py)   ← only if a notebook is open
      │           stays alive between cells, keeps variables
      │
      └─ (c) python3 -B client.py <base64>   ← one short-lived messenger per nb_* call,
                started inside the container, delivers one command to (b) and quits
```

- **`main.py` is the only process that talks to the model** (through LiteLLM). No network is needed inside the container for the agent to think.
- **`sandbox_shell` is one `podman exec`**: a fresh `bash` inside the container for each command. Variables in your shell do **not** survive between two `sandbox_shell` calls; files do, only inside `/workspace/...`.
- **A notebook kernel is the only long-lived process inside the container.** That is why notebook variables survive between cells and shell variables do not.
- **`client.py` is a messenger**: the host-side notebook tool starts it with a base64 command; it delivers that one command to the kernel over a socket, prints the JSON/text answer, and exits. It runs inside the container so that it can reach the kernel's socket and write the `.ipynb` in `/workspace`.

Why the split: the *tool* must run where the model is (host), the *code* must run where the data is (container), and the *protocol between them* must survive quotes, `$`, backticks and newlines — hence base64 on the command line and JSON over the socket.

## 2.3 The folders, and who may write them

Everything on the host, relative to the repository:

| Path | Written by | Read by | Survives restart |
|---|---|---|---|
| `Ego/SOUL.md` | you | system prompt (`main.py:29`) | yes |
| `Ego/MEMORY.md` | the agent (`write_memory`) | system prompt of the main agent | yes |
| `Skills/<name>/SKILL.md` | you | `load_skills()` menu, `load_skill` body | yes |
| `Skills/Learned/<name>/SKILL.md` | the agent (`create/edit/delete_skill`) | same | yes |
| `Templates/<name>.md` | you | `templates()`, `delegate` | yes |
| `Sandboxes/<name>/Containerfile` | you | `sandbox.build()` | yes |
| `Conversations/<name>/state.json` | `save_conversation` | `/open` | yes |
| `Conversations/<name>/log.jsonl` | `Agent.record` | you / grep (never read back by code) | yes |
| `Conversations/<name>/checkpoint.md` | `write_checkpoint` | the system prompt after a clear | yes |
| `Conversations/<name>/results/` | `save_result` | `read_result`, `search_result`, `copy_result` | yes |
| `Conversations/<name>/agents/<when>-<id>/` | `delegate` | you; the child agent | yes |
| `Locks/*.lock` | `locks.take` | every instance at startup and on contention | no (swept) |
| `Shared/common/` | you, the agent (through the container) | the container at `/workspace/common` | yes |
| `Shared/<project>/` | you, the agent (through the container) | the container at `/workspace/<project>` | yes |
| `Shared/Notebooks_Engine/` | — (read-only in the container) | the container | yes |
| `.env` | you | `config.py` at import | yes |

Inside the container the world is much smaller — this is the entire mount list (`sandbox.py:150-169`):

| Host path | Container path | Flags | When |
|---|---|---|---|
| `Shared/common/` | `/workspace/common` | `z,noexec` | always |
| `Shared/<project>/` | `/workspace/<project>` | `Z,noexec` + label `harness.project` | only while a project is mounted |
| `Shared/Notebooks_Engine/` | `/workspace/Notebooks_Engine` | `z,ro,noexec` | only if the folder exists |

Nothing else of yours is visible: no home directory, no `/tmp` from the host, no program folder, no podman socket. The container's working folder is `/workspace/common` or `/workspace/<project>`.

## 2.4 The object graph on the host

```
main.py
  └─ agent: Agent            name "main", depth 1, memory=True, tools="all", skills="all"
       ├─ .messages  [ {system}, {user}, {assistant}, {tool}, … ]      ← the only thing the model sees
       ├─ .tools     [ {type:function, function:{…schema…}}, … ]        ← built from TOOLS, filtered
       ├─ .skills    [ "memory", "notebook", … ]                        ← names from config.load_skills()
       ├─ .children  { "worker-1": Agent(depth 2), … }                  ← live subagents only
       ├─ .folder    Conversations/<name>/                              ← log, checkpoint, results, agents
       └─ .lock/.busy  threading locks (ids, one question at a time)
```

Module-level globals that everything shares:

```
config.SKILLS      { name: {description, path, editable} }     loaded at import, reloaded from main.py's loop
config.API_KEY     from .env, per provider
agent.TOOLS        { name: {type, function} }                  the schemas the model sees
agent.FUNCTIONS    { name: run }                               what actually gets called
agent.FOUND_IN     { name: "tools/…/x.py" }                     for duplicate-name errors
```

`Agent`, `TOOLS`, `FUNCTIONS` are per-process; they are rebuilt at startup by walking `tools/`. Nothing is cached to disk.

## 2.5 Startup order (what happens when you type `python main.py`)

1. `config.py` is imported first (by everything): paths are computed, `.env` is read, `load_skills()` fills `SKILLS`.
2. `agent.py` imports: LiteLLM is quieted, then the **tool loader** walks `tools/` and fills `TOOLS`/`FUNCTIONS`. A duplicate tool name kills startup with a clear message.
3. `sandbox.py`, `locks.py` import (no side effects of consequence).
4. `main.py` starts: `locks.start()` registers this instance's own lock (`instance-<pid>-<time>`) and sweeps locks left by dead instances; `atexit` is wired so cleanup happens even on an exception.
5. `main.py` lists conversations; you `/open` one or `/new`.
6. `Agent("main", …)` is built: system prompt (soul + skills menu + template menu + memory), tool list filtered by `MAIN_ONLY_TOOLS`/depth, `results` counter read from existing files.
7. The prompt appears. From then on every line of text is one `agent.ask(...)`.

Shutdown, in this order (it matters): `agent.close()` (close transcripts of subagents still waiting), then `sandbox.shutdown()` (stop this instance's container, free the project), then "bye".

## 2.6 What each file owns (the one-line contract)

- **`config.py`** — *the numbers and the paths.* If you want to change behaviour, you change it here, nowhere else. Everything else reads names like `CONTEXT_LIMIT`, `SHARED_DIR`, `MEMORY_FILE`.
- **`locks.py`** — *exclusivity.* It knows nothing about agents; it only knows names and OS file locks.
- **`sandbox.py`** — *the container's whole life*: image building, mounting, exec, timeouts, projects, and the `/sandbox` subcommand. Its own container and project live in module globals of the process; every *other* container is discovered by asking podman for its labels — `harness.owner` (instance id), `harness.sandbox`, `harness.project`, `harness.shared` (`sandbox.py:86-105`). There is no state file: podman itself is the registry.
- **`agent.py`** — *the model's world*: the message list, tool dispatch, printing, result files, checkpoints, subagents, transcripts.
- **`main.py`** — *your world*: the terminal, conversations on disk, commands, one agent.
- **`tools/*/*.py`** — *capabilities, one file each*: a `TOOL` dict (prompt text) and `run()` (behaviour). They may call into `sandbox`, `locks`, `agent` helpers, but never into each other except through `_`-helpers in their own folder.
- **`Shared/Notebooks_Engine/`** — *the notebook feature's two halves*: `client.py` (messenger, inside the container) and `kernel.py` (the kernel, inside the container). The host-side half is `tools/notebook/_notebook.py`.

## 2.7 The dependency direction

```
main.py ─▶ agent.py ─▶ config.py
   │           │  └──▶ tools/*  (loaded by path, by name)
   │           └────────▶ litellm (the model)
   └─▶ sandbox.py ─▶ podman (via subprocess)
   └─▶ locks.py   ─▶ fcntl / msvcrt

tools/* ─▶ sandbox, locks, config, (sometimes agent globals)
Shared/Notebooks_Engine/client.py ─▶ kernel.py   (socket, JSON)
```

No cycles except the deliberate one: `agent.py` loads tool modules, and tool modules sometimes import `sandbox` and `config` — never `agent` itself (they receive the agent object as their first argument, `run(agent, **args)`).

## 2.8 Where to look for what

| You want to understand… | Read |
|---|---|
| settings, paths, `.env`, skill/template discovery | `config.py` (ch. 03) |
| two instances not colliding | `locks.py` (ch. 03) |
| terminal commands, conversations on disk, shutdown | `main.py` (ch. 03) |
| the loop, checkpoints, subagents, result files, printing | `agent.py` (ch. 04) |
| containers, mounts, timeouts, projects | `sandbox.py` (ch. 05) |
| the tool protocol, and 19 of the 31 tools | `tools/basic`, `memory`, `skills`, `subagents`, `sandbox` (ch. 06) |
| long results, `read_result`, notebooks and the kernel protocol | `tools/results`, `tools/notebook`, `Shared/Notebooks_Engine` (ch. 07) |
| how all the data shapes interlock, with traces | ch. 08 |
