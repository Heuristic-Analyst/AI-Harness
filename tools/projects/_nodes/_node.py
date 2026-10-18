# _node.py — what the node tools share. (the _ in front: not a tool, the tool loader skips it)
# these tools only work for a node's agent in a project run: the scheduler (_scheduler.py) loads them, only for its
# nodes, and gives each node's agent agent.graph (the project's graph, see _graph.py) and agent.node (its id).
# every change to the graph goes through these tools, and they check the rules: the sandbox only sees .graph/ read-only.

from .. import _graph as G

NOT_A_NODE = "this tool only works inside a project run, for a node's agent"

def mine(agent, child):
    """None if `child` is one of this node's children, otherwise what is wrong"""
    if not child or G.parent_of(child) != agent.node or child not in agent.graph.ids():
        children = agent.graph.children(agent.node)
        return "'" + str(child) + "' is not one of your children. yours: " + (", ".join(children) or "none")
    return None
