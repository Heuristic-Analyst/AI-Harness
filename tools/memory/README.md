# memory

The agent's long-term memory: one file, `Ego/MEMORY.md`. It is shown in the main agent's system prompt at the start of every conversation, so whatever is saved there, the agent still knows next time.

| Tool | Who gets it | What it does |
|---|---|---|
| `read_memory` | main only | Returns the memory file as it is right now. |
| `write_memory` | main only | Replaces the whole memory file. |

## How it works

- `write_memory` always replaces the **whole** file. Whatever the agent leaves out is deleted, so it reads first, then writes the complete new version. The `memory` skill (`Skills/memory/SKILL.md`) walks it through exactly that.
- After a write, the copy in the system prompt is updated right away.
- Neither tool takes a path: they can only ever touch `MEMORY.md`.
- `write_memory` only saves if the file is still as `read_memory` showed it. If another running instance (or you) saved something in between, it refuses, and the agent reads again and merges. So two instances never save over each other.
- Only the main agent gets them. Subagents can't read or change the memory.

You can edit `Ego/MEMORY.md` yourself at any time. The agent sees your version at the next conversation, or right away the next time it calls `read_memory`.
