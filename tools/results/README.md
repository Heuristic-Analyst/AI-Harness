# results

Tool results that are too long for the agent's context are saved as files, and the agent only sees their start and end. These three tools let it work with the rest.

| Tool | Who gets it | What it does |
|---|---|---|
| `read_result` | main, and subagents by default | Shows a range of lines from a result file, with line numbers: at most 200 lines or 6,000 characters per call, like scrolling. |
| `search_result` | main, and subagents by default | Finds lines in one result file or in all of them, like `grep`: each hit with its file and line number. |
| `copy_result` | main, and subagents by default | Copies a result file into `common/` or any folder in it, or into the mounted project or any folder in it, so the agent can work on it with code in the sandbox. |

## Where results go

- A tool result longer than `RESULT_TO_FILE` characters (8,000) goes into the agent's folder as `results/000042-sandbox_shell.txt`: a counter with six digits, then the tool's name. The counter goes on across checkpoints and `/open`, so a name is never used twice in one conversation.
- The agent gets a preview instead: where the file is, how big it is, the first 40 lines and the last 20.
- `load_skill`, `read_memory`, `read_result` and `search_result` are never put into a file: the agent needs all of them, and they are short anyway.
- When the context gets too full in the middle of a task, older tool results are moved out too: they become a short pointer to their file (see "Checkpoints" in the main README).

## Who may use which files

- An agent can use its own result files, and those of its subagents, all the way down: `agents/<its folder>/results/...`. The subagent's folder is named at the start of its report.
- Never its parent's, never a sibling's, and nothing else in the folder: not the log, not the checkpoint.
- The path is checked, never trusted: everything it names must really lie inside the agent's own folder.

## copy_result

- The target is a folder: `common`, `common/data/raw`, or, only while this instance's sandbox runs with a project mounted, `<project>` or a folder in it. `/workspace/common/...` works too.
- Missing folders are created. An existing file is never replaced: the agent picks another name.
- No sandbox running? It still copies into `common/`, and says that a sandbox is needed to work on it.
