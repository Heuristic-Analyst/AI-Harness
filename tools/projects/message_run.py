import os
from . import _graph as G

def run(agent, project, text, extra_budget=0):
    graph = G.Graph(project)
    if not graph.exists():
        return "there is no project run in '" + str(project) + "'"
    if not str(text).strip():
        return "the message is empty"
    try:
        extra = int(extra_budget or 0)
    except (TypeError, ValueError):
        return "extra_budget is a number of tokens"
    if extra < 0:
        return "extra_budget can't be negative"
    if extra and G.running(project):                              # the scheduler writes the states while it runs: one writer
        return "the budget can only be raised while the run is stopped: pause_run first, then message_run again"
    if extra:
        root = graph.state(G.ROOT)
        graph.set_state(G.ROOT, budget=root["budget"] + extra)
        settings = graph.settings()
        settings["budget"] = settings.get("budget", 0) + extra
        graph.write(graph.path("project.json"), settings)
        graph.log("the user added " + format(extra, ",") + " tokens to the budget")
        text = "[the user added " + format(extra, ",") + " tokens to your budget]\n" + text
    graph.send("user", G.ROOT, text)
    if G.running(project):
        return "sent to the root of " + project + ": it reads it in its next shift"
    if os.path.exists(graph.path("pause")):
        return "sent. the run is paused: start_run lets it go on, and then the root reads it"
    G.start_scheduler(project)                                    # stopped (waiting, or finished): go on, so the root reads it
    return "sent to the root of " + project + ", and the run goes on, so it reads it now. run_status shows how it goes"

TOOL = {
    "name": "message_run",
    "description": "Send a message to the root of a project run: the answer to its question, or a change the user wants "
                   "(new features, things to drop, things to do better). The root reads it in its next shift and changes "
                   "the plan: reopens nodes, adds new ones, cancels others. A stopped or finished run starts again for it. "
                   "extra_budget adds tokens to the run's budget (only while it is stopped or paused), e.g. when it ran out.",
    "parameters": {"type": "object",
                   "properties": {"project": {"type": "string"}, "text": {"type": "string"},
                                  "extra_budget": {"type": "integer", "description": "tokens to add to the budget. default 0"}},
                   "required": ["project", "text"]},
}
