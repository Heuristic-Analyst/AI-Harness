import notebook

def run(agent, notebook_file, cell_id, source, run=False):
    return notebook.call("edit", notebook_file, cell_id=cell_id, source=source, run=run)

TOOL = {
    "name": "nb_edit",
    "description": "Replace the whole source of one notebook cell (pass the complete new code, not only the change). An edited "
                   "cell that isn't run again is marked EDITED in the overview: its output is stale. Set run to true to run it "
                   "right away. Returns the output (if run) and the overview of all cells.",
    "parameters": {"type": "object",
                   "properties": {"notebook_file": {"type": "string"},
                                  "cell_id": {"type": "string", "description": "the id from the overview, e.g. 3f9a1c0b"},
                                  "source": {"type": "string", "description": "the complete new source"},
                                  "run": {"type": "boolean", "description": "run it right away. default false"}},
                   "required": ["notebook_file", "cell_id", "source"]},
}
