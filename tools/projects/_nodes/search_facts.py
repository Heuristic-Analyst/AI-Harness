from . import _node

MAX_HITS = 30

def run(agent, text=""):
    if not agent.graph:
        return _node.NOT_A_NODE
    facts = agent.graph.facts()
    hits = []
    for fact in facts:
        line = fact["fact"] + " | " + fact["source"] + " | " + fact["node"]
        if text.lower() in line.lower():
            hits.append("- " + fact["fact"] + "  (source: " + fact["source"] + ", from " + fact["node"] + ", " + fact["time"] + ")")
    if not hits:
        return "no fact contains '" + text + "' (" + str(len(facts)) + " facts in this run)"
    shown = hits[-MAX_HITS:]                                      # the newest ones
    return str(len(hits)) + " facts" + (", the newest " + str(MAX_HITS) + " shown" if len(hits) > MAX_HITS else "") + ":\n" + "\n".join(shown)

TOOL = {
    "name": "search_facts",
    "description": "Search the facts every node of this project run saved (add_fact), with their sources. Look here "
                   "before you research or work something out: maybe another node knows it already. Empty text = all.",
    "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "upper or lower case doesn't matter"}}},
}
