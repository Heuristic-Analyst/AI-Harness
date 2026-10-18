from . import _node

def run(agent, nodes):
    if not agent.graph:
        return _node.NOT_A_NODE
    ids, problem = agent.graph.create(agent.node, nodes, extra_spent=agent.spent)
    if problem:
        return "nothing was created: " + problem
    lines = []
    for id in ids:
        node = agent.graph.node(id)
        waits = " (starts after " + ", ".join(node["depends_on"]) + ")" if node["depends_on"] else " (starts right away)"
        lines.append(id + waits + ": " + node["goal"])
    return ("created:\n" + "\n".join(lines) + "\nleft for you: " + format(max(0, agent.graph.available(agent.node, agent.spent)), ",")
            + " tokens. end your shift when you have nothing else to do meanwhile: you are woken when they need you")

TOOL = {
    "name": "create_nodes",
    "description": "Split your node: create child nodes, each a task of its own that the scheduler starts by itself. Use it "
                   "when your task is too big for your budget, or made of parts that can be done apart. Each child gets "
                   "a part of your budget. They are numbered on from your id (your briefing says the next number). "
                   "depends_on names siblings whose result a child needs first: it starts after them. Then end your shift.",
    "parameters": {"type": "object",
                   "properties": {"nodes": {"type": "array", "items": {"type": "object",
                       "properties": {"goal": {"type": "string", "description": "what this child must do or find out"},
                                      "why": {"type": "string", "description": "why you need it: so it knows what matters"},
                                      "done_when": {"type": "array", "items": {"type": "string"},
                                                    "description": "points someone can check, e.g. 'tests pass', '3 sources'"},
                                      "budget": {"type": "integer", "description": "tokens for it and all it splits into"},
                                      "depends_on": {"type": "array", "items": {"type": "string"},
                                                     "description": "ids of siblings it needs first, e.g. T1.2.1. leave out if none"}},
                       "required": ["goal", "why", "done_when", "budget"]}}},
                   "required": ["nodes"]},
}
