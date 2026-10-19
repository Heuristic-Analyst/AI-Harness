# 01 — The big picture: what this program is, and why every part of it exists

This chapter has no code in it. It is the intuition: what problem each capability solves, and why the solution has the shape it has. If you read only one chapter, read this one.

---

## 1.1 A model is a function, and that is the whole problem

A language model does one thing: you give it text, it gives you back text. It has no memory. It does not remember your last message, your files, or that it already tried something that failed. Every time you call it, you must hand it the **entire conversation so far**, and it writes the next message.

So a conversation is really a *list* of messages that the program keeps on the model's behalf:

- `system` — standing instructions ("you are …"), always first;
- `user` — what the human typed;
- `assistant` — what the model said earlier (including any requests it made for tools);
- `tool` — the result of a tool the model asked for.

That list **is** the model's memory. If something is not in the list, the model does not know it. Almost every design decision in this repository follows from that single sentence. Keep it in your head: checkpoints, result files, memory, skills, subagents, locks — all of them exist because the model's knowledge is exactly equal to that one list, and that list is expensive, finite, and disappears when the program exits.

## 1.2 A model cannot *do* anything, so it asks

The model cannot read your disk, run `pip install`, or open a browser. What it can do is *ask*. Together with the message list you send a menu of **tools**: a name, a sentence saying what it is for, and a description of the arguments it takes. Instead of plain text, the model may reply with a request: *run `sandbox_shell` with `{"command": "ls"}`*.

The program then:

1. runs the matching Python function,
2. puts the answer into the list as a `tool` message,
3. calls the model again with the longer list.

The model reads the answer and either asks for another tool or writes its final reply. Repeat until it stops asking.

That loop — **send list → run what it asks → append result → send again** — is the whole program. A program that wraps a model in this loop and hands it tools is called a *harness*. This repository is one, and the loop is about thirty lines long (`agent.py:307`).

Everything else in the codebase answers one of two questions:

- **"What can the model do?"** → tools, sandboxes, notebooks, subagents.
- **"How do we keep the list small, correct, and findable?"** → result files, checkpoints, memory, skills, conversations, locks.

That is the map. The rest of this chapter walks it capability by capability.

## 1.3 The loop, seen from the outside

```
you type ──▶ message list ──▶ model
                  ▲              │
                  │              ├── plain answer ──▶ printed, task done
                  │              │
                  └── tool result│── tool call ──▶ the tool runs (code, container, subagent…)
                                 │
                                 └────────────── back to the model, list is longer by 2 messages
```

Two consequences that are easy to miss:

- **The model is stateless; the harness is stateful.** All the state lives in the harness: one Python list in memory, and files on disk for everything that must survive a crash or a restart.
- **Every tool result you add makes the next call more expensive**, and the list never shrinks by itself. A twenty-step task can easily pile up a million characters. That is a real, hard limit, not a detail — half of this program is about living inside it.

## 1.4 The seven problems, and the eight answers

Here is every capability of the harness, each as a problem the loop creates, plus the mechanism that solves it. This is the "big picture" in its compressed form; the chapters after this one open each mechanism up.

### Problem 1 — The model needs to act on the real world

**Answer: tools.** One Python file per tool anywhere under `tools/`. Each file has two things: `TOOL` (the name, description and argument schema the *model* reads) and `run()` (what actually happens). At startup the program walks that folder, imports every file it finds, and builds two dictionaries: name → schema (sent to the model) and name → function (called when the model asks). Adding a capability means adding a file. There is no registry to edit, no decorator, no config list. The folders are for *you*; the model only ever sees the `TOOL` name.

Why it is written this way: a tool is data (a description) plus behaviour (a function), and both belong in one small file a person can read in a minute. The model's view is generated from that file, so the description of a tool is genuinely *prompt text* — it steers when the model calls it.

### Problem 2 — Code must never run on your machine

**Answer: sandboxes.** Everything the model wants executed — `python`, `pip`, reading files, notebooks — runs in a rootless Podman container. The container sees exactly three folders from your machine, and nothing else: `Shared/common` (always), one project folder `Shared/<project>` (when the agent mounts one), and `Shared/Notebooks_Engine` read-only. The network is off, memory is capped at 2 GB, 2 CPUs, a process limit, and every command dies after 600 seconds. The container is **throwaway**: it is built from a `Containerfile` and nothing inside survives it. Close it and the files are gone; only the image, and the mounted folders, remain.

Why: a model that can run code is a model that can delete your home folder. The sandbox makes the blast radius everything inside the container and nothing outside. The mount list is deliberately short because that list *is* the security boundary.

### Problem 3 — Tool results are bigger than the list can hold

**Answer: result files.** A tool result longer than 8,000 characters is written to a file in the conversation folder (`results/000042-sandbox_shell.txt`), and the model gets a preview instead: the path, the size, the first lines and the last lines. If it wants the rest, it calls `read_result` (paging) or `search_result` (grep-like), and if it wants to *process* the data with code it calls `copy_result` to bring the file into the container.

Why: throwing the result away would lose work; keeping it all would fill the list. Writing it to disk and telling the model where it is keeps both. This is the general trick of the whole program — **nothing is ever deleted, it is moved out of the context and pointed at**.

### Problem 4 — The list fills up, and the conversation must not die

**Answer: checkpoints.** When a task ends and the list is more than 60% full, the agent is asked to write its own state in a fixed format — goal, decisions, facts, done, open, files, questions — into `checkpoint.md`. The list is then cleared and the next turn starts with a fresh list: system prompt (which now contains the checkpoint) plus the last task. In the middle of a task, at 80%, old tool results are first swapped for one-line pointers; if it is still too full, the checkpoint happens immediately and the task continues from there.

Why: summarizing is lossy and done by the same model that is running out of room. A checkpoint is *the model writing its own notes* in a shape it will recognise later. And because `log.jsonl` keeps every message word for word, nothing is lost even though the list is emptied.

### Problem 5 — One context is not enough for a big job

**Answer: subagents.** Any agent can call `delegate`, either from a template in `Templates/` or with one-off instructions. A subagent is the *same* `Agent` class, one level deeper, with its own list, its own folder and transcript, and a *restricted* set of tools. Several delegations in one reply run in parallel (one thread each). A subagent's last message is its report, and it must begin with `DONE`, `BLOCKED` or `QUESTION`. A `QUESTION` keeps that subagent alive so the parent can answer with `tell` and it continues with its full context. Limits: five live children per agent, three levels deep, and subagents never get sandbox, memory, project or skill tools — they work inside the parent's container.

Why: parallelism is the small benefit. The big one is *context isolation* — a subagent can burn 300,000 tokens of trial and error and hand back 2,000 characters of result.

### Problem 6 — The agent should not relearn the same thing every time

**Answer: skills.** A skill is a folder with a `SKILL.md`: a header (`name`, `description`) and a body of step-by-step instructions. Only the name and description sit in the system prompt; the body is loaded only when the model calls `load_skill`. The agent may write its *own* skills — but only into `Skills/Learned/`, which is marked `[editable]` in the prompt. Yours it can never change.

Why: instructions in the prompt cost tokens in *every* call; instructions in a skill cost tokens only when used. And the folder split is a permission model expressed in the file system: the agent's own skills are editable, the user's are read-only to it.

### Problem 7 — It must remember you, and you must be able to come back

**Answer: memory and conversations.** `Ego/MEMORY.md` is a plain markdown file that is injected into the system prompt of the main agent and edited with `read_memory` / `write_memory`. (The memory *skill* tells the model how to use it; the file is the truth.) Each conversation is a folder: `state.json` (what `/open` loads), `log.jsonl` (every message and event, appended, never rewritten), `checkpoint.md`, `results/`, and `agents/` with a subfolder per subagent.

Why files: you can read them, grep them, edit them, back them up, and the program can crash without corrupting them. There is no database anywhere in this project, deliberately.

### Problem 0 — Two instances, one folder

**Answer: locks.** You can run `main.py` several times at once. Each instance has an id (`pid-timestamp`), and a lock is *not* a file saying "in use" — it is an operating-system lock held on a file in `Locks/`. The OS drops it when the process dies, however it dies, so a forgotten lock cannot exist. Locks are taken per conversation, per project, per notebook, and around writing `MEMORY.md` or a skill.

Why OS locks: the naive version (a file whose existence means "locked") breaks on every crash and needs manual cleanup. The OS already solves exactly this problem.

## 1.5 Two bonuses that fall out of the design

- **Notebooks.** Because the container can run a real Jupyter-compatible kernel, the agent can create and edit `.ipynb` files and run cells one at a time, with variables alive between cells — the same experience as Jupyter, except the kernel lives in the throwaway container and the file lives in your project. The tool side talks to the kernel over a socket with a tiny JSON command protocol.
- **Two modes.** `ask` lets the agent put a question to you; `auto` tells it you are unavailable, so it assumes, states the assumption, and continues. The mode is one string in the agent, and it changes the system prompt and the behaviour of the loop.

## 1.6 What this program is *not*

- Not a framework: no plugin protocol, no server, no orchestration graph. One loop, one class, and files.
- Not a vector database / RAG system: retrieval is `grep` (`search_result`, `grep` in the shell) plus a memory file.
- Not magic about context: it does not compress or summarize automatically. It writes notes and clears, which is honest about what is lost.
- Not sandboxed by Docker daemon privileges: Podman, rootless, so "root inside" is you outside.

## 1.7 The shape of the solution, in one picture

```
                        ┌────────────────────────── main.py ──────────────────────────┐
                        │ terminal loop · /commands · conversations · instance lock    │
                        └───────────────────────────┬─────────────────────────────────┘
                                                    │ one Agent ("main")
                        ┌───────────────────────────▼─────────────────────────────────┐
                        │ agent.py — the loop, the message list, checkpoints,          │
                        │ subagents, result files, printing                            │
                        └───┬───────────────┬───────────────┬───────────────┬─────────┘
                            │               │               │               │
                    tools/ (files)     sandbox.py      config.py        locks.py
                    one per tool      containers,      settings,        OS file locks
                    discovery at      mounts, exec     paths, helpers
                    import            lifecycle
                            │
        ┌───────────────────┼─────────────────────┬──────────────────────┐
        ▼                   ▼                     ▼                      ▼
  code execution      memory & skills        subagents               notebooks
  (sandbox_shell,     (MEMORY.md,            (delegate/tell,         (client+kernel
   projects)           Skills/*)              same Agent class)       in the container)
```

Files on disk are the memory of the whole system:

```
Ego/SOUL.md         who the main agent is            (you write it)
Ego/MEMORY.md       what it remembers                (it edits it)
Skills/<n>/SKILL.md instructions loaded on demand    (you; Learned/ is the agent's)
Templates/<n>.md    ready-made subagents             (you)
Sandboxes/<n>/      one Containerfile per sandbox    (you)
Conversations/<n>/  state.json · log.jsonl · checkpoint.md · results/ · agents/
Locks/              lock files of the running instances (contents irrelevant)
Shared/common/      always visible in the container
Shared/<project>/   the one project this instance mounted
```

## 1.8 How the rest of the guide is organised

Three pictures, as you asked for:

1. **Big picture** — this chapter: every capability, why it exists, how it works in words.
2. **Small picture** — chapters 03 to 07: every file, every function, every line that does something, with the code quoted and explained, plus examples.
3. **Interconnected picture** — chapter 08: all the data shapes (messages, tool schemas, tool results, replies, notebook commands, lock names, file naming), who writes them and who reads them, three end-to-end traces with realistic outputs, and a table of what breaks if a piece is missing.

Chapter 02 is the map you will keep coming back to: what lives where, and which process runs what.

> Read 01 → 02 → skim 08 → then 03…07 in order. Then read 08 again. The second time, it will read like a summary of everything you just learned.
