import notebook

def run(agent, notebook_file, cell_id):
    return notebook.call("run", notebook_file, cell_id=cell_id)

TOOL = {
    "name": "nb_run",
    "description": "Run one notebook cell in its kernel and get its output: printed text, the value of a bare last line (like "
                   "Jupyter), errors with the line that failed, and plots (saved into the notebook). cell_id 'all' runs every "
                   "code cell from the top and stops at the first error, e.g. after nb_restart. A cell running longer than "
                   "the time limit is stopped; the variables are kept.",
    "parameters": {"type": "object",
                   "properties": {"notebook_file": {"type": "string"},
                                  "cell_id": {"type": "string", "description": "a cell id, or all"}},
                   "required": ["notebook_file", "cell_id"]},
}
