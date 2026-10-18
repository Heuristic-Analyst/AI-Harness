# _notebook.py — what every nb_* tool next to this file goes through. (the _ in front: not a tool, the tool loader skips it)
# the notebooks themselves run INSIDE the sandbox. their engine lives in the shared folder, and every sandbox sees it read-only:
#   on your machine:     Shared/Notebooks/Engine/kernel.py and client.py
#   inside the sandbox:  /workspace/Notebooks/Engine/...           (mounted by sandbox.py, ENGINE there)
# a tool call = one run of client.py inside the sandbox, with one command. client.py hands it to the notebook's kernel.
# the notebooks live in the folders the sandbox shares with you: common/... or <project>/... (inside: /workspace/...)

import os
import json
import base64
import sandbox
from config import *


def call(cmd, notebook, **args):
    """send one command to the engine in the sandbox, for one notebook. returns the answer as text"""
    if not os.path.isfile(os.path.join(sandbox.engine_dir(), "client.py")):   # checked on your machine, before the sandbox
        return ("the notebook engine is missing: there is no Shared/" + sandbox.ENGINE + "/client.py (and kernel.py). "
                "tell the user, notebooks don't work without it")
    parts = notebook.replace("\\", "/").split("/")
    if not notebook.endswith(".ipynb") or notebook.startswith("/") or ".." in parts:
        return "the notebook must be a path ending in .ipynb, like common/analysis.ipynb, with no .. in it"
    folders = [sandbox.COMMON]                              # the folders that are kept: common, and the project if one is mounted
    allowed = sandbox.COMMON + "/..."
    if sandbox.my_project:
        folders.append(sandbox.my_project)
        allowed += " or " + sandbox.my_project + "/..."
    if len(parts) < 2 or parts[0] not in folders:           # anywhere else it would be gone when the sandbox stops
        return "a notebook must be in a folder the user keeps: " + allowed + ", e.g. " + folders[-1] + "/analysis.ipynb"
    command = dict(args, cmd=cmd, notebook=notebook, timeout=MAX_TOOL_TIMEOUT - 30)   # a slow cell is stopped before
    payload = base64.b64encode(json.dumps(command).encode()).decode()                 # sandbox_shell's own limit is hit
    answer = sandbox.exec("python3 -B /workspace/" + sandbox.ENGINE + "/client.py " + payload)   # -B: no __pycache__ (the engine is read-only)
    if "python3: command not found" in answer:
        return "this sandbox has no python3, so notebooks don't work in it. pick one that has it (check_sandbox)"
    return answer
