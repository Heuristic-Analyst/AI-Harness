import notebook

def run(agent, notebook_file):
    return notebook.call("show", notebook_file)

TOOL = {
    "name": "nb_show",
    "description": "Show a whole notebook: every cell with its id, state, full source and output. Use it when you open a "
                   "notebook you haven't seen in this conversation, or when you're unsure what is in it. It also opens an "
                   "existing .ipynb from the shared folder.",
    "parameters": {"type": "object", "properties": {"notebook_file": {"type": "string"}}, "required": ["notebook_file"]},
}
