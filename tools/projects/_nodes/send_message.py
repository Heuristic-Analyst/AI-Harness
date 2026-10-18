from .. import _graph as G
from . import _node

def run(agent, to, text):
    graph = agent.graph
    if not graph:
        return _node.NOT_A_NODE
    if not str(text).strip():
        return "the message is empty"
    if to == "parent":
        target = G.parent_of(agent.node) or "user"               # the root's parent is the user
        graph.send(agent.node, target, text)
        graph.set_state(agent.node, asked=True, progress=True)
        return ("sent to " + ("the user" if target == "user" else "your parent " + target)
                + ". end your shift: you are woken when the answer comes")
    problem = _node.mine(agent, to)
    if problem:
        return problem + " (or 'parent')"
    graph.send(agent.node, to, text)
    graph.set_state(agent.node, progress=True)
    status = graph.state(to)["status"]
    if status in ("done", "blocked", "stale"):
        return "sent. " + to + " is " + status + ": it only reads it when it works again. to change its result, use check_result with send_back"
    return "sent to " + to + ": it reads it in its next shift"

TOOL = {
    "name": "send_message",
    "description": "Send a message: to 'parent' (a question you can't settle yourself: then end your shift, you are woken "
                   "with the answer; the root's parent is the user), or to one of your children by id (an answer to its "
                   "question, or something it needs to know).",
    "parameters": {"type": "object",
                   "properties": {"to": {"type": "string", "description": "'parent', or a child's id"},
                                  "text": {"type": "string"}},
                   "required": ["to", "text"]},
}
