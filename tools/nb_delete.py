import notebook

def run(agent, notebook_file, cell_id):
    return notebook.call("delete", notebook_file, cell_id=cell_id)

TOOL = {
    "name": "nb_delete",
    "description": "Remove one cell from a notebook. Variables it created stay in the kernel until nb_restart.",
    "parameters": {"type": "object",
                   "properties": {"notebook_file": {"type": "string"}, "cell_id": {"type": "string"}},
                   "required": ["notebook_file", "cell_id"]},
}
