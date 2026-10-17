# tools

Everything the agent can *do* is a tool, and every tool is one Python file in here. They are loaded once at startup.

## The folders

| Folder | Tools | What for |
|---|---|---|
| [`basic/`](basic/) | `calculate`, `load_skill` | Arithmetic, and loading a skill's instructions |
| [`memory/`](memory/) | `read_memory`, `write_memory` | The agent's memory file, `Ego/MEMORY.md` |
| [`notebook/`](notebook/) | `nb_create`, `nb_open`, `nb_close`, `nb_add`, `nb_edit`, `nb_run`, `nb_remove`, `nb_show`, `nb_rerun` | Jupyter notebooks that run in the sandbox |
| [`sandbox/`](sandbox/) | `sandbox_shell`, `check_sandbox`, `open_sandbox`, `close_sandbox` | Running commands in the sandbox, and opening or closing it |
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

- The main agent gets all of them.
- A subagent gets the tools its template lists, or a default set (`DEFAULT_SUBAGENT_TOOLS` in `config.py`). It never gets the main-only ones (`MAIN_ONLY_TOOLS`): memory, opening and closing the sandbox, and writing skills.
- Agents at the deepest level (`MAX_DEPTH`) don't get `delegate` and `tell`.
- An agent with skills always gets `load_skill`, because skills are useless without it.

## Good to know

- An error inside a tool doesn't crash anything: it goes back to the model as `error: ...`, so it can try again.
- A result longer than `MAX_TOOL_RESULT` characters (20,000) is cut off before the model sees it.
- Several tool calls in one reply run at the same time, each in its own thread. Their results go back in the order the model asked.
