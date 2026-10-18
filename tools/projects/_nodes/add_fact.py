from . import _node

def run(agent, fact, source):
    if not agent.graph:
        return _node.NOT_A_NODE
    if not str(fact).strip() or not str(source).strip():
        return "not saved: a fact needs both: what it says, and where it comes from"
    agent.graph.add_fact(agent.node, str(fact).strip(), str(source).strip())
    agent.graph.set_state(agent.node, progress=True)
    return "saved. every node of this run can find it with search_facts"

TOOL = {
    "name": "add_fact",
    "description": "Save a fact for the whole project run, with its source (a URL, a file, or the command that showed "
                   "it). Every node can find it with search_facts, so nobody works it out twice. One fact per call, "
                   "short and exact. Facts are never changed: a newer one that corrects an older one says so.",
    "parameters": {"type": "object",
                   "properties": {"fact": {"type": "string"}, "source": {"type": "string"}},
                   "required": ["fact", "source"]},
}
