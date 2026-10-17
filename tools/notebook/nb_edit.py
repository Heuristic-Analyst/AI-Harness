from . import _notebook

def run(agent, path, cell_id, source, run=False):
    return _notebook.call("edit", path, cell_id=cell_id, source=source, run=run)

TOOL = {
    "name": "nb_edit",
    "description": "Replace the whole source of one cell (pass the complete new code, not only the change). Set run to "
                   "true to run it right away. An edited cell that isn't run again is marked EDITED in the overview: "
                   "its output is stale.",
    "parameters": {"type": "object",
                   "properties": {"path": {"type": "string"},
                                  "cell_id": {"type": "string", "description": "the id from the overview, e.g. 3f9a1c0b"},
                                  "source": {"type": "string", "description": "the complete new source"},
                                  "run": {"type": "boolean", "description": "run it right away. default false"}},
                   "required": ["path", "cell_id", "source"]},
}
