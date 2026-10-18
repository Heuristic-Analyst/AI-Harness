import os
from . import _graph as G
from config import read_text

def run(agent, project):
    graph = G.Graph(project)
    if not graph.exists():
        return "there is no project run in '" + str(project) + "'"
    settings = graph.settings()
    root = graph.state(G.ROOT)
    spent = 0
    for id in graph.ids():
        spent += graph.state(id)["spent"]
    if G.running(project):
        how = "running" + (", pausing after the shifts going on now" if os.path.exists(graph.path("pause")) else "")
    elif os.path.exists(graph.path("pause")):
        how = "paused (start_run goes on)"
    elif root["status"] in ("done", "blocked"):
        how = "finished: " + root["status"]
    elif root["status"] == "waiting" and root["asked"]:
        how = "stopped, waiting for the user's answer (message_run)"
    else:
        how = "stopped (start_run goes on)"
    lines = ["run of " + project + ": " + how,
             "goal: " + settings.get("goal", ""),
             "budget: " + format(spent, ",") + " of " + format(settings.get("budget", 0), ",") + " tokens used", "",
             "nodes (id [status] goal (spent of budget)):", graph.overview()]
    questions = graph.messages("user")
    if questions:
        lines += ["", "the root's messages to the user (newest last):"]
        for path in questions[-3:]:
            sender, time, text = graph.message(path)
            lines.append("- " + time + ": " + text)
        if root["status"] == "waiting" and root["asked"]:
            lines.append("(the last one is not answered yet)")
    if root["status"] in ("done", "blocked"):
        lines += ["", "the root's result:", read_text(os.path.join(graph.folder(G.ROOT), "result.md"))[:3000]]
    log = read_text(graph.path("run.log")).split("\n")
    lines += ["", "the scheduler, last lines:"] + log[-8:]
    return "\n".join(lines)

TOOL = {
    "name": "run_status",
    "description": "See how a project run goes: running, paused or finished, the budget used, every node with its "
                   "status, the root's questions to the user, and the final result once there is one. Changes nothing.",
    "parameters": {"type": "object", "properties": {"project": {"type": "string"}}, "required": ["project"]},
}
