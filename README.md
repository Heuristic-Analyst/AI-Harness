# agent

A small, readable multi-agent assistant that runs in your terminal. It talks to any LLM through [LiteLLM](https://github.com/BerriAI/litellm), can split work across subagents that run in parallel, remembers things between conversations, and runs code only inside throwaway [Podman](https://podman.io) containers, never on your machine.

The whole thing is about a thousand lines of commented Python. It's meant to be read, changed and extended.

## Features

- **Any model.** One line in `config.py` picks the model: DeepSeek, Anthropic, OpenAI, a local Ollama model, or anything else LiteLLM supports.
- **Subagents.** The agent can `delegate` tasks to subagents, either from ready-made templates or with one-off instructions. Several delegations in one reply run in parallel. Subagents report back with `DONE`, `BLOCKED` or `QUESTION`, and a parent can answer a question with `tell` so the subagent picks up where it stopped.
- **Sandboxes.** Code, installs and file work happen in rootless Podman containers with no network by default, memory, CPU and process limits, and exactly one shared folder.
- **Skills.** Step-by-step instructions in Markdown that the agent loads only when it needs them, so the system prompt stays small.
- **Memory.** A plain `MEMORY.md` file that the agent reads at the start of every conversation and edits itself.
- **Persistent conversations.** Every conversation is saved as JSON and can be listed, reopened and renamed.
- **Automatic compaction.** When a conversation grows past a token limit, older tasks are summarized and the most recent ones are kept word for word.
- **Jupyter notebooks.** The agent adds, edits, runs and deletes cells in real `.ipynb` files. Variables stay alive between runs, like in Jupyter, and every change lands in the file right away, so you can open it.
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
model: deepseek/deepseek-flash | tools: 10 | skills: memory | templates: coder, worker | sandboxes: ubuntu
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
| `/exit`, `/quit` | Leave. A running sandbox is stopped, and you're asked whether to save it first. |

### Sandbox commands

| Command | What it does |
|---|---|
| `/sandbox list` | All sandboxes, which one is running, which have an image. |
| `/sandbox check [name]` | State of one sandbox, or of all without a name. |
| `/sandbox new <name> [image]` | Create a sandbox (plain Ubuntu 24.04 by default) and build it. |
| `/sandbox run [name]` | Start a sandbox clean from its image. |
| `/sandbox stop` | Stop the running sandbox. Unsaved changes are lost. |
| `/sandbox save` | Make the running state the sandbox's new image. |
| `/sandbox remove <name>` | Delete a sandbox: its folder and its image. |
| `/sandbox reset <name>` | Forget the saved state and rebuild from the Containerfile. |
| `/sandbox copy <name> <new>` | Make a second sandbox with the same Containerfile and saved state. The two are independent afterwards. |
| `/sandbox rename <old> <new>` | Rename a sandbox, saved state included. It has to be stopped. |
| `/sandbox net on\|off` | Switch internet for the running sandbox (off by default). |
| `/sandbox shell` | A root shell inside the running sandbox, for you. |

## Project layout

```
.
├── main.py              # start here: the chat loop and the /commands
├── agent.py             # the Agent class: model calls, tool loop, subagents, compaction
├── sandbox.py           # Podman sandboxes: build, run, stop, save, exec
├── notebook.py          # the notebook tools' way into the sandbox
├── notebook_kernel.py   # runs inside the sandbox: the notebook kernel (variables + cells + .ipynb file)
├── config.py            # all settings and paths, plus small shared helpers
├── requirements.txt
├── .env                 # your API keys (create it yourself, don't commit it)
├── Ego/
│   ├── SOUL.md          # who the main agent is. you write it
│   └── MEMORY.md        # what it remembers. the agent edits this itself
├── Skills/
│   └── memory/SKILL.md  # one folder per skill
├── Templates/
│   ├── coder.md         # ready-made subagents: instructions, tools, skills
│   └── worker.md
├── tools/               # one file per tool
├── Sandboxes/
│   ├── ubuntu/Containerfile   # one folder per sandbox
│   └── python/Containerfile   # python + numpy, pandas, matplotlib: for notebooks
├── Shared/              # the only folder a sandbox can see (/workspace inside)
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
| `BASE_IMAGE` | `ubuntu:24.04` | Image for new sandboxes. |
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

Subagents never get the main-only tools (`read_memory`, `write_memory`, `open_sandbox`, `close_sandbox`, `check_sandbox`). Agents at the maximum depth don't get `delegate` or `tell`.

### Sandboxes

Each folder in `Sandboxes/` is one sandbox, defined by its `Containerfile`. Building it gives an image, and running it starts a container that's deleted when it stops, so every start is clean unless you `/sandbox save`. Only one sandbox runs at a time.

A running sandbox:

- has its network disconnected right after start (turn it on with `/sandbox net on`)
- runs with `no-new-privileges`, a 512-process limit and the memory and CPU limits from `config.py`
- sees only `Shared/` from your machine, mounted at `/workspace` with `noexec`, so files there have to be run through an interpreter (`python x.py`, `bash x.sh`)

The agent can open a sandbox, but you always pick which one. The agent can stop a sandbox but can't save one. Only you can save.

### Memory

`Ego/MEMORY.md` is included in the main agent's system prompt. When you ask it to remember or forget something, it loads the `memory` skill, reads the file, and writes back the whole updated file.

### Notebooks

The `nb_*` tools give the agent Jupyter-style notebooks. Each notebook in `Shared/` gets its own **kernel**: a small Python program (`notebook_kernel.py`) that is started inside the sandbox on first use and then keeps running, so the variables one cell creates are still there for the next. Every tool call is a short command that hands one request to that kernel and prints its answer.

- every cell has a short id (e.g. `3f9a1c0b`) that stays the same when cells are added or removed
- every answer ends with an overview of all cells and their state (`ran [3]`, `not run`, `EDITED since, output is stale`, `error`), so the agent always knows where it is
- the `.ipynb` file is rewritten after every change, outputs and plots included. Open it in Jupyter or VS Code to follow along
- if you change the file yourself, the kernel notices on the next command and reads it again
- a cell that runs too long is interrupted; the variables are kept. `nb_restart` throws them all away
- it needs `python3` in the sandbox: use the `python` sandbox (`/sandbox run python`), or add python to yours. The kernel itself uses only the standard library

### Compaction

Before each model call the conversation's size is estimated. Past `CONTEXT_LIMIT`, everything except the last `KEEP_TASKS` tasks is summarized by a separate request, and the summary moves into the system prompt.

## Built-in tools

| Tool | Who gets it | What it does |
|---|---|---|
| `calculate` | all | Evaluates a math expression in a separate, time-limited process. Only digits and math symbols are accepted. |
| `load_skill` | agents with skills | Returns a skill's full instructions. |
| `delegate` | above max depth | Creates a subagent with one task and returns its report. |
| `tell` | above max depth | Sends a follow-up message to a live subagent. |
| `sandbox_shell` | all | Runs a bash command inside the running sandbox. |
| `check_sandbox` | main only | Shows sandbox state without changing anything. |
| `open_sandbox` | main only | Asks you which sandbox to start. |
| `close_sandbox` | main only | Stops the running sandbox. |
| `nb_add` / `nb_edit` / `nb_delete` | main (subagents if given) | Add, change or remove a notebook cell, optionally running it right away. |
| `nb_run` | main (subagents if given) | Runs one cell (or `all`) and returns its output. |
| `nb_show` | main (subagents if given) | The whole notebook: every cell with source and output. |
| `nb_restart` | main (subagents if given) | A fresh kernel for a notebook: all variables gone, cells kept. |
| `read_memory` | main only | Reads `MEMORY.md`. |
| `write_memory` | main only | Replaces `MEMORY.md`. |

## Extending it

### Add a tool

Create `tools/<name>.py` with a `run` function and a `TOOL` description. `run` always receives the calling agent first, then the arguments the model passed. Tools are loaded at startup.

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

Create `Skills/<name>/SKILL.md`. Only the `name` and `description` go into the system prompt. The body is loaded when the agent calls `load_skill`. Skills are read at startup.

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

Run `/sandbox new <name> [image]`, or create `Sandboxes/<name>/Containerfile` yourself and add whatever you want preinstalled:

```dockerfile
FROM docker.io/library/python:3.12
RUN pip install numpy pandas
```

### Change the personality

Edit `Ego/SOUL.md`. It's the start of the main agent's system prompt.

## Notes

- `requirements.txt` pins `litellm==1.105.1`. Some newer pre-release versions also need the `mcp` package because of a LiteLLM bug.
- Without Podman, the app still runs. Only the sandbox tools won't work.
- Before pushing, add `.env` and `Conversations/` to `.gitignore` so your keys and chats stay private.
