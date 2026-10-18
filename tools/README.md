# tools

Everything the agent can *do* is a tool, and every tool is one Python file in here. They are loaded once at startup.

## The folders

| Folder | Tools | What for |
|---|---|---|
| [`basic/`](basic/) | `calculate`, `load_skill` | Arithmetic, and loading a skill's instructions |
| [`memory/`](memory/) | `read_memory`, `write_memory` | The agent's memory file, `Ego/MEMORY.md` |
| [`notebook/`](notebook/) | `nb_create`, `nb_open`, `nb_close`, `nb_add`, `nb_edit`, `nb_run`, `nb_remove`, `nb_show`, `nb_rerun` | Jupyter notebooks that run in the sandbox |
| [`sandbox/`](sandbox/) | `sandbox_shell`, `check_sandbox`, `open_sandbox`, `close_sandbox`, `check_projects`, `mount_project`, `unmount_project`, `create_project`, `delete_project`, `rename_project` | Running commands in the sandbox, opening or closing it, and the project folders |
| [`results/`](results/) | `read_result`, `search_result`, `copy_result` | Long tool results, saved as files: reading, searching, copying them into the sandbox |
| [`projects/`](projects/) | `start_run`, `run_status`, `message_run`, `pause_run` (+ the node tools in `_nodes/`) | Project runs: starting and following one, its graph, its scheduler |
| [`skills/`](skills/) | `create_skill`, `edit_skill`, `delete_skill` | The skills the agent writes itself, in `Skills/Learned/` |
| [`subagents/`](subagents/) | `delegate`, `tell` | Handing work to subagents, and talking to them |

## How a tool file looks

```python
# tools/basic/word_count.py
def run(agent, text):
    return str(len(text.split()))

TOOL = {
    "name": "word_count",
    "description": "Count the words in a text.",
    "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
}
```

- `TOOL` is what the model sees: the name, when to use it, and its arguments.
- `run` is what happens. It always gets the calling agent first, then the arguments the model passed. Whatever it returns goes back to the model as text.

## The rules the loader follows

- Every `.py` file in here is a tool, in any folder, as deep as you like. The folders are only for you: the model sees the `name` in `TOOL`, and templates list tools by that name, so moving a file breaks nothing.
- Files and folders starting with `_` are skipped: `_notebook.py`, `_skillfile.py`, `_drafts/`. That is where shared helper code goes.
- Anything that isn't a `.py` file is ignored, like these READMEs.
- Two tools with the same name stop the program at startup, with a message naming both files.

## Who gets which tool

- The main agent gets all of them. (The node tools in [`projects/_nodes/`](projects/_nodes/) are not among them: the folder starts with `_`, so the loader skips it, and only the scheduler of a project run loads them, for its nodes.)
- A subagent gets the tools its template lists, or a default set (`DEFAULT_SUBAGENT_TOOLS` in `config.py`). It never gets the main-only ones (`MAIN_ONLY_TOOLS`): memory, opening, closing and checking the sandbox, the project tools, project runs, and writing skills. Subagents work in their parent's sandbox.
- Agents at the deepest level (`MAX_DEPTH`) don't get `delegate` and `tell`.
- An agent with skills always gets `load_skill`, because skills are useless without it.

## Good to know

- An error inside a tool doesn't crash anything: it goes back to the model as `error: ...`, so it can try again.
- A result longer than `RESULT_TO_FILE` characters (8,000) goes into a file in the conversation folder. The model gets its start and end, and reads the rest with the [`results/`](results/) tools. Nothing is cut off and lost.
- Several tool calls in one reply run at the same time, each in its own thread. Their results go back in the order the model asked.
