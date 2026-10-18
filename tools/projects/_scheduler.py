# _scheduler.py — the scheduler of a project run. started by the start_run tool, in the background, as its own program:
# `python -m tools.projects._scheduler <project>` from the program folder. it keeps going when you close the chat.
# one per project (the lock run-<project>). starts with _: the tool loader skips it, it is no tool.
# no model, no thinking in the loop: it only follows the rules of _graph.py, round after round:
#   1. waiting nodes with news (a message, or children that can't go on without them) open again
#   2. every open node whose dependencies are done gets a shift, up to RUN_PARALLEL at the same time
#   3. a shift = a fresh agent for that node (NodeAgent, below): it reads its briefing, works, and leaves everything in files
# it ends when the root is done or blocked, when it waits for your answer, or when you paused it. start_run (or
# message_run) starts it again, and it goes on exactly where the files say: also after a crash.
# it is an instance like main.py: its own sandbox, with the project mounted, so no one else can mount it meanwhile.

import os
import sys
import time
import atexit
import threading
import importlib.util
import litellm
from config import *
import locks
import sandbox
import agent as A
from . import _graph as G

A.STREAM = False                                                  # nobody watches a node's reply arrive: it comes in one
                                                                  # piece, with the provider's count of the tokens it used

# the node tools, in _nodes/: the tool loader of agent.py skips that folder (the _ in front), so the main agent and its
# subagents never even see them. only here, in the scheduler's own program, they are added to the tools, for the nodes
NODES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_nodes")
NODE_ONLY = []                                                    # their names
for file in sorted(os.listdir(NODES_DIR)):
    if not file.endswith(".py") or file.startswith("_"):          # _node.py: their shared helper, not a tool
        continue
    spec = importlib.util.spec_from_file_location("tools.projects._nodes." + file[:-3], os.path.join(NODES_DIR, file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    name = module.TOOL["name"]
    if name in A.TOOLS:
        raise SystemExit("two tools are called '" + name + "': tools/projects/_nodes/" + file + " and " + A.FOUND_IN[name])
    A.TOOLS[name] = {"type": "function", "function": module.TOOL}
    A.FUNCTIONS[name] = module.run
    A.FOUND_IN[name] = "tools/projects/_nodes/" + file
    NODE_ONLY.append(name)

NODE_INSTRUCTIONS = "You are a careful, thorough worker in a long project, run by a small multi-agent system."

NODE_RULES = """
You work on ONE node of a project run: a long project, split into a graph of nodes. A node is one task, and you are its
worker for one shift. The plan and the state live in files, not in your head: what you don't write down is gone when your
shift ends. You never talk to the user directly. Your parent is the node above you (the root's parent is the user).
Your first message is your briefing: your goal, why it matters, your done-when points, your budget, your children and
their results, and new messages. In a shift, do what fits:
- Do the work yourself if it fits your budget. Work in the project folder with your tools. Write things down as you go:
  files in the project for the work, add_fact for facts others can use (search_facts first: maybe it is known already).
- Split if it is too big, or made of parts that can be done apart: create_nodes, with at most """ + str(NODE_CHILDREN) + """
  children. Give each a clear goal, why, done-when points someone can check, a budget, and depends_on where one needs
  another's result. Then end your shift: you are woken when they are done, or when they need you.
- Check what your children did when you are woken: go through every done-when point of each result, and look at the
  files it points to. check_result accepts it, or sends it back with exactly what is missing (and more budget, if it ran
  out). cancel_node drops one that isn't needed anymore, or was replaced by another.
- Finish with write_result: your report (start with DONE, or BLOCKED and why), one answer per done-when point, and your
  final checkpoint (what you did, decisions and why, facts with sources, files, what a later change must know).
- Ask only what you can't settle with a reasonable assumption: send_message to 'parent', then end your shift.
Your report stays under """ + format(REPORT_LIMIT, ",") + """ characters: details go into files, and the report points to them. Say where every
claim comes from. End every shift with a short final message: what you did in it."""

NODE_TOOLS = ["calculate", "load_skill", "sandbox_shell", "read_result", "search_result", "copy_result",
              "nb_create", "nb_open", "nb_close", "nb_add", "nb_edit", "nb_run", "nb_remove", "nb_show", "nb_rerun"] + NODE_ONLY

WRAP_UP = """BUDGET USED UP. Your shift ends now, without tools. Write your report for your parent: start with
"BLOCKED: out of budget", then what is done, what is missing, and roughly how many more tokens you would need."""


class OutOfBudget(Exception):
    """a node's shift used up its budget. raised between two model calls, never in the middle of one"""


class NodeAgent(A.Agent):
    """the agent of one node for one shift: an Agent (agent.py) like a subagent, with four differences, all in here:
    the node rules instead of the subagent rules, the node tools, a token budget, and a wrap-up when the budget is gone"""

    def __init__(self, graph, id, folder, log, budget):
        A.Agent.__init__(self, id, NODE_INSTRUCTIONS, NODE_TOOLS, "all", folder, depth=2, log=log)
        self.graph = graph                                        # the node tools work with these two
        self.node = id
        self.budget = budget                                      # tokens for this shift
        self.spent = 0                                            # tokens its model calls used so far
        self.warned = False                                       # told already that its budget is nearly used up

    def build_system(self):
        """the system prompt of a subagent, with the node rules where the subagent rules are"""
        return A.Agent.build_system(self).replace(A.SUBAGENT_RULES, NODE_RULES)

    def count(self, response):
        """add what a model call used: the provider's own count if it sent one, an estimate if not"""
        usage = getattr(response, "usage", None)
        total = getattr(usage, "total_tokens", None) if usage else None
        if not total:
            content = response.choices[0].message.content or ""
            total = self.tokens() + len(content) // 4             # what was sent + what came back, roughly
        self.spent += total

    def show(self, response):
        """agent.py calls this with every reply of the model: count it, then go on as usual"""
        self.count(response)
        return A.Agent.show(self, response)

    def make_room(self):
        """agent.py calls this before every model call: the budget used up? then the shift stops here (OutOfBudget)"""
        A.Agent.make_room(self)
        if self.budget is not None and self.spent >= self.budget:
            raise OutOfBudget(self.node + " used its budget of " + format(self.budget, ",") + " tokens")

    def run_tools(self, reply):
        """after the tools of a reply ran: nearly out of budget (BUDGET_WARNING)? say so once, at the end of the last
        tool result, so the agent reads it next"""
        A.Agent.run_tools(self, reply)
        if self.budget is None or self.warned or self.spent < BUDGET_WARNING * self.budget:
            return
        self.warned = True
        note = ("\n\n[budget: " + format(self.spent, ",") + " of " + format(self.budget, ",") + " tokens used. finish now: "
                "write_result, or create_nodes for what is left, or write_result with BLOCKED and what is done]")
        if self.messages[-1]["role"] == "tool":
            self.messages[-1]["content"] += note
            self.record("budget warning", spent=self.spent, budget=self.budget)

    def write_checkpoint(self, emergency):
        """agent.py's checkpoint call doesn't count its tokens: this adds an estimate (it sends the whole context)"""
        self.spent += self.tokens()
        return A.Agent.write_checkpoint(self, emergency)

    def wrap_up_report(self):
        """the budget is used up: one last request, answered without tools, for the report. None if it failed"""
        try:
            response = litellm.completion(api_key=API_KEY, model=MODEL, reasoning_effort=EFFORT,
                                          messages=self.messages + [{"role": "user", "content": WRAP_UP}],
                                          tools=self.tools or None,      # some models need the tools listed when the
                                          tool_choice="none" if self.tools else None)   # history has tool calls. none may be used
            self.count(response)
            text = response.choices[0].message.content
        except Exception as e:
            self.say("\n[the wrap-up report failed: " + type(e).__name__ + ": " + str(e) + "]")
            return None
        if not text or not text.strip():
            return None
        self.say("\nWRAP-UP REPORT:\n" + text)
        return text


def shift(graph, id):
    """one shift on one node: a fresh agent, its briefing, its work. whatever happens, the node ends in a clear state"""
    state = graph.state(id)
    folder = graph.folder(id)
    os.makedirs(folder, exist_ok=True)
    log = open(os.path.join(folder, "transcript.md"), "a", encoding="utf-8")   # for you: watch it with tail -f
    log.write("\n\n# " + id + ", shift " + str(state["shifts"]) + " (" + G.now() + ")\n")
    reserve = int(BUDGET_RESERVE * state["budget"])
    agent = NodeAgent(graph, id, folder, log, max(0, graph.available(id) - reserve))   # the reserve is kept back for the wrap-up
    failed = False
    try:
        agent.ask(graph.briefing(id, agent.budget))
    except OutOfBudget:
        wrap_up(graph, agent, id)
    except Exception as e:                                        # the model or the connection failed
        failed = True
        graph.log(id + " shift failed: " + type(e).__name__ + ": " + str(e))
        failures = graph.state(id).get("failures", 0) + 1
        graph.set_state(id, failures=failures)
        if failures >= 3:                                         # three times in a row: its parent has to decide
            graph.finish(id, "BLOCKED: the model failed three times in a row (" + type(e).__name__ + ": " + str(e)[:200]
                         + "). Last checkpoint: " + os.path.relpath(os.path.join(folder, "checkpoint.md"), graph.root))
    finally:
        agent.close()
        log.close()
        with graph.lock:
            state = graph.state(id)
            graph.set_state(id, spent=state["spent"] + agent.spent)
            settle(graph, id, failed)

def settle(graph, id, failed=False):
    """after a shift: where does the node stand? done/blocked stay. otherwise: waiting, or open again"""
    state = graph.state(id)
    if state["status"] in ("done", "blocked", "cancelled", "replaced"):
        return
    if failed:
        graph.set_state(id, status="open")                        # the model failed, not the node: try again, no idle count
        return
    moving = False
    for child in graph.children(id):
        if graph.can_move(child):
            moving = True
    if state["asked"] or moving:
        graph.set_state(id, status="waiting", progress=False, idle=0)
    elif state["progress"]:
        graph.set_state(id, status="open", progress=False, idle=0, failures=0)   # it did something: on in a new shift
    else:
        idle = state["idle"] + 1
        graph.set_state(id, status="open", idle=idle)
        if idle >= IDLE_SHIFTS:
            graph.finish(id, "BLOCKED: " + str(idle) + " shifts in a row without progress (no result, no split, no "
                         "message). Its checkpoint and transcript are in its folder.")

def wrap_up(graph, agent, id):
    """the budget is used up: with the reserve, the agent writes its checkpoint and a report. if even that fails, the
    scheduler writes the report itself, so the parent always gets one"""
    graph.log(id + " is out of budget: wrap-up")
    agent.budget = None                                           # the reserve is for this
    agent.write_checkpoint(True)
    report = agent.wrap_up_report()
    if not report:
        report = ("BLOCKED: out of budget, and no report could be written. Last checkpoint: "
                  + os.path.relpath(os.path.join(graph.folder(id), "checkpoint.md"), graph.root)
                  + ", details: the log next to it")
    if not report.strip().upper().startswith("BLOCKED"):
        report = "BLOCKED: out of budget.\n" + report
    graph.finish(id, report)


def main(project):
    locks.start()
    atexit.register(locks.stop)                                   # runs last: every lock is given back
    atexit.register(sandbox.shutdown)
    if not locks.take("run-" + project):
        print("a run of " + project + " is going already")
        return
    graph = G.Graph(project)
    if not graph.exists():
        print("there is no project run in " + project + ": start_run sets one up")
        return
    sandbox.cleanup()
    answer = sandbox.open_sandbox(graph.settings().get("sandbox", ""), project)
    if not answer.startswith("running"):
        graph.log("the scheduler could not start: " + answer)
        return
    graph.log("scheduler started (" + INSTANCE + ")")
    graph.recover()                                               # nodes a crash left 'working' go on from their checkpoint
    threads = {}                                                  # node id -> the thread of its shift
    while True:
        for id in list(threads):                                  # shifts that ended
            if not threads[id].is_alive():
                del threads[id]
        for id in graph.update():
            graph.log(id + " opens: something new for it")
        root = graph.state(G.ROOT)
        if root["status"] in ("done", "blocked") and not threads and not graph.unread(G.ROOT):
            graph.log("the run is " + root["status"] + ": " + root["note"])
            break
        paused = os.path.exists(graph.path("pause"))
        ready = []
        if not paused:
            for id in graph.ids():
                if id not in threads and graph.ready(id):
                    ready.append(id)
        for id in ready:
            if len(threads) >= RUN_PARALLEL:
                break
            state = graph.state(id)
            graph.set_state(id, status="working", shifts=state["shifts"] + 1, progress=False)
            graph.log(id + " shift " + str(state["shifts"] + 1))
            threads[id] = threading.Thread(target=shift, args=(graph, id))
            threads[id].start()
        if not threads and not ready:
            if paused:
                graph.log("paused")
            elif root["status"] == "waiting" and root["asked"]:
                graph.log("waiting for your answer (message_run). the scheduler stops until then")
            else:
                graph.log("nothing can go on, and nothing waits for you: stopped. run_status shows where it stands")
            break
        time.sleep(1)
    graph.log("scheduler stopped")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m tools.projects._scheduler <project>   (start_run normally starts it for you)")
    else:
        main(sys.argv[1])
