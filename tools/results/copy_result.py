import os
import shutil
import sandbox
from config import SHARED_DIR
from . import _results

def run(agent, file, to, name=None):
    path = _results.resolve(agent, file)
    if not path:
        return _results.not_found(agent, file)
    to = str(to).replace("\\", "/")
    if to.startswith("/workspace/"):                              # "/workspace/common/x" is fine too: it means common/x
        to = to[len("/workspace/"):]
    target = _results.parts_of(to)
    if to.startswith("/") or not target or ".." in target:
        return "the target must be a folder like common or common/data/raw (or your mounted project, e.g. website/data)"
    allowed = sandbox.COMMON + "/..."
    project = sandbox.my_project if sandbox.running_here() else None   # the project only while this instance's sandbox has it
    if project:
        allowed += " or " + project + "/..."
    if target[0] != sandbox.COMMON and target[0] != project:
        return "you can copy into " + allowed + ", nowhere else" + ("" if project else " (no project is mounted right now)")
    name = name or os.path.basename(path)
    if "/" in name or "\\" in name or name in (".", ".."):
        return "name is only a file name, e.g. data.csv: the folder goes into to"
    folder = os.path.join(SHARED_DIR, *target)
    inside = os.path.realpath(os.path.join(SHARED_DIR, target[0])) + os.sep
    if not (os.path.realpath(folder) + os.sep).startswith(inside):   # also through links: it must stay in that folder
        return "that folder is outside " + target[0] + "/"
    destination = os.path.join(folder, name)
    if os.path.exists(destination):
        return "/workspace/" + "/".join(target) + "/" + name + " exists already: pick another name"
    os.makedirs(folder, exist_ok=True)                            # missing folders are created
    shutil.copyfile(path, destination)
    answer = ("copied to /workspace/" + "/".join(target) + "/" + name + " (for the user: Shared/" + "/".join(target) + "/"
              + name + "). work on it in your sandbox, with sandbox_shell or a notebook")
    if not sandbox.running_here():
        answer += ". no sandbox runs right now: open one first"
    return answer

TOOL = {
    "name": "copy_result",
    "description": "Copy one of your result files (results/..., or a subagent's) into a folder your sandbox sees, to work "
                   "on it with code there: Python, grep, a notebook. That beats reading a big file piece by piece. The "
                   "target is common (/workspace/common, shared with every other instance) or any folder in it, and, only "
                   "while your sandbox runs with a project mounted, that project or any folder in it. Missing folders are "
                   "created. An existing file is never replaced.",
    "parameters": {"type": "object",
                   "properties": {"file": {"type": "string", "description": "e.g. results/000042-sandbox_shell.txt"},
                                  "to": {"type": "string", "description": "the folder, e.g. common, common/data/raw, or website/logs"},
                                  "name": {"type": "string", "description": "the file name there. leave out = the same name"}},
                   "required": ["file", "to"]},
}
