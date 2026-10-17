# _notebook.py — what every nb_* tool next to this file goes through. (the _ in front: not a tool, the tool loader skips it)
# the notebooks themselves run INSIDE the sandbox. their engine lives in the shared folder, so the sandbox can see it:
#   on your machine:     Shared/Notebook/Engine/kernel.py and client.py
#   inside the sandbox:  /workspace/Notebook/Engine/...
# a tool call = one run of client.py inside the sandbox, with one command. client.py hands it to the notebook's kernel.

import os
import json
import base64
import sandbox
from config import *

ENGINE = "Notebook/Engine"                                 # the engine's folder inside the shared folder. move it? change this

def call(cmd, notebook, **args):
    """send one command to the engine in the sandbox, for one notebook. returns the answer as text"""
    if not os.path.isfile(os.path.join(SHARED_DIR, ENGINE, "client.py")):   # checked on your machine, before the sandbox
        return ("the notebook engine is missing: there is no Shared/" + ENGINE + "/client.py (and kernel.py). "
                "tell the user, notebooks don't work without it")
    if not notebook.endswith(".ipynb") or notebook.startswith("/") or ".." in notebook.replace("\\", "/").split("/"):
        return "the notebook must be a path inside the shared folder ending in .ipynb, like analysis.ipynb or work/sales.ipynb"
    command = dict(args, cmd=cmd, notebook=notebook, timeout=MAX_TOOL_TIMEOUT - 30)   # a slow cell is stopped before
    payload = base64.b64encode(json.dumps(command).encode()).decode()                 # sandbox_shell's own limit is hit
    answer = sandbox.exec("python3 -B /workspace/" + ENGINE + "/client.py " + payload)   # -B: no __pycache__ in Shared/
    if "python3: command not found" in answer:
        return "this sandbox has no python3, so notebooks don't work in it. tell the user (the python sandbox has it)"
    return answer
