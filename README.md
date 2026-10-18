# agent

A small, readable multi-agent assistant that runs in your terminal. It talks to any LLM through [LiteLLM](https://github.com/BerriAI/litellm), can split work across subagents that run in parallel, remembers things between conversations, and runs code only inside throwaway [Podman](https://podman.io) containers, never on your machine.

The whole thing is under two thousand lines of commented Python. It's meant to be read, changed and extended.

## Features

- **Any model.** One line in `config.py` picks the model: DeepSeek, Anthropic, OpenAI, a local Ollama model, or anything else LiteLLM supports.
- **Subagents.** The agent can `delegate` tasks to subagents, either from ready-made templates or with one-off instructions. Several delegations in one reply run in parallel. Subagents report back with `DONE`, `BLOCKED` or `QUESTION`, and a parent can answer a question with `tell` so the subagent picks up where it stopped.
- **Sandboxes.** Code, installs and file work happen in rootless Podman containers with no network by default, and memory, CPU and process limits. The agent picks and opens the sandbox it needs itself. Each running `main.py` gets its own container, and its Containerfile is all there is: nothing is ever saved inside.
- **Projects.** The agent works in folders on your machine: `Shared/common/`, which every running instance shares, and one project folder `Shared/<project>/` that it mounts, which no other instance can mount at the same time.
- **Skills.** Step-by-step instructions in Markdown that the agent loads only when it needs them, so the system prompt stays small. The agent can also write its own skills, in a folder of their own, and improve or delete them later. Yours it can never change.
- **Memory.** A plain `MEMORY.md` file that the agent reads at the start of every conversation and edits itself.
- **Persistent conversations.** Every conversation is saved as JSON and can be listed, reopened and renamed.
- **Automatic compaction.** When a conversation grows past a token limit, older tasks are summarized and the most recent ones are kept word for word.
- **Jupyter notebooks.** The agent creates, edits and runs real `.ipynb` notebooks inside the sandbox. Variables stay alive between cells, like in Jupyter, and every change is saved to the file right away, so you can open it any time.
- **Two modes.** In `ask` mode the agent may ask you questions. In `auto` mode it makes reasonable assumptions and decides on its own.

## Requirements

- Python 3 (3.10 or newer recommended)
- An API key for your model provider (not needed for local models such as Ollama)
- [Podman](https://podman.io/docs/installation), only if you want sandboxes. Everything else works without it.

## Quick start

```bash
git clone https://github.com/<you>/agent.git
cd agent
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
model: deepseek/deepseek-flash | tools: 26 | skills: memory, notebook | templates: coder, worker | sandboxes: python, ubuntu
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
├── requirements.txt
├── .env                 # your API keys (create it yourself, don't commit it)
├── Ego/
│   ├── SOUL.md          # who the main agent is. you write it
│   └── MEMORY.md        # what it remembers. the agent edits this itself
├── Skills/              # one folder per skill. these are yours: the agent can't change them
│   ├── memory/SKILL.md
│   ├── notebook/SKILL.md
│   └── Learned/         # skills the agent wrote itself: the only ones it may create, edit and delete
├── Templates/
│   ├── coder.md         # ready-made subagents: instructions, tools, skills
│   └── worker.md
├── tools/               # one file per tool, sorted into folders by feature
│   ├── basic/           #   calculate, load_skill
│   ├── memory/          #   read_memory, write_memory
│   ├── notebook/        #   nb_create, nb_open, nb_close, nb_add, nb_edit, nb_run, nb_remove, nb_show, nb_rerun
│   ├── sandbox/         #   sandbox_shell, check_sandbox, open_sandbox, close_sandbox, check_projects, mount_project, unmount_project, rename_project
│   ├── skills/          #   create_skill, edit_skill, delete_skill
│   └── subagents/       #   delegate, tell
├── Sandboxes/
│   ├── ubuntu/Containerfile   # one folder per sandbox
│   └── python/Containerfile   # python + numpy, pandas, matplotlib: the one notebooks need
├── Shared/              # the only folder a sandbox sees parts of
│   ├── common/          #   every sandbox of every instance: /workspace/common. created on first use
│   ├── <project>/       #   one project per sandbox, mounted by the agent: /workspace/<project>
│   └── Notebooks/Engine/  # kernel.py + client.py: run the notebooks inside the sandbox (mounted read-only)
└── Conversations/       # saved conversations (.json), created on first use
    └── agents/          # subagent transcripts (.md)
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
| `CONTEXT_LIMIT` | `100_000` | Token count at which old tasks are summarized. |
| `KEEP_TASKS` | `2` | How many recent tasks stay word for word after summarizing. |
| `MAX_TOOL_RESULT` | `20_000` | Longest tool result (characters) sent back to the model. |
| `MAX_CHILDREN` | `5` | Live subagents one agent may have at once. |
| `MAX_DEPTH` | `3` | How deep the agent tree may go. You talk to depth 1. |
| `SANDBOX_MEMORY` / `SANDBOX_CPUS` | `2g` / `2` | Resource limits for a running sandbox. |
| `MAX_TOOL_TIMEOUT` | `600` | Seconds a sandbox command may run before it is stopped. |

The API key is read from `.env` only. It never touches your environment variables.

## How it works

### The agent loop

The main agent and every subagent are the same `Agent` class. Each one keeps its whole conversation in a single list of messages. On every turn it sends the list to the model, prints the reply, runs any tool calls (each in its own thread) and loops until the model answers without calling a tool.

The system prompt is rebuilt from parts whenever one of them changes: the soul or template instructions, the subagent rules, the skills menu, the templates menu, the memory, the mode and the summary of earlier tasks.

### Subagents

The main agent can call `delegate` with a template name or its own instructions. Each subagent:

- starts with an empty context and knows only its instructions and the task it was given
- writes a full transcript to `Conversations/agents/`, which you can watch live with `tail -f`
- ends its work with a report that starts with `DONE`, `BLOCKED` or `QUESTION`
- is closed when its parent's task ends, unless it's waiting for an answer to a `QUESTION`

Subagents never get the main-only tools (`read_memory`, `write_memory`, `open_sandbox`, `close_sandbox`, `check_sandbox`, `check_projects`, `mount_project`, `unmount_project`, `rename_project`, `create_skill`, `edit_skill`, `delete_skill`). They work in their parent's sandbox. Agents at the maximum depth don't get `delegate` or `tell`.

### Sandboxes

Each folder in `Sandboxes/` is one sandbox, defined by its `Containerfile`, and the Containerfile is all there is. Building it gives an image, and running it starts a container that's deleted when it stops, so every start is clean. Nothing is ever saved: the image is built from the Containerfile again at every start. Unchanged steps come from Podman's cache, so that's quick, and a change you make in a Containerfile is in the very next start.

An instance is one running `main.py`. Each instance runs at most one sandbox, in its own container. Several instances can run at the same time, with the same sandbox (one image, a container each) or different ones. The agent picks a sandbox by reading the Containerfiles (`check_sandbox`) and opens and closes it itself. When you exit, its sandbox is stopped.

A running sandbox:

- has its network disconnected right after start (turn it on with `/sandbox net on`)
- runs with `no-new-privileges`, a 512-process limit and the memory and CPU limits from `config.py`
- sees only these folders of your machine, all mounted `noexec`, so files there have to be run through an interpreter (`python x.py`, `bash x.sh`):
  - `Shared/common/` at `/workspace/common`: always there, in every instance, so instances can share files. It can't be unmounted.
  - `Shared/<project>/` at `/workspace/<project>`: one project folder at most, mounted by the agent (`mount_project`). While one instance has it, no other instance can mount it. A new name creates the folder.
  - `Shared/Notebooks/Engine/` at `/workspace/Notebooks/Engine`, read-only: the notebook engine. It can't be changed from inside.

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

The `nb_*` tools give the agent Jupyter-style notebooks, in `Shared/common/` or the mounted project. The tools in `tools/notebook/` only pass commands on: everything runs inside the sandbox, through the engine in `Shared/Notebooks/Engine/` (inside the sandbox: `/workspace/Notebooks/Engine/`, read-only).

- `kernel.py` is the kernel of one open notebook. It keeps running, holds the variables and the cells, and writes the whole `.ipynb` file after every change.
- `client.py` runs once per tool call. It starts a kernel (`nb_create`, `nb_open`), stops one (`nb_close`), or hands the command to the running one.

Every answer ends with an overview of all cells: id, state (`ran [3]`, `not run`, `EDITED since, output is stale`, `error`) and first line, so the agent always knows where it is. The `notebook` skill tells it how to work: a plan cell at the top, one step per cell, fix cells in place, `nb_rerun` at the end. If you edit an open notebook yourself, the kernel notices and keeps your changes. Notebooks need `python3` in the sandbox, e.g. the `python` sandbox. Moving the engine? Change `ENGINE` in `sandbox.py`.

### Compaction

Before each model call the conversation's size is estimated. Past `CONTEXT_LIMIT`, everything except the last `KEEP_TASKS` tasks is summarized by a separate request, and the summary moves into the system prompt.

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
| `rename_project` | main only | Renames a project folder that no sandbox has mounted. |
| `nb_create` / `nb_open` | main (subagents if given) | Make a new notebook or open an existing one: starts its kernel. |
| `nb_close` | main (subagents if given) | Stops a notebook's kernel. The file stays. |
| `nb_add` / `nb_edit` / `nb_remove` | main (subagents if given) | Add, change or remove a cell, optionally running it right away. |
| `nb_run` | main (subagents if given) | Runs one or more cells in order and returns their output. |
| `nb_show` | main (subagents if given) | The whole notebook: every cell with code and output. |
| `nb_rerun` | main (subagents if given) | Fresh kernel, then every cell from the top. |
| `create_skill` / `edit_skill` / `delete_skill` | main only | Write, rewrite or delete the agent's own skills in `Skills/Learned/`. |
| `read_memory` | main only | Reads `MEMORY.md`. |
| `write_memory` | main only | Replaces `MEMORY.md`. |

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
- The included `.gitignore` keeps your keys (`.env`), your chats (`Conversations/`) and everything the agent makes in `Shared/` off GitHub. Only `Shared/Notebooks/Engine/` stays, because the notebooks need it.
- Editing a Containerfile leaves the old image behind on disk, without a name. `podman image prune` removes such leftovers (of all your images, not only these).
