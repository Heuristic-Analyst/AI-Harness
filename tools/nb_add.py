import notebook

def run(agent, notebook_file, source, kind="code", after=None, run=False):
    return notebook.call("add", notebook_file, source=source, kind=kind, after=after, run=run)

TOOL = {
    "name": "nb_add",
    "description": "Add a cell to a Jupyter notebook in the shared folder (the file is created if it doesn't exist; the user can "
                   "open it). Notebooks run in the sandbox, in a kernel that keeps every variable between runs, like Jupyter: "
                   "what one cell defines, later cells can use. Returns the new cell's id, its output if run is true, and an "
                   "overview of all cells with their state (ran, not run, EDITED since run, error). Read that overview to know "
                   "where you are. Use one notebook per piece of work; put explanations in markdown cells.",
    "parameters": {"type": "object",
                   "properties": {"notebook_file": {"type": "string", "description": "file name in the shared folder, e.g. analysis.ipynb"},
                                  "source": {"type": "string", "description": "the code or markdown of the cell"},
                                  "kind": {"type": "string", "enum": ["code", "markdown"], "description": "default code"},
                                  "after": {"type": "string", "description": "id of the cell to insert after. leave out = at the end"},
                                  "run": {"type": "boolean", "description": "run it right away. default false"}},
                   "required": ["notebook_file", "source"]},
}
