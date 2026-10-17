from . import _notebook

def run(agent, path):
    return _notebook.call("show", path)

TOOL = {
    "name": "nb_show",
    "description": "Show a whole open notebook: every cell with its id, state, full source and output. Use it when you're "
                   "unsure what is in it; the short overview after every other notebook call is usually enough.",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
}
