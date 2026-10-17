from . import _notebook                                       # the helper next to this file

def run(agent, path):
    return _notebook.call("create", path)

TOOL = {
    "name": "nb_create",
    "description": "Create a new Jupyter notebook (.ipynb) in the shared folder and open it. Notebooks run in the sandbox, in "
                   "a kernel that keeps every variable between runs, like Jupyter: what one cell defines, later cells can use. "
                   "Every change is saved to the file at once, so the user can open it any time. Every notebook answer ends "
                   "with an overview of all cells: id, and state (ran [n], not run, EDITED since = output is stale, error). "
                   "Read it to know where you are. Tip: make the first cell a markdown cell with the goal, the plan and "
                   "what is done, and keep it up to date. Notebook calls for the same notebook in one reply may run in any "
                   "order: when order matters, make them in separate replies.",
    "parameters": {"type": "object",
                   "properties": {"path": {"type": "string", "description": "inside the shared folder, ending in .ipynb, "
                                           "e.g. analysis.ipynb or sales/report.ipynb (folders are created)"}},
                   "required": ["path"]},
}
