from . import _node

def run(agent, child, verdict, note="", extra_budget=0):
    graph = agent.graph
    if not graph:
        return _node.NOT_A_NODE
    problem = _node.mine(agent, child)
    if problem:
        return problem
    state = graph.state(child)
    if verdict == "accept":
        if state["status"] not in ("done", "blocked", "stale"):
            return child + " is " + state["status"] + ": only a finished child can be accepted"
        status = "done" if state["status"] == "stale" else state["status"]
        graph.set_state(child, accepted=True, status=status)
        graph.set_state(agent.node, progress=True)
        graph.log(agent.node + " accepted " + child + ((": " + note) if note else ""))
        return "accepted " + child
    if verdict != "send_back":
        return "verdict is accept or send_back"
    if state["status"] in ("open", "working", "waiting"):
        return child + " is still " + state["status"] + ": wait for it, or send_message to tell it something"
    if state["status"] in ("cancelled", "replaced"):
        return child + " is " + state["status"] + ": create a new node instead"
    if not str(note).strip():
        return "say exactly what is missing or should change: that is what it works from"
    try:
        extra = int(extra_budget or 0)
    except (TypeError, ValueError):
        return "extra_budget is a number of tokens"
    if extra < 0 or extra > graph.available(agent.node, agent.spent):
        return "extra_budget must be between 0 and what you have left: " + format(max(0, graph.available(agent.node, agent.spent)), ",")
    with graph.lock:
        graph.set_state(child, status="open", accepted=False, budget=state["budget"] + extra, idle=0, failures=0, asked=False)
        own = graph.state(agent.node)
        graph.set_state(agent.node, given=own["given"] + extra, progress=True)
        graph.send(agent.node, child, "Your parent sent your result back" + (" with " + format(extra, ",") + " more tokens" if extra else "")
                   + ":\n" + note)
        graph.mark_stale(child)                                   # what depends on it has to be checked again
    return ("sent back to " + child + ": it goes on from its checkpoint with your note. siblings that depend on it are "
            "stale now: check them again when they are done")

TOOL = {
    "name": "check_result",
    "description": "Judge one of your children's results, after going through its done-when points and the files it "
                   "points to. accept: it counts as done (a BLOCKED child too, if its partial result is enough for you). "
                   "send_back: it works on it again from its checkpoint, with your note saying exactly what is missing or "
                   "should change, and extra budget if it ran out. Also how you change a finished child later. Siblings "
                   "that depend on it become stale: check them again.",
    "parameters": {"type": "object",
                   "properties": {"child": {"type": "string", "description": "its id, e.g. T1.3"},
                                  "verdict": {"type": "string", "enum": ["accept", "send_back"]},
                                  "note": {"type": "string", "description": "for send_back: exactly what is missing or should change"},
                                  "extra_budget": {"type": "integer", "description": "send_back: more tokens for it, from yours. default 0"}},
                   "required": ["child", "verdict"]},
}
