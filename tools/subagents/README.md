# subagents

Lets an agent hand work to subagents, several at once, and talk to them while they work. The logic lives in `agent.py` (`Agent.delegate` and `Agent.tell`); these two files only call it.

| Tool | Who gets it | What it does |
|---|---|---|
| `delegate` | every agent above the deepest level | Creates a subagent with one task and returns its report. |
| `tell` | every agent above the deepest level | Sends a follow-up message to a live subagent and returns its next report. |

## How it works

- A subagent is made from a template in `Templates/` (e.g. `worker`, `coder`), or from one-off instructions the parent writes.
- It starts with an empty context: it only knows its instructions and the task. So the parent has to put every fact it needs into the task.
- Several `delegate` calls in one reply run at the same time.
- A subagent's final message is its report and starts with `DONE`, `BLOCKED` or `QUESTION`. It stays under `REPORT_LIMIT` characters (6,000): details go into files, and the report points to them. Every claim says where it comes from: a source, a file, or the command that showed it.
- The parent gets the report with the subagent's id and folder in front, e.g. `[worker-1, its files: agents/20261018-19-50-01-worker-1/] DONE: ...`. With that it can read the subagent's result files (`read_result`), never the other way round.
- A subagent that asked a `QUESTION` stays alive: the parent answers with `tell`, and it carries on with its full context. All others end when the parent's task ends.
- Every subagent has its own folder inside its parent's: `Conversations/<conversation>/agents/<when>-<id>/`, with the same things as the conversation (`log.jsonl`, `results/`, `checkpoint.md` if it needed one, and `agents/` for its own subagents), plus `transcript.md`, a readable version you can watch live with `tail -f`.
- A subagent's whole life is one task, so it never gets a checkpoint after a task. If its context gets too full, the emergency path covers it: older results become pointers, then an emergency checkpoint (see "Checkpoints" in the main README).

## Limits (in config.py)

- `MAX_CHILDREN` (5): live subagents per agent.
- `MAX_DEPTH` (3): you talk to depth 1. It may create depth 2, which may create depth 3, which may not create any.
- Subagents never get the main-only tools (`MAIN_ONLY_TOOLS`), whatever a template says.
