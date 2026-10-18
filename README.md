# AI Harness

A small, readable multi-agent assistant that runs in your terminal. It talks to any LLM through [LiteLLM](https://github.com/BerriAI/litellm), can split work across subagents that run in parallel, remembers things between conversations, and runs code only inside throwaway [Podman](https://podman.io) containers, never on your machine.

The whole thing is a few thousand lines of commented Python. It's meant to be read, changed and extended.

## Features

- **Any model.** One line in `config.py` picks the model: DeepSeek, Anthropic, OpenAI, a local Ollama model, or anything else LiteLLM supports.
- **Subagents.** The agent can `delegate` tasks to subagents, either from ready-made templates or with one-off instructions. Several delegations in one reply run in parallel. Subagents report back with `DONE`, `BLOCKED` or `QUESTION`, and a parent can answer a question with `tell` so the subagent picks up where it stopped.
- **Sandboxes.** Code, installs and file work happen in rootless Podman containers with no network by default, and memory, CPU and process limits. The agent picks and opens the sandbox it needs itself. Each running `main.py` gets its own container, and its Containerfile is all there is: nothing is ever saved inside.
- **Projects.** The agent works in folders on your machine: `Shared/common/`, which every running instance shares, and one project folder `Shared/<project>/` that it mounts, which no other instance can mount at the same time.
- **Skills.** Step-by-step instructions in Markdown that the agent loads only when it needs them, so the system prompt stays small. The agent can also write its own skills, in a folder of their own, and improve or delete them later. Yours it can never change.
- **Memory.** A plain `MEMORY.md` file that the agent reads at the start of every conversation and edits itself.
- **Persistent conversations.** Every conversation has its own folder and can be listed, reopened and renamed. A log keeps every word, and only ever grows.
- **Several at once.** You can run `main.py` more than once at the same time. Each instance has its own sandbox, and locks make sure two instances never work in the same conversation, project or notebook, or save the memory or a skill over each other.
- **Checkpoints, not summaries.** When the context gets full, the agent writes down where it stands in a fixed structure, and goes on with a fresh context. Long tool results go into files the agent can read, search and copy into its sandbox. Nothing is ever lost.
- **Project runs.** A long project (hours, days, any size) runs in the background as a graph of nodes: each node is one task with checkable done-when points and a token budget, and splits into children when it is too big. A scheduler without a model starts the shifts, parents check their children's results, and everything lives in files, so a run survives closing the chat and even a crash. You can answer its questions, ask for changes, pause it or give it more budget at any time.
- **Jupyter notebooks.** The agent creates, edits and runs real `.ipynb` notebooks inside the sandbox. Variables stay alive between cells, like in Jupyter, and every change is saved to the file right away, so you can open it any time.
- **Two modes.** In `ask` mode the agent may ask you questions. In `auto` mode it makes reasonable assumptions and decides on its own.

## Requirements

- Python 3 (3.10 or newer recommended)
- An API key for your model provider (not needed for local models such as Ollama)
- [Podman](https://podman.io/docs/installation), only if you want sandboxes. Everything else works without it.

## Quick start

```bash
git clone https://github.com/Heuristic-Analyst/AI-Harness.git
cd AI-Harness
pip install -r requirements.txt
```

Create a `.env` file next to `main.py` with the key for your provider. The name is the provider part of the model string in upper case, followed by `_API_KEY`:

```
DEEPSEEK_API_KEY=sk-...
```

On macOS or Windows, start the Podman VM once:

```bash
podman machine start
```

Then run:

```bash
python main.py
```

```
model: deepseek/deepseek-flash | tools: 31 | skills: memory, notebook | templates: coder, worker | sandboxes: python, ubuntu
conversation: 20261015-22-11-04   (/help for commands)

> what is 17% of 2340?
```

## Commands

Anything that doesn't start with `/` is a message to the agent.

| Command | What it does |
|---|---|
| `/new` | Start a new conversation. The current one stays saved. |
| `/list` | Show saved conversations. |
| `/open <name>` | Continue a saved conversation. |
| `/rename <old> <new>` | Rename a saved conversation. |
| `/mode ask\|auto` | `ask`: the agent may ask you questions. `auto`: it decides on its own. `/mode` alone shows the current mode. |
| `/sandbox ...` | Manage sandboxes (see below). |
| `/help` | Show the command list. |
| `/exit`, `/quit` | Leave. This instance's sandbox is stopped. |

### Sandbox commands

| Command | What it does |
|---|---|
| `/sandbox list` | All sandboxes: which one runs here, which run in other instances, which are built. |
| `/sandbox check [name]` | One sandbox in detail with its whole Containerfile, or all of them without a name. |
| `/sandbox remove <name>` | Delete a sandbox: its folder and its image. Only when no instance runs it. |
| `/sandbox rename <old> <new>` | Rename a sandbox, its image included. Only when no instance runs it. |
| `/sandbox net on\|off` | Switch internet for this instance's sandbox (off at every start). |
| `/sandbox shell` | A root shell inside this instance's sandbox, for you. |

Opening and closing a sandbox is the agent's job, and every exit closes it. A new sandbox is a new folder in `Sandboxes/` with a Containerfile inside.

## Project layout

```
.
├── main.py              # start here: the chat loop and the /commands
├── agent.py             # the Agent class: model calls, tool loop, subagents, compaction
├── sandbox.py           # Podman sandboxes: build, run, stop, exec, project folders
├── config.py            # all settings and paths, plus small shared helpers
├── locks.py             # "in use" signs between running instances, released by the operating system
├── requirements.txt
├── .env                 # your API keys (create it yourself, don't commit it)
├── Ego/
│   ├── SOUL.md          # who the main agent is. you write it
│   └── MEMORY.md        # what it remembers. the agent edits this itself
├── Skills/              # one folder per skill. these are yours: the agent can't change them
│   ├── memory/SKILL.md
│   ├── notebook/SKILL.md
│   ├── project-run/SKILL.md   # how the main agent sets up, starts and follows a project run
│   └── Learned/         # skills the agent wrote itself: the only ones it may create, edit and delete (README.md explains)
├── Templates/
│   ├── coder.md         # ready-made subagents: instructions, tools, skills
│   └── worker.md
├── tools/               # one file per tool, sorted into folders by feature
│   ├── basic/           #   calculate, load_skill
│   ├── memory/          #   read_memory, write_memory
│   ├── notebook/        #   nb_create, nb_open, nb_close, nb_add, nb_edit, nb_run, nb_remove, nb_show, nb_rerun
│   ├── results/         #   read_result, search_result, copy_result
│   ├── projects/        #   project runs: start_run, run_status, message_run, pause_run, and their helpers:
│   │   ├── _graph.py    #     the graph of nodes in Shared/<project>/.graph/, and its rules
│   │   ├── _scheduler.py  #   the scheduler, started in the background by start_run
│   │   └── _nodes/      #     the nodes' own tools: create_nodes, write_result, check_result, cancel_node, send_message,
│   │                    #     add_fact, search_facts, node_status. only the scheduler loads them
│   ├── sandbox/         #   sandbox_shell, check_sandbox, open_sandbox, close_sandbox, check_projects, mount_project, unmount_project,
│   │                    #   create_project, delete_project, rename_project
│   ├── skills/          #   create_skill, edit_skill, delete_skill
│   └── subagents/       #   delegate, tell
├── Sandboxes/
│   ├── ubuntu/Containerfile   # one folder per sandbox
│   └── python/Containerfile   # python + numpy, pandas, matplotlib: the one notebooks need
├── Shared/              # the only folder a sandbox sees parts of
│   ├── common/          #   every sandbox of every instance: /workspace/common. created on first use
│   ├── <project>/       #   one project per sandbox, mounted by the agent: /workspace/<project>
│   │   └── .graph/      #   only in a project run: its plan and state (see Project runs). read-only in the sandbox
│   └── Notebooks_Engine/  # kernel.py + client.py: run the notebooks inside the sandbox (mounted read-only)
├── Locks/               # lock files of the running instances. created on first use, cleaned up by itself
└── Conversations/       # your conversations, one folder each, created on first use
    └── <name>/
        ├── state.json      # what the agent carries right now: what /open loads
        ├── log.jsonl       # everything, word for word, only ever appended
        ├── checkpoint.md   # the agent's own notes, from its last checkpoint
        ├── results/        # tool results too long for the context: 000042-sandbox_shell.txt
        └── agents/         # its subagents: one folder each, with the same inside, plus transcript.md
```

## Configuration

Everything lives in `config.py`. The settings you're most likely to change:

| Setting | Default | Meaning |
|---|---|---|
| `MODEL` | `deepseek/deepseek-flash` | Any LiteLLM model string, e.g. `anthropic/...`, `openai/...`, `ollama/llama3`. |
| `STREAM` | `True` | Print the reply as it arrives. |
| `EFFORT` | `high` | Reasoning effort (`low`/`medium`/`high`; DeepSeek uses `low`/`high`/`max`). |
| `PRINT_THINKING` | `False` | Show the model's thinking in the terminal. |
| `PRINT_TOOLS` | `True` | Show tool calls and their results in the terminal. |
| `PRINT_SUBAGENT_TALK` | `False` | Show the messages between the agent and its subagents (`delegate` and `tell`) in the terminal. They're always in the transcripts. |
| `CONTEXT_LIMIT` | `500_000` | Tokens an agent may use at most. Keep it at or below the model's real limit. |
| `CHECKPOINT_AT` | `0.60` | After a task, above this share of `CONTEXT_LIMIT`: checkpoint, then a fresh context. |
| `EMERGENCY_AT` | `0.80` | In the middle of a task, above this share: older results become pointers, then an emergency checkpoint if needed. |
| `KEEP_TASKS` | `1` | How many recent tasks stay word for word after a checkpoint. |
| `RESULT_TO_FILE` | `8_000` | Tool results longer than this (characters) go into a file; the model gets a preview. |
| `KEEP_RESULTS` | `3` | In an emergency, the newest tool results stay in the context as they are. |
| `REPORT_LIMIT` | `8_000` | A subagent's report should stay below this many characters. |
| `MAX_CHILDREN` | `5` | Live subagents one agent may have at once. |
| `MAX_DEPTH` | `3` | How deep the agent tree may go. You talk to depth 1. |
| `RUN_PARALLEL` | `3` | Project runs: shifts that run at the same time. |
| `NODE_CHILDREN` / `NODE_DEPTH` | `5` / `8` | Project runs: children one node may have, and how deep the graph may go. |
| `NODE_MIN_BUDGET` | `20_000` | Project runs: the smallest budget a node may get. |
| `BUDGET_WARNING` / `BUDGET_RESERVE` | `0.80` / `0.10` | Project runs: a node is warned at 80% of its budget; 10% is kept back for its wrap-up. |
| `IDLE_SHIFTS` | `2` | Project runs: shifts in a row without progress before a node is blocked. |
| `SANDBOX_MEMORY` / `SANDBOX_CPUS` | `2g` / `2` | Resource limits for a running sandbox. |
| `MAX_TOOL_TIMEOUT` | `600` | Seconds a sandbox command may run before it is stopped. |

The API key is read from `.env` only. It never touches your environment variables.

## How it works

### The agent loop

The main agent and every subagent are the same `Agent` class. Each one keeps its whole conversation in a single list of messages. On every turn it sends the list to the model, prints the reply, runs any tool calls (each in its own thread) and loops until the model answers without calling a tool.

The system prompt is rebuilt from parts before each of your messages and whenever one of them changes: the soul or template instructions, the subagent rules, the skills menu, the templates menu, the memory, the mode and the agent's checkpoint. An unchanged rebuild gives exactly the same text, so the model's prompt cache stays valid.

### Subagents

The main agent can call `delegate` with a template name or its own instructions. Each subagent:

- starts with an empty context and knows only its instructions and the task it was given
- has its own folder inside its parent's (`agents/<when>-<id>/`): a log, its result files, and `transcript.md`, which you can watch live with `tail -f`
- ends its work with a report that starts with `DONE`, `BLOCKED` or `QUESTION`, stays under `REPORT_LIMIT` characters, points to files for the details, and says where every claim comes from
- reaches its parent with its id and folder in front, so the parent can read the subagent's result files. Never the other way round
- is closed when its parent's task ends, unless it's waiting for an answer to a `QUESTION`

Subagents never get the main-only tools (`read_memory`, `write_memory`, `open_sandbox`, `close_sandbox`, `check_sandbox`, `check_projects`, `mount_project`, `unmount_project`, `create_project`, `delete_project`, `rename_project`, `create_skill`, `edit_skill`, `delete_skill`). They work in their parent's sandbox. Agents at the maximum depth don't get `delegate` or `tell`.

### Sandboxes

Each folder in `Sandboxes/` is one sandbox, defined by its `Containerfile`, and the Containerfile is all there is. Building it gives an image, and running it starts a container that's deleted when it stops, so every start is clean. Nothing is ever saved: the image is built from the Containerfile again at every start. Unchanged steps come from Podman's cache, so that's quick, and a change you make in a Containerfile is in the very next start.

An instance is one running `main.py`. Each instance runs at most one sandbox, in its own container. Several instances can run at the same time, with the same sandbox (one image, a container each) or different ones. The agent picks a sandbox by reading the Containerfiles (`check_sandbox`) and opens and closes it itself. When you exit, its sandbox is stopped.

A running sandbox:

- has its network disconnected right after start (turn it on with `/sandbox net on`)
- runs with `no-new-privileges`, a 512-process limit and the memory and CPU limits from `config.py`
- sees only these folders of your machine, all mounted `noexec`, so files there have to be run through an interpreter (`python x.py`, `bash x.sh`):
  - `Shared/common/` at `/workspace/common`: always there, in every instance, so instances can share files. It can't be unmounted.
  - `Shared/<project>/` at `/workspace/<project>`: one project folder at most, mounted by the agent (`mount_project`). While one instance has it, no other instance can mount it. The agent can also create, rename and delete project folders, but never one that a sandbox has mounted.
  - `Shared/Notebooks_Engine/` at `/workspace/Notebooks_Engine`, read-only: the notebook engine. It can't be changed from inside.
  - `Shared/<project>/.graph/`, read-only, only if the project has a project run: its plan and state, for the work to read.

`common` and `Notebooks_Engine` are never treated as projects: no tool creates, mounts, renames or deletes them.

Podman can't add or remove a folder of a running container, so mounting or unmounting a project restarts the sandbox: what was installed or started inside is gone. The agent can avoid that by giving the project to `open_sandbox` right away. A project is free again as soon as its instance closes the sandbox or ends, also after a crash: every container carries labels (who started it, which sandbox, which project), and the container of a crashed instance is removed the next time any instance looks.

The labels are also how an instance finds its own container, so containers you start yourself are never touched.

### Memory

`Ego/MEMORY.md` is included in the main agent's system prompt. When you ask it to remember or forget something, it loads the `memory` skill, reads the file, and writes back the whole updated file.

### Learned skills

The agent can write its own skills with `create_skill`, improve them with `edit_skill` and remove them with `delete_skill`. These tools only ever touch `Skills/Learned/<name>/SKILL.md`: your skills one level up are out of reach, whatever the agent tries.

- every learned skill gets `editable: yes` in its header and a note at the top of its text, both written by the tool
- in the agent's skill list they are tagged `[editable]`, so it knows which skills it may change before loading one
- what counts is the folder, not the header: a skill elsewhere that says `editable: yes` is still yours and stays locked
- a new or changed skill is usable at once, no restart needed. A learned skill with the same name as one of yours is ignored
- only the main agent gets these tools, like the memory tools

Want to keep a learned skill for good? Move its folder from `Skills/Learned/` up into `Skills/`: from then on it is yours, and the agent can't change it anymore. The folder's name is `LEARNED_SKILLS_DIR` in `config.py`.

### Notebooks

The `nb_*` tools give the agent Jupyter-style notebooks, in `Shared/common/` or the mounted project. The tools in `tools/notebook/` only pass commands on: everything runs inside the sandbox, through the engine in `Shared/Notebooks_Engine/` (inside the sandbox: `/workspace/Notebooks_Engine/`, read-only).

- `kernel.py` is the kernel of one open notebook. It keeps running, holds the variables and the cells, and writes the whole `.ipynb` file after every change.
- `client.py` runs once per tool call. It starts a kernel (`nb_create`, `nb_open`), stops one (`nb_close`), or hands the command to the running one.

Every answer ends with an overview of all cells: id, state (`ran [3]`, `not run`, `EDITED since, output is stale`, `error`) and first line, so the agent always knows where it is. The `notebook` skill tells it how to work: a plan cell at the top, one step per cell, fix cells in place, `nb_rerun` at the end. If you edit an open notebook yourself, the kernel notices and keeps your changes. Notebooks need `python3` in the sandbox, e.g. the `python` sandbox. Moving the engine? Change `ENGINE` in `sandbox.py`.

### Several instances at once

Every `main.py` you start is an instance with an id of its own (its process number plus its start time). Instances can run side by side, and they keep out of each other's way with locks:

- **Conversations:** an open conversation is locked. `/open` refuses one that's open in another instance, `/rename` too, and `/list` marks them. A new conversation's name is locked right away, so two instances started in the same second never get the same one.
- **Projects:** a project is taken while a sandbox of a running instance has it mounted.
- **Notebooks:** an open notebook is locked, also in `common/`, until `nb_close` or the sandbox stops.
- **Memory and skills:** they aren't locked while the agent thinks. Instead, `write_memory` and `edit_skill` only save if the file is still as the agent last read it. Otherwise they refuse, and the agent reads again and merges. Each instance reloads the skill list before your every message, so new skills show up everywhere.

A lock is a file in `Locks/` that the instance keeps open, with a lock from the operating system on it. The operating system takes that lock away by itself when the instance ends, however it ends: `/exit`, a crash, a closed terminal, a killed process, a power cut. So a lock is never left behind. Each instance deletes its own lock files when it gives a lock back, and all of them when it exits; it never touches another instance's files. After a crash its files stay, without the lock, so every start deletes the files nobody holds. Files that running instances hold are never touched.

### Conversation folders and the log

Every conversation is a folder, `Conversations/<name>/` (see the layout above). Two files in it matter most:

- **`log.jsonl`** keeps everything, one line each: every message, every tool call and result, the system prompt whenever its text changed, mode changes, checkpoints, and when the context was cleared. It is only ever appended to, never rewritten, so nothing that happened is ever lost.
- **`state.json`** is what the agent carries right now, rewritten after every message. `/open` loads it, together with `checkpoint.md`.

Conversations saved the old way, as `Conversations/<name>.json`, still show up in `/list`. The first `/open` turns one into a folder: its messages go into `state.json`, its summary into `checkpoint.md`, and the old file is kept there as `old.json`.

### Long tool results

A tool result longer than `RESULT_TO_FILE` characters goes into the agent's `results/` folder as `000042-sandbox_shell.txt`. The agent gets a preview: where the file is, how big, the first 40 and the last 20 lines. With `read_result` it reads any range of lines, with `search_result` it finds lines like `grep`, and with `copy_result` it copies the file into `common/` (or the mounted project) to work on it with code in the sandbox. A file bigger than the whole context is no problem: the agent only ever loads the slice it needs.

### Checkpoints

Nothing is summarized. When the context gets full, the agent writes its **checkpoint** itself, while it still knows everything, in fixed sections: goal, decisions, facts (each with its source), done, open (with the next step), files, questions. It replaces `checkpoint.md`; every earlier one is still in the log.

- **After a task**, above `CHECKPOINT_AT` (60%): the agent writes its checkpoint, and its context is cleared down to the system prompt, which holds the checkpoint, and the last `KEEP_TASKS` tasks. If those are big themselves, only each task's question and final answer are kept.
- **In the middle of a task**, above `EMERGENCY_AT` (80%): first, every tool result except the newest `KEEP_RESULTS` becomes a short pointer to its file. That usually frees most of the room, and nothing is lost. Only if that isn't enough does the agent write an emergency checkpoint, saying exactly where it is in the task. Its context is cleared, and it goes on with the same task from there.

Subagents only use the emergency path: their whole life is one task.

### Project runs

For work far bigger than one context or one evening: a website, a data pipeline, a long research. You agree with the agent on the project folder, the goal, **done when** (3 to 6 points someone can check), a token budget and the sandbox, and optionally the first level of the plan. The `project-run` skill tells the agent how. Then `start_run` starts the scheduler (`tools/projects/_scheduler.py`) in the background, and you can close the chat.

The run is a graph of **nodes** in `Shared/<project>/.graph/`. The root `T1` is the whole goal; its children are `T1.1`, `T1.2`, ...; theirs `T1.1.1`, and so on. Each node has a goal, why it matters, its done-when points, a budget (for itself and everything it gives its children), and `depends_on`: siblings whose results it needs first.

```
.graph/
├── project.json        # goal, done when, budget, sandbox
├── nodes/T1.2.json     # what a node is: goal, why, done_when, budget, depends_on. written once
├── state/T1.2.json     # where it stands: status, spent, given to children, accepted, ...
├── inbox/T1.2/         # messages to it, one numbered file each (inbox/user/: the root's questions to you)
├── knowledge/facts.jsonl  # facts any node found, with their source
├── work/T1/            # the root's folder: checkpoint.md, result.md, transcript.md, log.jsonl, results/
│   └── agents/T1.2/    #   a child's folder, inside its parent's
├── run.log             # what the scheduler did, one line each
└── pause               # only while paused
```

The **scheduler** has no model. Round after round it follows the rules in `tools/projects/_graph.py`: an open node whose dependencies are done gets a **shift**, up to `RUN_PARALLEL` at once. A shift is a fresh agent for that node, a subagent with the node rules and the node tools: its briefing (goal, budget, its dependencies' results, its children and their results, new messages) is its first message, and its checkpoint is in its system prompt. In a shift a node does what fits:

- **does the work** itself, in the project folder, if it fits its budget
- **splits** with `create_nodes`, if it is too big: then it ends its shift and waits
- **checks** its children's results against their done-when points, when it is woken: `check_result` accepts one or sends it back with exactly what is missing (and more budget, if needed). Siblings that build on a sent-back result become **stale** and are checked again
- **finishes** with `write_result`: a report that starts with `DONE` or `BLOCKED`, one answer per done-when point, and its final checkpoint. A `DONE` needs every child accepted or cancelled
- **asks** its parent with `send_message`, only when it can't go on with a reasonable assumption. The root's parent is you

A waiting node is woken when a message comes, or when none of its children can go on without it. The run ends when the root is done or blocked, when it waits for your answer, or when you paused it. `run_status` shows where it stands; `message_run` passes on your answer or a change ("also read credit card statements"), and starts the scheduler again: the root decides how, reopening finished parts, adding or cancelling nodes.

The **budget** is checked between model calls. At `BUDGET_WARNING` (80%) the node is told; when it is used up, the shift stops, and with the `BUDGET_RESERVE` kept back for this, the node writes its checkpoint and a `BLOCKED: out of budget` report saying what is done and what it would need. If even that fails, the scheduler writes the report. A node that makes no progress for `IDLE_SHIFTS` shifts, or whose model fails three times in a row, is blocked too: its parent always gets an answer. A run that is out of budget goes on with `message_run` and `extra_budget`.

Everything is in files, written by one tool each, so a crash loses at most the shift that was going on: a node that was working opens again and goes on from its checkpoint. The scheduler is an instance like `main.py`: its own sandbox, with the project mounted, so no one else can mount it while it runs. Inside the sandbox `.graph/` is read-only: only the node tools change it.

## Built-in tools

| Tool | Who gets it | What it does |
|---|---|---|
| `calculate` | all | Evaluates a math expression in a separate, time-limited process. Only digits and math symbols are accepted. |
| `load_skill` | agents with skills | Returns a skill's full instructions. |
| `delegate` | above max depth | Creates a subagent with one task and returns its report. |
| `tell` | above max depth | Sends a follow-up message to a live subagent. |
| `sandbox_shell` | all | Runs a bash command inside this instance's sandbox. |
| `check_sandbox` | main only | Shows every sandbox with its whole Containerfile, and which one runs here. Changes nothing. |
| `open_sandbox` | main only | Starts the sandbox the agent picked, optionally with a project mounted. |
| `close_sandbox` | main only | Stops this instance's sandbox. |
| `check_projects` | main only | Lists the project folders: free, mounted here, or mounted by another instance. |
| `mount_project` / `unmount_project` | main only | Mounts one project folder, or unmounts it. Restarts the sandbox. |
| `create_project` / `delete_project` | main only | Creates a new, empty project folder, or deletes one with everything in it. Never one a sandbox has mounted. |
| `rename_project` | main only | Renames a project folder that no sandbox has mounted. |
| `nb_create` / `nb_open` | main (subagents if given) | Make a new notebook or open an existing one: starts its kernel. |
| `nb_close` | main (subagents if given) | Stops a notebook's kernel. The file stays. |
| `nb_add` / `nb_edit` / `nb_remove` | main (subagents if given) | Add, change or remove a cell, optionally running it right away. |
| `nb_run` | main (subagents if given) | Runs one or more cells in order and returns their output. |
| `nb_show` | main (subagents if given) | The whole notebook: every cell with code and output. |
| `nb_rerun` | main (subagents if given) | Fresh kernel, then every cell from the top. |
| `create_skill` / `edit_skill` / `delete_skill` | main only | Write, rewrite or delete the agent's own skills in `Skills/Learned/`. |
| `read_memory` | main only | Reads `MEMORY.md`. |
| `read_result` / `search_result` | all | Reads a range of lines from a long tool result's file, or finds lines in them. Own files and the subagents' only. |
| `copy_result` | all | Copies a result file into `common/` or the mounted project, any subfolder, to work on it in the sandbox. |
| `write_memory` | main only | Replaces `MEMORY.md`. |
| `start_run` | main only | Sets up a project run (goal, done when, budget, sandbox, optional plan) and starts its scheduler, or lets a paused one go on. |
| `run_status` | main only | Where a run stands: the tree of nodes, the budget used, the root's questions and result, the last log lines. |
| `message_run` | main only | Sends your answer or a change to the root, optionally with more budget, and starts the scheduler again. |
| `pause_run` | main only | Pauses a run after the shifts going on now. |
| `create_nodes` / `cancel_node` | nodes of a run only | Split a node into children, or drop one (optionally replaced by another). |
| `write_result` / `check_result` | nodes of a run only | Finish a node with its report, checkpoint and done-when answers; accept a child's result or send it back. |
| `send_message` | nodes of a run only | A message to the parent or to an own child. |
| `add_fact` / `search_facts` / `node_status` | nodes of a run only | The run's shared facts, and the whole graph with the node's budget. |

## Extending it

### Add a tool

Create `tools/<name>.py` with a `run` function and a `TOOL` description. `run` always receives the calling agent first, then the arguments the model passed. Tools are loaded at startup.

You can sort tools into folders, as deep as you like (`tools/sandbox/sandbox_shell.py`). The folders are only for you: the model sees the `name` in `TOOL`, and templates list tools by that name, so moving a file never breaks anything. Files and folders starting with `_` are skipped (`_helpers.py`, `_drafts/`), and two tools with the same name stop the program at startup with a message saying which files.

```python
# tools/word_count.py
def run(agent, text):
    return str(len(text.split()))

TOOL = {
    "name": "word_count",
    "description": "Count the words in a text.",
    "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
}
```

### Add a skill

Create `Skills/<name>/SKILL.md`. Only the `name` and `description` go into the system prompt. The body is loaded when the agent calls `load_skill`. Skills are read at startup. Keep `: ` (a colon and a space) out of the `description` line: GitHub reads the header as YAML and shows an error.

```markdown
---
name: git-commit
description: Use when the user asks you to write a commit message.
---

# Writing commit messages
1. ...
```

### Add a subagent template

Create `Templates/<name>.md`. Templates are read fresh every time, so you can add one while the program runs.

```markdown
---
name: researcher
description: Reads files in the sandbox and summarizes what it finds.
tools: sandbox_shell, load_skill
skills:
---
You are a researcher. ...
```

### Add a sandbox

Create `Sandboxes/<name>/Containerfile` and add whatever you want preinstalled. The name: lowercase letters, digits and hyphens. The image is built the first time the agent opens it, and again whenever you change the file:

```dockerfile
FROM docker.io/library/python:3.12
RUN pip install numpy pandas
```

### Change the personality

Edit `Ego/SOUL.md`. It's the start of the main agent's system prompt.

## Notes

- `requirements.txt` pins `litellm==1.105.1`. Some newer pre-release versions also need the `mcp` package because of a LiteLLM bug.
- Without Podman, the app still runs. Only the sandbox tools won't work.
- The included `.gitignore` keeps your keys (`.env`), your chats (`Conversations/`) and everything the agent makes in `Shared/` off GitHub. Only `Shared/Notebooks_Engine/` stays, because the notebooks need it.
- Editing a Containerfile leaves the old image behind on disk, without a name. `podman image prune` removes such leftovers (of all your images, not only these).
