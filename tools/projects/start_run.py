import os
import shutil
from . import _graph as G
import sandbox
from config import NODE_MIN_BUDGET

def run(agent, project, goal=None, done_when=None, budget=None, sandbox_name=None, plan=None):
    if project not in sandbox.projects():
        return "there is no project called '" + str(project) + "'. create_project makes one, check_projects lists them"
    if G.running(project):
        return "a run of " + project + " is going already. run_status shows where it stands"
    who = sandbox.holder(project)
    if who == "you":
        return project + " is mounted in your sandbox: unmount_project first. the run needs the project for itself"
    if who:
        return project + " is mounted by another instance right now. a run needs the project for itself"
    graph = G.Graph(project)
    if graph.exists():                                            # a run that stopped (finished, paused, waiting): go on
        if os.path.exists(graph.path("pause")):
            os.remove(graph.path("pause"))
        G.start_scheduler(project)
        note = ". (it keeps its own goal: to change something, use message_run)" if goal else ""
        return "the run of " + project + " goes on where it stopped" + note + ". run_status shows how it goes"
    if not str(goal or "").strip():
        return "a new run needs a goal"
    if not isinstance(done_when, list) or not done_when:
        return "a new run needs done_when: points someone can check, e.g. 'tests pass', 'report.md exists'"
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        return "a new run needs a budget: tokens for the whole project, e.g. 2000000"
    if budget < 5 * NODE_MIN_BUDGET:
        return "a budget below " + format(5 * NODE_MIN_BUDGET, ",") + " tokens is too small for a project run"
    if sandbox_name not in sandbox.names():
        return "pick the sandbox the run works in: " + ", ".join(sandbox.names()) + " (check_sandbox shows what is in them)"
    points = []
    for point in done_when:
        points.append(str(point).strip())
    graph.write(graph.path("project.json"), {"goal": str(goal).strip(), "done_when": points, "budget": budget,
                                              "sandbox": sandbox_name, "created": G.now()})
    graph.add_node(G.ROOT, str(goal).strip(), "the user's goal for this project", points, budget, [], "user")
    if plan:
        ids, problem = graph.create(G.ROOT, plan, by="user")
        if problem:
            shutil.rmtree(graph.root)                             # nothing half set up stays behind
            return "nothing was started, the plan has a problem: " + problem
        graph.set_state(G.ROOT, status="waiting")                 # the root is woken when its children need it
    graph.log("run set up: " + str(goal).strip()[:100])
    G.start_scheduler(project)
    return ("started the run of " + project + " in the background. it keeps going when the chat is closed. run_status "
            "shows how it goes, message_run reaches its root, pause_run pauses it")

TOOL = {
    "name": "start_run",
    "description": "Start a project run: a long project, worked on in the background as a graph of nodes, until its "
                   "done-when points are met. Load the project-run skill first: it says how to get goal, done-when and "
                   "budget right with the user. The project must exist and not be mounted (unmount_project first). For a "
                   "project with a run already (finished, paused, waiting for an answer), it just goes on: then only "
                   "project is needed.",
    "parameters": {"type": "object",
                   "properties": {"project": {"type": "string"},
                                  "goal": {"type": "string", "description": "what the project must achieve, in a few sentences"},
                                  "done_when": {"type": "array", "items": {"type": "string"},
                                                "description": "points someone can check when it is finished"},
                                  "budget": {"type": "integer", "description": "tokens for the whole run, e.g. 2000000"},
                                  "sandbox_name": {"type": "string", "description": "the sandbox it works in, e.g. python"},
                                  "plan": {"type": "array", "items": {"type": "object"},
                                           "description": "optional: the first level of the plan, as create_nodes takes it "
                                                          "(goal, why, done_when, budget, depends_on). leave out = the root plans itself"}},
                   "required": ["project"]},
}
