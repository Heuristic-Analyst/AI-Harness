# AI-Harness, explained from the ground up

A complete guide to the AI-Harness codebase (the `AI-Harness-main` folder next to this one): about 3,100 lines of Python that wrap a language model in a loop, give it tools, and run everything it executes inside throwaway containers.

It is written in three pictures, as requested:

| Picture | Chapter | What it gives you |
|---|---|---|
| **Big picture** | `01-big-picture.md` | Every capability and *why it exists*, in words, no code. The problems the loop creates and the mechanism that solves each one. |
| **Small picture** | `02` map, then `03`–`07` | Every file, every function, every line that does something and why. Code quoted and explained. Examples throughout. |
| **Interconnected picture** | `08-inside-out.md` | Every data shape, who writes it and who reads it, how the subsystems interlock, three end-to-end traces, a table of loose ends, a cheat sheet of all dicts. |

## Read in this order

1. **`01-big-picture.md`** — intuition. Read it first, in one sitting.
2. **`02-architecture-map.md`** — where everything lives: files, four kinds of process, folders, mounts, startup order. Keep it open while reading the rest.
3. **`08-inside-out.md` §8.1–8.3** — skim it, so you know which shapes to watch for.
4. **`03` → `04` → `05` → `06` → `07`** — the line-by-line chapters, in dependency order.
5. **`08-inside-out.md`** again — the second time it reads like a summary of everything you learned.

## The chapters

| File | Lines | Covers |
|---|---|---|
| `00-README.md` | this | index, how to read |
| `01-big-picture.md` | 170 | the loop, the seven problems, the eight answers, what it is *not* |
| `02-architecture-map.md` | 169 | codebase in numbers, processes, folders, mounts, object graph, startup/shutdown, dependency direction |
| `03-config-locks-main.md` | 671 | every constant and helper in `config.py`; the OS-lock design in `locks.py`; startup, `/commands`, conversations and shutdown in `main.py` |
| `04-agent.md` | 737 | the tool loader; the prompt strings; `preview`/`highest_result`; `Agent` line by line: prompt building, logging, printing, tool dispatch, the loop, tokens, checkpoints, `clear`, `last_tasks`, `move_old_results`, `delegate`, `tell`, report handling, closing |
| `05-sandbox.md` | 633 | containers in plain words; every function of `sandbox.py`; the mounts table; the exact `podman` command lines; timeouts and failures |
| `06-tools-core.md` | 851 | the tool protocol (a `TOOL` dict + a `run` function, discovered by walking `tools/`); then 19 tools: basic, memory, skills, subagents, sandbox/projects |
| `07-notebooks-results.md` | 1405 | long results and the three tools that read them; the notebook engine: `client.py` (messenger, inside the container), `kernel.py` (the kernel), the JSON command table, all nine `nb_*` tools, a worked notebook session |
| `08-inside-out.md` | 467 | the eight data shapes; the identifiers; one turn end to end; nine subsystem interlocks; three traces; loose ends; cheat sheet |

## A note on the examples

- **"real"** means: actually produced by running the repository's own code while writing this guide. `agent.py` and all 31 tools were imported for real, with only `litellm` replaced by a stub (no network here). The system prompt, the tool message, the preview, the pointer, the result file names and the `log.jsonl` lines in chapter 08 are real outputs.
- **"reconstructed"** means: built by reading the code, for anything that needs a model or podman to happen. That covers most network and container examples. They are marked as such.

## Three facts worth carrying with you

1. **The message list is the model's entire world.** Everything else — checkpoints, result files, memory, skills — exists to feed that list, shrink it, or rebuild it.
2. **Nothing is ever deleted, it is moved out of the context and pointed at.** Long results become files, old results become one-line pointers, full contexts become a checkpoint. `log.jsonl` keeps every word, always.
3. **One class, many agents.** The main agent, a subagent, a subagent's subagent: same `Agent`, different instructions, tools, depth and folder. The only differences are arguments.

## Where the code is

```
agent-explainer/
├── AI-Harness-main/     the codebase, extracted from AI-Harness-main.zip
└── guide/               these chapters
```

Every reference in the guide looks like `agent.py:307` or `tools/notebook/nb_run.py:12` — relative to `AI-Harness-main/`. Open the repo next to the guide and jump.
