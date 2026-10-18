# _results.py — what read_result, search_result and copy_result share. (the _ in front: not a tool, the tool loader skips it)
# an agent's long tool results are files in its folder: results/000042-sandbox_shell.txt (see agent.py).
# an agent may use its own result files, and those of its subagents, all the way down:
#   results/000042-sandbox_shell.txt                          its own
#   agents/20261018-19-50-01-worker-1/results/000003-...txt   one of its subagent's (the path is in the subagent's report)
# never its parent's, never a sibling's, and nothing else in the folder (the log, the checkpoint). the path is checked,
# never trusted: everything it names must really lie inside the agent's own folder.

import os

def parts_of(file):
    """'results/x.txt' -> ['results', 'x.txt']. backslashes count as slashes, empty and '.' parts are dropped"""
    parts = []
    for part in str(file).replace("\\", "/").split("/"):
        if part not in ("", "."):
            parts.append(part)
    return parts

def is_result_path(parts):
    """results/<file>, or agents/<x>/results/<file>, or agents/<x>/agents/<y>/results/<file>, ..."""
    if len(parts) < 2 or parts[-2] != "results" or ".." in parts:
        return False
    position = 0
    while position < len(parts) - 2:                              # in front of results/: pairs of agents/<name>
        if parts[position] != "agents" or position + 1 >= len(parts) - 2:
            return False
        position += 2
    return True

def resolve(agent, file):
    """the real path of one of the agent's result files, or None if it isn't one"""
    parts = parts_of(file)
    if not is_result_path(parts):
        return None
    path = os.path.join(agent.folder, *parts)
    inside = os.path.realpath(agent.folder) + os.sep              # also through links: it must really be in the agent's folder
    if not os.path.realpath(path).startswith(inside) or not os.path.isfile(path):
        return None
    return path

def all_results(agent):
    """every result file the agent may use, as it names them: results/..., agents/.../results/..."""
    found = []
    for folder, subfolders, files in os.walk(agent.folder):
        subfolders.sort()
        relative = os.path.relpath(folder, agent.folder)
        parts = parts_of(relative)
        for file in sorted(files):
            if is_result_path(parts + [file]):
                found.append("/".join(parts + [file]))
    return found

def not_found(agent, file):
    """the answer for a file that isn't one of the agent's results: what there is instead"""
    files = all_results(agent)
    if not files:
        return "no result file '" + str(file) + "'. you have no result files yet"
    shown = files[-20:]                                           # the newest 20, the list could be long
    return ("no result file '" + str(file) + "'. yours" + (" (the last 20)" if len(files) > 20 else "") + ":\n"
            + "\n".join(shown))
