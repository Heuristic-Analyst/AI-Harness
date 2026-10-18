from . import _node

def run(agent):
    graph = agent.graph
    if not graph:
        return _node.NOT_A_NODE
    return ("the whole graph (id [status] goal (spent of budget)):\n" + graph.overview() + "\n\nyou are " + agent.node
            + ". left for you: " + format(max(0, graph.available(agent.node, agent.spent)), ",") + " tokens")

TOOL = {
    "name": "node_status",
    "description": "See the whole graph of this project run: every node with its status, goal and budget. Changes nothing.",
    "parameters": {"type": "object", "properties": {}},
}
