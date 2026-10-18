# tools/projects

**Project runs**: a long project (hours, days, any size) as a graph of nodes, worked on in shifts, in the background. Everything for it is in this folder. How a run works, for you: the main [README](../../README.md#project-runs). How the agent sets one up with you: `Skills/project-run/SKILL.md`.

## The files

| File | What it is |
|---|---|
| `start_run.py` | **Tool**, main agent only. Sets up a new run in `Shared/<project>/.graph/` (goal, done-when points, budget, sandbox, optionally a plan: the first level of nodes) and starts the scheduler. On a run that exists already, it lets it go on (also after a pause). The project must not be mounted, by this instance or another. |
| `run_status.py` | **Tool**, main agent only. Where a run stands: running, paused or stopped, the budget used, the tree of nodes, the root's questions to you and its result, the last lines of `run.log`. |
| `message_run.py` | **Tool**, main agent only. Your answer or a change, to the root. Starts the scheduler again if it stopped. `extra_budget` raises the run's budget, only while it is stopped or paused. |
| `pause_run.py` | **Tool**, main agent only. The shifts going on now finish, no new ones start. `start_run` lets it go on. |
| `_graph.py` | The graph: the files in `.graph/` and the rules (which node is ready, who wakes up, what gets stale, the briefing of a shift). No model in it. |
| `_scheduler.py` | The scheduler: its own program, `python -m tools.projects._scheduler <project>`, started by `start_run` in the background, so it goes on when you close the chat. One per project. It gives every ready node a shift, up to `RUN_PARALLEL` at once. Its `NodeAgent` is the agent of one shift: an `Agent` from `agent.py` with the node rules, the node tools, a token budget and a wrap-up when the budget is gone. |
| `_nodes/` | The node tools (below). The `_` hides them from the tool loader: the main agent and its subagents never see them. Only the scheduler loads them, for its nodes. |

## The node tools, in `_nodes/`

| Tool | What it does |
|---|---|
| `create_nodes` | Splits the node into children: each with goal, why, done-when points, budget and `depends_on` (siblings). All or nothing: at most `NODE_CHILDREN` live children, not deeper than `NODE_DEPTH`, each budget at least `NODE_MIN_BUDGET`, together not more than the node has left, no circles. |
| `write_result` | Finishes the node: a report that starts with `DONE` or `BLOCKED` (under `REPORT_LIMIT` characters), one answer per done-when point, and the final checkpoint. A `DONE` needs every child accepted or cancelled. |
| `check_result` | A child's result: `accept`, or `send_back` with a note saying exactly what is missing, and optionally more budget from the node's own. Siblings that build on a sent-back child become stale. |
| `cancel_node` | Drops a child with everything below it, with a reason, optionally `replaced_by` another child: whatever depended on it waits for that one now. Its spent budget is not returned. |
| `send_message` | To `parent` (the root's parent is you) or to one of its own children. A question to the parent ends in waiting. |
| `add_fact` / `search_facts` | The run's shared facts in `knowledge/facts.jsonl`, each with its source, so no node finds the same thing twice. |
| `node_status` | The whole graph, and what the node has left of its budget. |

`_nodes/_node.py` holds what they share. A node can only change itself and its own children, and only through these tools: the sandbox sees `.graph/` read-only.

## Good to know

- The scheduler is an instance like `main.py`: its own sandbox, with the project mounted, so no other instance can mount the project while it runs. Its output is in `.graph/scheduler.log`, what it did in `.graph/run.log`, and each node's whole shift in `transcript.md` in its folder (`.graph/work/T1/agents/...`).
- A node's replies don't stream: nobody watches them, and in one piece they come with the provider's token count, which the budget is measured in.
- The settings are in `config.py`: `RUN_PARALLEL`, `NODE_CHILDREN`, `NODE_DEPTH`, `NODE_MIN_BUDGET`, `BUDGET_WARNING`, `BUDGET_RESERVE`, `IDLE_SHIFTS`.
