from . import _node

def run(agent, child, reason, replaced_by=None):
    graph = agent.graph
    if not graph:
        return _node.NOT_A_NODE
    problem = _node.mine(agent, child)
    if problem:
        return problem
    if graph.state(child)["status"] in ("cancelled", "replaced"):
        return child + " is " + graph.state(child)["status"] + " already"
    if not str(reason).strip():
        return "say why: it stays in the graph, with your reason"
    if replaced_by:
        problem = _node.mine(agent, replaced_by)
        if problem or replaced_by == child:
            return "replaced_by must be another of your children"
    with graph.lock:
        status = "replaced" if replaced_by else "cancelled"
        graph.set_state(child, status=status, replaced_by=replaced_by, note=reason, accepted=False)
        for below in graph.descendants(child):                    # everything below it goes with it
            if graph.state(below)["status"] not in ("cancelled", "replaced"):
                graph.set_state(below, status="cancelled", note="its ancestor " + child + " was " + status)
        graph.set_state(agent.node, progress=True)
        graph.log(agent.node + ": " + child + " " + status + (" by " + replaced_by if replaced_by else "") + ": " + reason)
    return child + " is " + status + ", with everything below it. it stays in the graph, with your reason"

TOOL = {
    "name": "cancel_node",
    "description": "Drop one of your children (and everything below it) because it isn't needed anymore, or because "
                   "another child replaces it (replaced_by). Nothing is deleted: it stays in the graph with your reason. "
                   "A shift running on it right now can't save its result anymore. Budget given to it is not returned.",
    "parameters": {"type": "object",
                   "properties": {"child": {"type": "string"},
                                  "reason": {"type": "string"},
                                  "replaced_by": {"type": "string", "description": "the child that replaces it, if one does"}},
                   "required": ["child", "reason"]},
}
