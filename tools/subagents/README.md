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
- A subagent's final message is its report and starts with `DONE`, `BLOCKED` or `QUESTION`.
- A subagent that asked a `QUESTION` stays alive: the parent answers with `tell`, and it carries on with its full context. All others end when the parent's task ends.
- Every subagent writes a full transcript to `Conversations/agents/`. Watch one live with `tail -f`.

## Limits (in config.py)

- `MAX_CHILDREN` (5): live subagents per agent.
- `MAX_DEPTH` (3): you talk to depth 1. It may create depth 2, which may create depth 3, which may not create any.
- Subagents never get the main-only tools (`MAIN_ONLY_TOOLS`), whatever a template says.
