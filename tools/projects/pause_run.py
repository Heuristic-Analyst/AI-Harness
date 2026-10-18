from . import _graph as G
from config import write_text

def run(agent, project):
    graph = G.Graph(project)
    if not graph.exists():
        return "there is no project run in '" + str(project) + "'"
    write_text(graph.path("pause"), "paused by the user at " + G.now())
    if G.running(project):
        return "pausing: no new shifts start, the ones going on now finish. then the project is free. start_run goes on"
    return "paused. start_run goes on"

TOOL = {
    "name": "pause_run",
    "description": "Pause a project run: no new shifts start, the ones going on finish, then the scheduler stops and the "
                   "project is free again. Nothing is lost: start_run goes on exactly there.",
    "parameters": {"type": "object", "properties": {"project": {"type": "string"}}, "required": ["project"]},
}
