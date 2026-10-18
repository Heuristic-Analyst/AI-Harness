# notebook

Jupyter notebooks for the agent. It adds, edits and runs cells in real `.ipynb` files, and the variables stay alive between cells, like in Jupyter. Everything runs **inside the sandbox**; the files in here only pass the commands on.

| Tool | What it does |
|---|---|
| `nb_create` | Makes a new notebook in `common/` or the mounted project and starts its kernel. |
| `nb_open` | Opens an existing notebook (starting its kernel) and returns all of it. Already open? Its variables are kept. |
| `nb_close` | Stops a notebook's kernel. Its variables are gone, the file stays. |
| `nb_add` | Adds a code or markdown cell, at the end or after a given cell, optionally running it. |
| `nb_edit` | Replaces a cell's whole code, optionally running it. |
| `nb_run` | Runs one or more cells, in the order given. |
| `nb_remove` | Removes a cell. |
| `nb_show` | Returns the whole notebook: every cell with code and output. |
| `nb_rerun` | Fresh kernel, then every cell from the top. |

The main agent gets them all. Subagents only get them if their template or the parent gives them.

## How it works

```
nb_add.py, nb_run.py, ...      the tools: each one sends one command
        │
_notebook.py                   packs the command and runs it in the sandbox (through sandbox.exec)
        │
Shared/Notebooks/Engine/client.py   inside the sandbox: starts or stops kernels, or hands the command on
        │
Shared/Notebooks/Engine/kernel.py   one per open notebook: holds the variables and the cells,
                                    and writes the .ipynb file after every change
```

- Each notebook has its own kernel, so two notebooks never mix their variables.
- Every answer ends with an overview of all cells: id, state (`ran [3]`, `not run`, `EDITED since, output is stale`, `error`) and first line. That is how the agent keeps track. The `notebook` skill (`Skills/notebook/SKILL.md`) teaches it how to work with them.
- If you edit an open notebook yourself, the kernel notices before its next step and keeps your changes.
- A cell that runs too long is stopped about 30 seconds before the sandbox's own limit (`MAX_TOOL_TIMEOUT`). The variables are kept.
- Notebooks live in the folders you keep: `common/...` or `<project>/...` (on your machine: `Shared/common/...`, `Shared/<project>/...`). Anywhere else they would be gone when the sandbox stops, so the tools refuse other paths.

## Good to know

- Notebooks need `python3` in the sandbox, e.g. the `python` sandbox. The engine itself only uses Python's standard library.
- The engine lives in `Shared/Notebooks/Engine/`. Every sandbox sees it read-only at `/workspace/Notebooks/Engine/`, so the agent can use it but never change it. Moving it? Change `ENGINE` in `sandbox.py`.
- Stopping the sandbox stops every kernel, and so does a restart by `mount_project` or `unmount_project`. The notebook files stay; the agent opens them again with `nb_open`.
