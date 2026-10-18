from config import REPORT_LIMIT
from .. import _graph as G
from . import _node

def run(agent, report, checkpoint, answers=None):
    graph = agent.graph
    if not graph:
        return _node.NOT_A_NODE
    if graph.state(agent.node)["status"] != "working":
        return "not saved: your node is " + graph.state(agent.node)["status"] + " now (its parent changed it): end your shift"
    report = str(report or "").strip()
    first = report.split(None, 1)[0].strip("*:#").upper() if report else ""
    if first not in ("DONE", "BLOCKED"):
        return "not saved: the report starts with DONE, or BLOCKED and why"
    if len(report) > REPORT_LIMIT:
        return ("not saved: the report has " + format(len(report), ",") + " characters, at most " + format(REPORT_LIMIT, ",")
                + ". put the details into files and point to them")
    if not str(checkpoint or "").strip():
        return "not saved: the final checkpoint is missing: what you did, decisions, facts with sources, files, notes for later"
    points = graph.node(agent.node)["done_when"]
    answers = answers or []
    if first == "DONE":
        if len(answers) != len(points):
            return ("not saved: give one answer per done-when point, in order: " + str(len(points)) + " points, "
                    + str(len(answers)) + " answers")
        for answer in answers:
            if not str(answer).strip():
                return "not saved: one of the answers is empty"
        open_children = []
        for child in graph.children(agent.node):
            state = graph.state(child)
            if state["status"] in ("cancelled", "replaced"):
                continue
            if not state["accepted"]:
                open_children.append(child + " (" + state["status"] + ", not accepted)")
        if open_children:
            return ("not saved: a DONE needs every child accepted (check_result) or cancelled (cancel_node). still open: "
                    + ", ".join(open_children))
    elif len(answers) != len(points):
        answers = None                                            # BLOCKED: answers only if all are there
    graph.finish(agent.node, report, checkpoint, answers)
    if agent.node == G.ROOT:
        return "saved. this was the root: the project run is " + ("finished" if first == "DONE" else "blocked") + ". end your shift"
    return "saved: your parent checks it next. end your shift with a short final message"

TOOL = {
    "name": "write_result",
    "description": "Finish your node. Three parts: the report for your parent (starts with DONE, or BLOCKED and why; "
                   "short, details in files it points to, sources for every claim), one answer per done-when point (in "
                   "order: how each one is met), and your final checkpoint (what you did, decisions and why, facts with "
                   "sources, the files that matter, and what a later change must know). A DONE needs every child "
                   "accepted or cancelled first.",
    "parameters": {"type": "object",
                   "properties": {"report": {"type": "string"},
                                  "checkpoint": {"type": "string"},
                                  "answers": {"type": "array", "items": {"type": "string"},
                                              "description": "one per done-when point, in order"}},
                   "required": ["report", "checkpoint"]},
}
