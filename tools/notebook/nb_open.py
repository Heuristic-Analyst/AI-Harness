from . import _notebook

def run(agent, path):
    return _notebook.call("open", path)

TOOL = {
    "name": "nb_open",
    "description": "Open an existing notebook (.ipynb) in common/ or in the mounted project and show all of it: every cell with id, state, "
                   "source and output. Opening starts a fresh kernel with no variables: outputs in the file are from "
                   "earlier runs, so run the cells you need (or nb_rerun for all). Already open? Then its variables are "
                   "kept and you just get the view. Needed after the sandbox restarted (also mount_project and unmount_project restart it), because that stops every kernel.",
    "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "e.g. common/analysis.ipynb"}},
                   "required": ["path"]},
}
