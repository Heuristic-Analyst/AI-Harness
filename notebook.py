# notebook.py — the agent's jupyter notebooks. the tools in tools/nb_*.py all come through here.
# the real work happens INSIDE the sandbox, in notebook_kernel.py: a small program that keeps running there, holds the
# variables (that is what a jupyter "kernel" is) and writes every change into the .ipynb file in Shared/.
# this file only copies that program into the sandbox and hands it one command at a time, through sandbox_shell's way in.

import os
import json
import base64
import sandbox
from config import *

with open(os.path.join(HERE, "notebook_kernel.py"), "rb") as f:   # read once at startup, sent along with every command
    KERNEL = base64.b64encode(f.read()).decode()

def call(cmd, notebook, **args):
    """send one command (add, edit, run, delete, show, restart) to the kernel of one notebook, return its answer"""
    if not notebook.endswith(".ipynb") or notebook.startswith("/") or ".." in notebook.split("/"):
        return "the notebook must be a file name in the shared folder, like analysis.ipynb or work/analysis.ipynb"
    command = dict(args, cmd=cmd, notebook=notebook, timeout=MAX_TOOL_TIMEOUT - 30)   # the kernel stops a slow cell before
    payload = base64.b64encode(json.dumps(command).encode()).decode()                 # sandbox_shell's own limit is hit
    # base64 = only letters and digits, so no quote or $ in the code can confuse bash.
    # the kernel program is written to /tmp each time (it's small), so a sandbox never runs an old copy of it
    script = ("echo " + KERNEL + " | base64 -d > /tmp/notebook_kernel.py && "
              "python3 /tmp/notebook_kernel.py send " + payload)
    answer = sandbox.exec(script)
    if "python3: command not found" in answer:
        return "this sandbox has no python3, so notebooks don't work in it. tell the user (e.g. use the python sandbox)"
    return answer
