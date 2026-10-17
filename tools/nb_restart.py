import notebook

def run(agent, notebook_file):
    return notebook.call("restart", notebook_file)

TOOL = {
    "name": "nb_restart",
    "description": "Restart a notebook's kernel: ALL its variables are gone, the cells stay. Use it when the state got messy "
                   "or to check that the notebook works from the top; then nb_run with cell_id all.",
    "parameters": {"type": "object", "properties": {"notebook_file": {"type": "string"}}, "required": ["notebook_file"]},
}
