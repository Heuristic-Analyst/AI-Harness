# _graph.py — the graph of a project run: a long project, split into nodes, kept as files in the project's folder.
# no model in here, only files and rules. the scheduler (_scheduler.py), the node tools (_nodes/) and the run tools
# (start_run, run_status, message_run, pause_run) use it. starts with _: the tool loader skips it, it is no tool.
#
#   Shared/<project>/.graph/
#   ├── project.json        the goal, done-when points, total budget, sandbox          (start_run, once)
#   ├── nodes/T1.3.json     one node: goal, why, done-when points, depends on, budget (its parent, once)
#   ├── state/T1.3.json     status, budget, spent, given to children, accepted, ...   (only through this file)
#   ├── work/T1/            the root's folder: like a conversation folder (log, checkpoint, results, transcript)
#   │   └── agents/T1.3/    a child's folder, inside its parent's: so a parent can read its children's result files
#   ├── inbox/T1.3/         messages to a node, one file each. inbox/user/ = the root's messages to you
#   ├── knowledge/facts.jsonl   facts with their sources, from every node. only ever appended
#   ├── run.log             what the scheduler did, one line each
#   └── pause               there while you paused the run
#
# the sandbox sees .graph/ read-only (sandbox.py): agents can look at everything, but change it only through tools.
# a node's id says where it sits: T1 is the root, T1.3 its third child, T1.3.2 that one's second child.
#
# a node's status:
#   open       to do: it starts when everything it depends on is done
#   working    a shift runs on it right now
#   waiting    for its children, or for the answer to a question it asked
#   done       finished, with its result. its parent still checks it (accepted)
#   blocked    finished without its goal: out of budget, or something is missing. its parent decides
#   stale      was done, but something it depends on changed since: its parent checks it again
#   cancelled  dropped by its parent. replaced: dropped for another node (replaced_by)
# nothing is ever deleted: the graph is also the project's history.

import os
import json
import sys
import threading
import subprocess
import datetime
import locks
from config import *

ROOT = "T1"
SETTLED = ("done", "blocked", "stale", "cancelled", "replaced")   # a node in one of these is not working anymore


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")

def parent_of(id):
    """T1.3.2 -> T1.3. the root has none"""
    if "." not in id:
        return None
    return id.rsplit(".", 1)[0]

def id_key(id):
    """T1.10 after T1.9, not after T1.1: sort by the numbers"""
    key = []
    for part in id[1:].split("."):
        key.append(int(part))
    return key


class Graph:
    def __init__(self, project):
        self.project = project
        self.root = os.path.join(SHARED_DIR, project, ".graph")
        self.lock = threading.RLock()                             # parallel shifts change the graph one at a time

    # --- files ---
    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def exists(self):
        return os.path.isfile(self.path("project.json"))

    def read(self, path, default=None):
        if not os.path.isfile(path):
            return default
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def write(self, path, data):
        """first into a temporary file, then swapped in: nobody ever reads half a file"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".saving", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        os.replace(path + ".saving", path)

    def log(self, text):
        os.makedirs(self.root, exist_ok=True)
        with open(self.path("run.log"), "a", encoding="utf-8") as f:
            f.write(now() + "  " + text + "\n")

    def settings(self):
        return self.read(self.path("project.json"), {})

    # --- nodes ---
    def ids(self):
        found = []
        if os.path.isdir(self.path("nodes")):
            for file in os.listdir(self.path("nodes")):
                if file.endswith(".json"):
                    found.append(file[:-5])
        return sorted(found, key=id_key)

    def node(self, id):
        return self.read(self.path("nodes", id + ".json"))

    def state(self, id):
        return self.read(self.path("state", id + ".json"))

    def set_state(self, id, **changes):
        with self.lock:
            state = self.state(id)
            state.update(changes)
            self.write(self.path("state", id + ".json"), state)
            return state

    def children(self, id):
        found = []
        for other in self.ids():
            if parent_of(other) == id:
                found.append(other)
        return found

    def descendants(self, id):
        found = []
        for child in self.children(id):
            found.append(child)
            found += self.descendants(child)
        return found

    def folder(self, id):
        """a node's working folder: the root's is work/T1, a child's sits inside its parent's: .../agents/T1.3"""
        if id == ROOT:
            return self.path("work", ROOT)
        return os.path.join(self.folder(parent_of(id)), "agents", id)

    def result(self, id):
        return read_text(os.path.join(self.folder(id), "result.md"))

    def add_node(self, id, goal, why, done_when, budget, depends_on, by):
        """write a node once, with its first state: open"""
        self.write(self.path("nodes", id + ".json"),
                   {"id": id, "goal": goal, "why": why, "done_when": done_when, "depends_on": depends_on,
                    "budget": budget, "created": now(), "created_by": by})
        self.write(self.path("state", id + ".json"),
                   {"status": "open", "budget": budget, "spent": 0, "given": 0, "accepted": False, "asked": False,
                    "read": 0, "shifts": 0, "idle": 0, "progress": False, "note": "", "replaced_by": None})

    # --- budget: a node's budget covers its own shifts and everything it gives its children ---
    def available(self, id, extra_spent=0):
        state = self.state(id)
        return state["budget"] - state["spent"] - state["given"] - extra_spent

    # --- splitting ---
    def create(self, parent, specs, extra_spent=0, by=None):
        """create children of `parent`. specs: [{goal, why, done_when: [...], budget, depends_on: [...]}].
        returns (the new ids, None) or (None, what is wrong)"""
        with self.lock:
            if not isinstance(specs, list) or not specs:
                return None, "give a list of nodes"
            alive = []
            highest = 0
            for child in self.children(parent):
                if self.state(child)["status"] not in ("cancelled", "replaced"):
                    alive.append(child)
                highest = max(highest, int(child.rsplit(".", 1)[1]))
            if len(alive) + len(specs) > NODE_CHILDREN:
                return None, ("at most " + str(NODE_CHILDREN) + " children per node, you have " + str(len(alive))
                              + ". group the parts: fewer children, which split further themselves")
            if len(parent.split(".")) >= NODE_DEPTH:
                return None, "this node is " + str(NODE_DEPTH) + " levels deep already: do the work here, no more splitting"
            new_ids = []
            number = highest
            for spec in specs:
                number += 1
                new_ids.append(parent + "." + str(number))
            total = 0
            position = 0
            for spec in specs:
                if not isinstance(spec, dict):
                    return None, "every node must be an object with goal, why, done_when, budget"
                name = new_ids[position]
                for field in ("goal", "why"):
                    if not str(spec.get(field) or "").strip():
                        return None, name + ": " + field + " is missing"
                points = spec.get("done_when")
                if not isinstance(points, list) or not points:
                    return None, name + ": done_when must be a list of points that can be checked"
                for point in points:
                    if not str(point).strip():
                        return None, name + ": one of its done_when points is empty"
                try:
                    budget = int(spec.get("budget"))
                except (TypeError, ValueError):
                    return None, name + ": budget must be a number of tokens"
                if budget < NODE_MIN_BUDGET:
                    return None, name + ": a budget below " + format(NODE_MIN_BUDGET, ",") + " tokens is too small to do anything"
                total += budget
                for dependency in spec.get("depends_on") or []:
                    if dependency not in alive and dependency not in new_ids:
                        return None, name + ": depends_on can only name its siblings (" + ", ".join(alive + new_ids) + ")"
                    if dependency == name:
                        return None, name + " can't depend on itself"
                position += 1
            if total > self.available(parent, extra_spent):
                return None, ("these budgets add up to " + format(total, ",") + " tokens, but you only have "
                              + format(max(0, self.available(parent, extra_spent)), ",") + " left")
            if self.has_cycle(new_ids, specs):
                return None, "the depends_on of these nodes go in a circle: a node would wait for itself"
            position = 0
            for spec in specs:
                points = []
                for point in spec["done_when"]:
                    points.append(str(point).strip())
                self.add_node(new_ids[position], str(spec["goal"]).strip(), str(spec["why"]).strip(), points,
                              int(spec["budget"]), list(spec.get("depends_on") or []), by or parent)
                position += 1
            self.set_state(parent, given=self.state(parent)["given"] + total, progress=True)
            self.log(parent + " created " + ", ".join(new_ids))
            return new_ids, None

    def has_cycle(self, new_ids, specs):
        """follow the depends_on arrows among the siblings: coming back to where you started = a circle"""
        arrows = {}
        position = 0
        for spec in specs:
            arrows[new_ids[position]] = list(spec.get("depends_on") or [])
            position += 1
        for start in new_ids:
            seen = []
            todo = list(arrows[start])
            while todo:
                current = todo.pop()
                if current == start:
                    return True
                if current in seen or current not in arrows:
                    continue
                seen.append(current)
                todo += arrows[current]
        return False

    # --- messages: one file each, numbered 000001.md, 000002.md, ... read = how many of them the node has seen ---
    def inbox(self, id):
        return self.path("inbox", id)

    def messages(self, id):
        found = []
        if os.path.isdir(self.inbox(id)):
            for file in sorted(os.listdir(self.inbox(id))):
                if file.endswith(".md"):
                    found.append(os.path.join(self.inbox(id), file))
        return found

    def unread(self, id):
        if id == "user":
            return []
        return self.messages(id)[self.state(id)["read"]:]

    def send(self, sender, to, text):
        """put a message into a node's inbox (or the user's: to = "user"). the sender is its first line"""
        with self.lock:
            os.makedirs(self.inbox(to), exist_ok=True)
            number = len(self.messages(to)) + 1
            while True:                                           # the chat and the scheduler are two programs: if both
                path = os.path.join(self.inbox(to), str(number).zfill(6) + ".md")   # write at once, "x" lets only
                try:                                              # one of them have a number
                    with open(path, "x", encoding="utf-8") as f:
                        f.write("from: " + sender + "\ntime: " + now() + "\n\n" + text.strip() + "\n")
                    break
                except FileExistsError:
                    number += 1
            self.log(sender + " -> " + to + ": " + " ".join(text.split())[:100])

    def message(self, path):
        """(sender, time, text) of one message file"""
        lines = read_text(path).split("\n")
        sender = lines[0][len("from: "):] if lines and lines[0].startswith("from: ") else "?"
        time = lines[1][len("time: "):] if len(lines) > 1 and lines[1].startswith("time: ") else ""
        return sender, time, "\n".join(lines[3:]).strip()

    # --- the knowledge store ---
    def add_fact(self, node, fact, source):
        with self.lock:
            os.makedirs(self.path("knowledge"), exist_ok=True)
            with open(self.path("knowledge", "facts.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"time": now(), "node": node, "fact": fact, "source": source}, ensure_ascii=False) + "\n")

    def facts(self):
        found = []
        if os.path.isfile(self.path("knowledge", "facts.jsonl")):
            with open(self.path("knowledge", "facts.jsonl"), encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        found.append(json.loads(line))
        return found

    # --- the rules the scheduler follows ---
    def satisfied(self, id):
        """is this node, as something others depend on, finished? done or cancelled; replaced = when its replacement is"""
        state = self.state(id)
        if state["status"] == "replaced" and state["replaced_by"]:
            return self.satisfied(state["replaced_by"])
        return state["status"] in ("done", "cancelled")

    def ready(self, id):
        if self.state(id)["status"] != "open":
            return False
        for dependency in self.node(id)["depends_on"]:
            if not self.satisfied(dependency):
                return False
        return True

    def can_move(self, id):
        """can this node still get somewhere without its parent? then the parent doesn't need to be woken yet"""
        state = self.state(id)
        if state["status"] == "working":
            return True
        if state["status"] == "open":
            if self.ready(id):
                return True
            for dependency in self.node(id)["depends_on"]:      # waits for a sibling: can that one still finish?
                if not self.satisfied(dependency) and self.can_move(dependency):
                    return True
            return False
        if state["status"] == "waiting":
            if self.unread(id):
                return True                                       # a message came: it opens next round
            if state["asked"]:
                return False                                      # waits for its parent's answer
            for child in self.children(id):
                if self.can_move(child):
                    return True
            return False
        return False                                              # done, blocked, stale, cancelled, replaced

    def update(self):
        """before every round: waiting nodes with something new open again. returns the ids it opened"""
        opened = []
        with self.lock:
            for id in self.ids():
                state = self.state(id)
                wake = False
                if state["status"] == "waiting":
                    if self.unread(id):
                        wake = True                               # an answer, or news from below
                    elif not state["asked"]:
                        moving = False
                        for child in self.children(id):
                            if self.can_move(child):
                                moving = True
                        wake = not moving                         # nothing below it can go on without it
                elif state["status"] in ("done", "blocked") and id == ROOT and self.unread(id):
                    wake = True                                   # you sent the finished root a change request
                if wake:
                    self.set_state(id, status="open")
                    opened.append(id)
        return opened

    def recover(self):
        """after a crash: nodes left 'working' never finished their shift. they go on from their checkpoint"""
        for id in self.ids():
            if self.state(id)["status"] == "working":
                self.set_state(id, status="open")
                self.log(id + " was working when the scheduler stopped: open again")

    def mark_stale(self, id, changed=None):
        """`id` changed: every sibling that depends on it and was done is stale now: its parent checks it again"""
        changed = changed or id                                   # the node that really changed, for the log
        parent = parent_of(id)
        if not parent:
            return
        for sibling in self.children(parent):
            node = self.node(sibling)
            if id in node["depends_on"] and self.state(sibling)["status"] == "done":
                self.set_state(sibling, status="stale", accepted=False)
                self.log(sibling + " is stale: it builds on " + changed + ", which is being redone")
                self.mark_stale(sibling, changed)                 # and what depends on that one

    def finish(self, id, report, checkpoint=None, answers=None):
        """the node's result: report (+ an answer per done-when point) into result.md, its final checkpoint too"""
        text = report.strip()
        if answers:
            text += "\n\n## Done when\n"
            points = self.node(id)["done_when"]
            position = 0
            for point in points:
                text += str(position + 1) + ". " + point + "\n   -> " + str(answers[position]).strip() + "\n"
                position += 1
        write_text(os.path.join(self.folder(id), "result.md"), text)
        if checkpoint:
            write_text(os.path.join(self.folder(id), "checkpoint.md"), checkpoint)
        first = report.split(None, 1)[0].strip("*:#").upper() if report.strip() else ""
        status = "blocked" if first == "BLOCKED" else "done"
        self.set_state(id, status=status, accepted=False, progress=True, idle=0, note=report.strip().split("\n")[0][:200])
        self.log(id + " " + status + ": " + report.strip().split("\n")[0][:120])

    # --- what a node's agent reads at the start of its shift ---
    def briefing(self, id, budget_now):
        node = self.node(id)
        state = self.state(id)
        settings = self.settings()
        lines = ["You are node " + id + " of the project run on '" + self.project + "'. This is your shift "
                 + str(state["shifts"]) + ". The project folder is /workspace/" + self.project + "."]
        if id == ROOT:
            lines.append("You are the root: the whole project is your task. Your parent is the user: send_message to "
                         "'parent' reaches them.")
        lines += ["", "## Goal", node["goal"], "", "## Why", node["why"], "", "## Done when"]
        position = 0
        for point in node["done_when"]:
            position += 1
            lines.append(str(position) + ". " + point)
        lines += ["", "## Budget",
                  format(state["budget"], ",") + " tokens for this node and everything it gives its children. spent so far: "
                  + format(state["spent"], ",") + ", given to children: " + format(state["given"], ",")
                  + ". for this shift: " + format(max(0, budget_now), ",") + " (a reserve for your wrap-up is kept back)."]
        if node["depends_on"]:
            lines += ["", "## What you depend on (their results)"]
            for dependency in node["depends_on"]:
                lines.append("### " + dependency + " (" + self.state(dependency)["status"] + "): " + self.node(dependency)["goal"])
                lines.append(self.result(dependency)[:REPORT_LIMIT] or "(no result)")
        children = self.children(id)
        if children:
            lines += ["", "## Your children (their files: agents/<id>/... in your folder, e.g. agents/<id>/results/...)"]
            for child in children:
                child_state = self.state(child)
                status = child_state["status"]
                if status in ("done", "blocked", "stale"):
                    status += ", accepted" if child_state["accepted"] else ", NOT CHECKED YET"
                lines.append("### " + child + " [" + status + "] " + self.node(child)["goal"])
                lines.append("budget " + format(child_state["budget"], ",") + ", spent " + format(child_state["spent"], ","))
                if child_state["status"] in ("done", "blocked", "stale") and not child_state["accepted"]:
                    lines.append(self.result(child)[:REPORT_LIMIT + 2000] or "(no result)")
        number = 0
        for child in children:
            number = max(number, int(child.rsplit(".", 1)[1]))
        lines += ["", "Children you create are numbered on from " + id + "." + str(number + 1) + "."]
        unread = self.unread(id)
        if unread:
            lines += ["", "## New messages"]
            for message in unread:
                sender, time, text = self.message(message)
                who = sender
                if sender == parent_of(id) or (id == ROOT and sender == "user"):
                    who = "your parent (" + sender + ")"
                lines.append("### from " + who + ", " + time)
                lines.append(text)
            self.set_state(id, read=state["read"] + len(unread), asked=False)   # shown = read (one that comes later stays
                                                                  # unread). an answer came: no longer waiting for one
        if id == ROOT:
            lines += ["", "## The project", "goal: " + settings.get("goal", ""), "total budget: " + format(settings.get("budget", 0), ",")]
        lines += ["", "Decide what to do in this shift (see your rules), and do it. Write things down as you go."]
        return "\n".join(lines)

    # --- an overview, for you (run_status) and for nodes (node_status) ---
    def overview(self, show_spent=True):
        lines = []
        for id in self.ids():
            state = self.state(id)
            mark = state["status"]
            if state["status"] in ("done", "blocked", "stale") and parent_of(id):
                mark += "" if state["accepted"] else ", not checked yet"
            if state["status"] == "waiting" and state["asked"]:
                mark += ", asked a question"
            if state["status"] == "replaced":
                mark += " by " + str(state["replaced_by"])
            goal = self.node(id)["goal"]
            line = "  " * (len(id.split(".")) - 1) + id + " [" + mark + "] " + goal[:70] + ("..." if len(goal) > 70 else "")
            if show_spent:
                line += "  (" + format(state["spent"], ",") + " of " + format(state["budget"], ",") + ")"
            lines.append(line)
        return "\n".join(lines)


# --- the scheduler: one per project, as its own program (_scheduler.py) ---
def running(project):
    """is a scheduler running for this project? it holds the lock run-<project> as long as it runs"""
    return not locks.free("run-" + project)

def start_scheduler(project):
    """start the scheduler for this project in the background. it keeps running when you close the chat"""
    graph = Graph(project)
    log = open(graph.path("scheduler.log"), "a", encoding="utf-8")   # what it prints, in case something goes wrong
    detach = {}
    if os.name == "nt":                                           # windows: its own process group, no console of ours
        detach["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        detach["start_new_session"] = True                        # mac/linux: not stopped by ctrl+c in your terminal
    subprocess.Popen([sys.executable, "-B", "-m", "tools.projects._scheduler", project], cwd=HERE,   # -m: as part of
                     # tools/projects, so it finds _graph.py, and from the program folder, so it finds agent.py
                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **detach)
    log.close()
