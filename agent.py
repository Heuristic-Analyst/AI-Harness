# agent.py — the Agent class. one Agent = one conversation with one model.
# the main agent you talk to and every subagent are the same class. the differences: the instructions, the tools and skills
# it may use, how deep it sits, and where its output goes (your terminal, or its transcript file).
#
# every agent has a folder: the conversation's folder (Conversations/<name>/) for the main agent, and a folder in there
# for each subagent (agents/<when>-<id>/). in it:
#   log.jsonl       everything, word for word, one line per message or event. only ever appended, never rewritten
#   checkpoint.md   the agent's own notes: goal, decisions, facts, done, open, next. it is in the system prompt
#   results/        tool results too long for the context, one file each (000042-sandbox_shell.txt)
#   agents/         its subagents, each with the same folder inside
# nothing is ever summarized. when the context gets full, the agent writes its checkpoint and the context is cleared:
# it goes on with its system prompt (checkpoint included) and the last task. the log still has every word.

import os
import re
import json
import datetime
import logging
import importlib.util
import threading
import litellm
from config import *

logging.getLogger("LiteLLM").setLevel(logging.ERROR)   # litellm is chatty. only show real errors.
litellm.drop_params = True             # if a model can't do something (e.g. thinking), skip it instead of crashing
litellm.suppress_debug_info = True     # no "Provider List" hints when litellm's bookkeeping can't identify a model


# Tools: one file per tool, anywhere in the tools folder, also in subfolders (tools/notebook/nb_add.py).
# each file has TOOL (what the model sees) and run (what we execute). folders are only for you: the model sees the name in TOOL
TOOLS = {}                                                        # tool name -> description, in the format the model wants
FUNCTIONS = {}                                                    # tool name -> the python function to run
FOUND_IN = {}                                                     # tool name -> its file, to report two tools with one name
for folder, subfolders, files in os.walk(TOOLS_DIR):              # the tools folder, then every folder inside it, all the way down
    subfolders[:] = sorted(s for s in subfolders if not s.startswith((".", "_")))   # skip __pycache__, .git and _drafts
    for file in sorted(files):
        if not file.endswith(".py") or file.startswith("_"):      # _helpers.py, __init__.py: not a tool
            continue
        path = os.path.join(folder, file)
        where = os.path.relpath(path, HERE)                       # e.g. tools/notebook/nb_add.py
        spec = importlib.util.spec_from_file_location(where[:-3].replace(os.sep, "."), path)   # load the file by its path
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        name = module.TOOL["name"]
        if name in TOOLS:
            raise SystemExit("two tools are called '" + name + "': " + FOUND_IN[name] + " and " + where + ". rename one")
        TOOLS[name] = {"type": "function", "function": module.TOOL}
        FUNCTIONS[name] = module.run
        FOUND_IN[name] = where


SUBAGENT_RULES = """
You are a subagent in a small multi-agent system. A parent agent gave you one task. You never talk to the user.
Do the task with your tools. Do not ask about things you can settle with a reasonable assumption: state the assumption and go on.
Your final message is your report, and it is the ONLY thing your parent will see. Start it with one word:
- DONE: then the result, and how you got it
- BLOCKED: what you tried, and what is missing
- QUESTION: exactly what you need to know to continue (the parent may answer and continue you)
Keep the report under """ + format(REPORT_LIMIT, ",") + """ characters. Details go into files, and the report points to them: files
you made in /workspace/..., or your result files (results/...: your parent can read those too). Say where every claim
comes from: a source, a file, or the command that showed it."""

AUTO_MODE = """
Autonomous mode: the user is not available for questions. You are the final decision maker. When something is unclear,
make the most reasonable assumption, say in one line what you assumed, and continue. Answer your subagents' QUESTION reports
yourself; never pass them on to the user."""

CHECKPOINT_PROMPT = """CHECKPOINT. Your context is getting full and will be cleared right after this message. Write your checkpoint
now: everything you need to go on without the conversation so far. It replaces your previous checkpoint (in your system
prompt, if there is one), so carry over everything from it that is still true. Do not call tools. Short bullets, facts
not stories, exactly these sections:
## Goal
what the user wants, and what "done" means
## Decisions
what was decided, and why
## Facts
what was found out, each with where it comes from: a source, a file, or the command that showed it
## Done
## Open
what is left, and the very next step
## Files
the files that matter: results/... (read them with read_result), and files in /workspace/...
## Questions
what is unclear or still to be asked"""

EMERGENCY_NOTE = """
You are in the MIDDLE of a task: say exactly where you are in it, and what you were about to do next."""

GO_ON = """

[note: your context was cleared in the middle of this task to make room. Your checkpoint (in your system prompt) says
where you were: go on from there. Earlier tool results are in your results/ files: read_result shows them.]"""

WHOLE_RESULTS = ["load_skill", "read_memory", "read_result", "search_result"]   # never put into a file: the agent needs all of it,
                                                                                # and they are short by themselves
MOVED = "[moved out of your context to make room: "               # the start of a tool result that became a pointer


def preview(path, text):
    """what the model sees of a long tool result: where it is, how big, the start and the end"""
    lines = text.split("\n")
    head = "\n".join(lines[:40])[:3000]                           # the first 40 lines, at most 3000 characters
    tail = "\n".join(lines[-20:])[-1500:] if len(lines) > 40 else ""   # and the last 20
    answer = ("[result: " + path + ", " + format(len(text), ",") + " characters, " + format(len(lines), ",") + " lines. "
              "this is only the start" + (" and the end" if tail else "") + ": read_result and search_result show the rest]\n"
              + head)
    if tail:
        answer += "\n...\n" + tail
    return answer

def highest_result(folder):
    """the highest number among the result files in this folder, 0 if there are none. the next file counts on from it,
    also after /open: so a name is never used twice in one conversation"""
    highest = 0
    results = os.path.join(folder, "results")
    if os.path.isdir(results):
        for file in os.listdir(results):
            number = file.split("-", 1)[0]                        # "000042-sandbox_shell.txt" -> "000042"
            if number.isdigit():
                highest = max(highest, int(number))
    return highest


class Agent:
    def __init__(self, name, instructions, tools, skills, folder, depth=1, memory=False, log=None):
        self.name = name                                          # "main", or e.g. "main.worker-1" for a subagent
        self.folder = folder                                      # its folder: log, checkpoint, results, subagents (see the top)
        self.instructions = instructions                          # the soul (main agent) or the template / one-off text (subagent)
        self.depth = depth                                        # 1 = talks to you. 2 = subagent. 3 = subagent of a subagent
        self.memory = memory                                      # True = MEMORY.md is shown in the system prompt (main agent only)
        self.log = log                                            # None = print to the terminal. a file = write there (subagents)
        self.mode = "ask"                                         # "ask" = may ask you questions. "auto" = decides on its own (/mode)
        self.logged_system = None                                 # the system prompt as it was last written into the log
        self.results = highest_result(folder)                     # how many result files it has so far, for the next one's name
        self.children = {}                                        # live subagents: id -> Agent
        self.waiting = False                                      # True = its last report was a QUESTION: it stays alive until its parent answers with tell
        self.spawned = 0                                          # how many subagents this agent created so far, for their ids
        self.lock = threading.Lock()                              # parallel tool calls may create subagents at once: ids are handed out one at a time
        self.busy = threading.Lock()                              # one question at a time per agent
        self.printing = None                                      # which kind of text is being printed right now: THINKING or ANSWER
        self.memory_seen = None                                   # MEMORY.md as read_memory last showed it. write_memory checks that
                                                                  # nobody (another instance, you) changed it since
        self.skills_seen = {}                                     # skill name -> its file as load_skill last showed it, for edit_skill

        self.skill_choice = skills                                # "all", or the list of skill names it was given
        self.skills = self.pick_skills()                          # the skill names this agent may load

        self.tools = []                                           # the tool descriptions this agent gets, in the model's format
        for tool in TOOLS:
            if depth >= MAX_DEPTH and tool in ("delegate", "tell"):   # the deepest agents may not create subagents, so they don't get the tools for it
                continue
            if tools == "all" or tool in tools or (tool == "load_skill" and self.skills):   # skills are useless without load_skill, so it comes with them
                self.tools.append(TOOLS[tool])
        self.tool_names = [t["function"]["name"] for t in self.tools]   # just the names, e.g. ["calculate", "delegate", ...]

        self.messages = [{"role": "system", "content": self.build_system()}]   # the whole conversation. one list.

    # --- the system prompt: rebuilt from parts whenever a part changes, never edited in place ---
    def build_system(self):
        system = self.instructions                                # 1. who the agent is
        if self.depth > 1:                                        # 2. a subagent: the rules every subagent follows
            system += "\n" + SUBAGENT_RULES
        if self.skills:                                           # 3. the skills menu: names and descriptions, loaded on demand
            system += ("\n\nYou have skills: step-by-step instructions for certain kinds of tasks. "
                       "When a task matches a skill, first call load_skill with its name, then follow what it returns.\nAvailable skills:")
            for skill in self.skills:                             # [editable] = one the agent wrote itself, in Skills/Learned
                entry = SKILLS.get(skill)
                if entry:                                         # deleted a moment ago? then it's simply not listed
                    system += "\n- " + skill + (" [editable]" if entry["editable"] else "") + ": " + entry["description"]
            if "create_skill" in self.tool_names:
                system += ("\nSkills marked [editable] are ones you wrote yourself: improve them with edit_skill when you learn "
                           "something better, remove them with delete_skill when they are no longer useful. The others are "
                           "the user's: you can't change them. New skills: create_skill.")
        if "delegate" in self.tool_names:                         # 4. the templates menu, for agents that may create subagents
            system += ("\n\nYou can create subagents with delegate: from a template below, or with your own instructions.\n"
                       "Templates:")
            for template_name, template in templates().items():
                system += "\n- " + template_name + ": " + template["description"]
            if not templates():
                system += "\n(none, write your own instructions)"
        if self.memory:                                           # 5. the memory, as it is in the file right now
            system += ("\n\nYour memory, saved across conversations. To change it, load the memory skill first.\n"
                       "<memory>\n" + (read_text(MEMORY_FILE) or "(empty)") + "\n</memory>")
        if self.mode == "auto":                                   # 6. autonomous mode, if you switched it on
            system += "\n" + AUTO_MODE
        checkpoint = read_text(os.path.join(self.folder, "checkpoint.md"))
        if checkpoint:                                            # 7. its checkpoint, once it wrote one
            system += ("\n\nYour checkpoint: your own notes from earlier in this conversation, written before your context was "
                       "cleared. It is where you stand.\n<checkpoint>\n" + checkpoint + "\n</checkpoint>")
        return system

    def pick_skills(self):
        """the skills this agent may load, from the menu as it is right now"""
        return [skill for skill in list(SKILLS) if self.skill_choice == "all" or skill in self.skill_choice]   # list(): a snapshot

    def refresh_system(self):
        self.skills = self.pick_skills()                          # skills can come and go while it runs (create_skill, delete_skill)
        self.messages[0] = {"role": "system", "content": self.build_system()}

    # --- the log: everything, one json line each, only ever appended ---
    def record(self, kind, **fields):
        """write one line into log.jsonl: a message, the system prompt, a checkpoint, ..."""
        entry = {"time": datetime.datetime.now().isoformat(timespec="seconds"), "kind": kind}
        entry.update(fields)
        os.makedirs(self.folder, exist_ok=True)                   # the folder appears with the first line, not before
        with open(os.path.join(self.folder, "log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def add(self, message):
        """put a message into the conversation, and into the log. the system prompt goes into the log first, if it
        changed since it was last written there: so the log always shows what the agent was working with"""
        if self.messages[0]["content"] != self.logged_system:
            self.record("system", content=self.messages[0]["content"])
            self.logged_system = self.messages[0]["content"]
        self.messages.append(message)
        self.record("message", message=message)

    def moved(self, old, new):
        """the conversation's folder was renamed (/rename): this agent and its subagents now live under the new name"""
        self.folder = new + self.folder[len(old):]
        for child in self.children.values():
            child.moved(old, new)

    # --- output: the main agent prints, a subagent writes its transcript (watch it live with `tail -f`) ---
    def say(self, text, end="\n"):
        if self.log:
            self.log.write(text + end)
            self.log.flush()                                      # write it out right now, so you can watch the file live
        else:
            print(text, end=end, flush=True)

    def print_part(self, kind, text):
        """print one piece of THINKING or ANSWER text. a title appears whenever the kind changes"""
        if not text:                                              # nothing of this kind in this chunk
            return
        if kind == "THINKING" and not PRINT_THINKING and not self.log:   # hidden in the terminal, kept in transcripts
            return
        if kind != self.printing:
            self.say("\n\n" + kind + ":" if self.printing else "\n" + kind + ":")
            self.printing = kind
        self.say(text, end="")

    def show(self, response):
        """print the reply while it arrives, and return the finished reply"""
        chunks = []                                               # every chunk, so litellm can rebuild the full reply from them
        self.printing = None
        for chunk in (response if STREAM else [response]):        # streaming: many small chunks. not streaming: one big chunk
            chunks.append(chunk)
            if not chunk.choices:                                 # some chunks are just bookkeeping, skip
                continue
            part = chunk.choices[0].delta if STREAM else chunk.choices[0].message   # delta = "what's new", message = "everything"
            self.print_part("THINKING", getattr(part, "reasoning_content", None))   # getattr = the attribute, or None if there is none
            self.print_part("ANSWER", part.content)
        self.say("")
        if STREAM:
            response = litellm.stream_chunk_builder(chunks)       # glue the chunks back together into one reply
        return response.choices[0].message

    # --- tools: every tool call of one reply runs in its own thread, so subagents run in parallel ---
    def run_tool(self, call, results):
        name = call.function.name
        try:
            args = json.loads(call.function.arguments or "{}")    # arguments arrive as a json string
            if name not in self.tool_names:                       # only the tools this agent was given, even if the model names another one
                raise Exception("you have no tool called '" + name + "'. yours: " + (", ".join(self.tool_names) or "none"))
            result = str(FUNCTIONS[name](self, **args))           # every tool gets the calling agent first, then the arguments
        except Exception as e:
            args, result = call.function.arguments, "error: " + str(e)   # errors go back to the model as text, so it can retry
        if len(result) > RESULT_TO_FILE and name not in WHOLE_RESULTS:   # long? into a file. the model gets a preview
            result = preview(self.save_result(name, result), result)
        results[call.id] = (args, result)

    def save_result(self, name, text):
        """put a tool result into its own file in results/. returns its path, as the agent uses it: results/000042-name.txt"""
        with self.lock:                                           # parallel tool calls: one number each
            self.results += 1
            path = "results/" + str(self.results).zfill(6) + "-" + name + ".txt"   # 6 digits: in order up to 999,999
        os.makedirs(os.path.join(self.folder, "results"), exist_ok=True)
        with open(os.path.join(self.folder, path), "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def shows(self, call):
        """should this tool call appear? transcripts get everything; your terminal follows the PRINT_ settings"""
        talk = call.function.name in ("delegate",
                                      "tell")  # a message to a subagent and its report: their conversation, not yours
        return self.log or (PRINT_TOOLS and (PRINT_SUBAGENT_TALK or not talk)) # transcripts always get everything

    def run_tools(self, reply):
        results = {}  # tool call id -> (arguments, result)
        threads = []
        for call in reply.tool_calls:  # start one thread per call...
            if self.shows(call):  # ...and show what is starting, before it runs
                self.say("\nTOOL CALL:\n" + call.function.name + "(" + (call.function.arguments or "") + ")")
            thread = threading.Thread(target=self.run_tool, args=(call, results))
            thread.start()
            threads.append(thread)
        for thread in threads:  # wait until all of them are done
            thread.join()
        for call in reply.tool_calls:  # then hand the results back, in the order the model asked
            args, result = results[call.id]
            if self.shows(call):
                self.say("\nTOOL RESULT:\n" + call.function.name + " -> " + result)
            self.add({"role": "tool", "tool_call_id": call.id, "name": call.function.name, "content": result})

    # --- the agent loop ---
    def ask(self, text):
        with self.busy:                                           # a second question waits until this one is answered
            question = {"role": "user", "content": text}
            self.add(question)                                    # 1. add the question to the list (and the log)
            if self.log:                                          #    a subagent writes what its parent sent into its transcript
                self.say("\nFROM PARENT:\n" + text)

            try:
                while True:                                       # repeat until the model answers without tool calls
                    self.make_room()                              # 2. too full in the middle of a task? make room first
                    response = litellm.completion(                # 3. send the whole list to the model
                        api_key=API_KEY,                          #    the key from .env, no environment variables involved
                        model=MODEL,
                        messages=self.messages,
                        tools=self.tools or None,                 #    None = this agent has no tools
                        stream=STREAM,
                        reasoning_effort=EFFORT,                  #    thinking on
                        cache_control_injection_points=[{"location": "message", "index": -1}],   # cache bookmark on the last message
                    )
                    reply = self.show(response)                   # 4. print it as it arrives, get the finished reply back
                    self.add(reply.model_dump(exclude_none=True))   # 5. store the whole reply: answer, thinking, tool calls

                    if not reply.tool_calls:                      # 6. no tool calls -> that was the final answer, done
                        break
                    self.run_tools(reply)                         #    tool calls -> run them, then loop: send the results back
                self.maybe_checkpoint()                           # 7. the task is done: context getting full? checkpoint now
                return reply.content or ""                        #    the final answer, for whoever asked: you, or a parent agent
            except Exception:                                     # the model or the connection failed (rate limit, network, ...)
                if self.messages[-1] is question:                 # nothing happened yet: take the question back, so it can simply be asked again
                    self.messages.pop()
                    self.record("question taken back", reason="the model call failed")
                raise                                             # and let whoever asked know: main.py prints it, a parent gets it as a tool error
            finally:                                              # 8. the task is over (or failed), so its subagents are over too,
                self.close_children(keep_waiting=True)            #    except the ones still waiting for an answer to their QUESTION

    # --- checkpoints: when the context gets full, the agent writes down where it stands, and starts fresh ---
    def tokens(self):
        return litellm.token_counter(model=MODEL, messages=self.messages)   # an estimate, good enough to decide

    def maybe_checkpoint(self):
        """after a task: above CHECKPOINT_AT? the agent writes its checkpoint, and its context is cleared down to the
        system prompt (which holds the checkpoint) and the last KEEP_TASKS tasks. only the main agent: a subagent's
        whole life is one task, the emergency below covers it"""
        if self.depth > 1:
            return
        before = self.tokens()
        if before < CHECKPOINT_AT * CONTEXT_LIMIT:
            return
        if not self.write_checkpoint(False):
            return                                                # failed: it is tried again after the next task
        self.clear(self.last_tasks())
        self.say("\n[checkpoint written, context cleared: " + format(before, ",") + " -> " + format(self.tokens(), ",") + " tokens]")

    def make_room(self):
        """in the middle of a task, above EMERGENCY_AT: first the old tool results become pointers to their files.
        still too full? the agent writes its checkpoint right away, and the task goes on from it with a fresh context"""
        limit = EMERGENCY_AT * CONTEXT_LIMIT
        before = self.tokens()
        if before < limit:
            return
        moved = self.move_old_results()
        if moved:
            self.record("results moved to files", count=moved)
            self.say("\n[context " + format(before, ",") + " tokens: " + str(moved) + " older tool results moved to their files -> "
                     + format(self.tokens(), ",") + " tokens]")
        if self.tokens() < limit:
            return
        task = self.last_tasks(1)[0]                              # the task it is in the middle of: its question
        if not self.write_checkpoint(True):
            return                                                # failed: it goes on, and the model call may fail for size
        self.clear([{"role": "user", "content": task["content"] + GO_ON}])
        self.say("\n[emergency checkpoint written, context cleared: " + format(before, ",") + " -> " + format(self.tokens(), ",")
                 + " tokens. the task goes on]")

    def write_checkpoint(self, emergency):
        """ask the agent for its checkpoint (it sees everything, and its old checkpoint in the system prompt), and save it
        into checkpoint.md, replacing the old one. the old one is still in the log. returns True if it worked"""
        self.say("\n[writing checkpoint...]")
        request = CHECKPOINT_PROMPT + (EMERGENCY_NOTE if emergency else "")
        try:
            response = litellm.completion(api_key=API_KEY, model=MODEL, reasoning_effort=EFFORT,
                                          messages=self.messages + [{"role": "user", "content": request}],   # only for this call
                                          tools=self.tools or None,      # some models need the tools listed when the
                                          tool_choice="none" if self.tools else None)   # history has tool calls. none may be used
            text = response.choices[0].message.content
        except Exception as e:
            self.say("\n[checkpoint failed: " + type(e).__name__ + ": " + str(e) + "]")
            return False
        if not text or not text.strip():
            self.say("\n[checkpoint failed: the model wrote nothing]")
            return False
        write_text(os.path.join(self.folder, "checkpoint.md"), text)
        self.record("checkpoint", content=text, emergency=emergency)
        return True

    def clear(self, kept):
        """the context starts fresh: the system prompt (rebuilt, with the new checkpoint) and the kept messages"""
        self.messages = [{"role": "system", "content": self.build_system()}]
        self.record("context cleared", kept_messages=len(kept))
        for message in kept:
            self.add(message)

    def last_tasks(self, count=None):
        """the messages of the last KEEP_TASKS tasks (or `count`), to keep after a checkpoint. if they are big themselves,
        only each task's question and final answer are kept: the steps in between are in the log and the result files"""
        if count is None:
            count = KEEP_TASKS
        starts = []                                               # the positions of the user messages: every one starts a task
        position = 0
        for m in self.messages:
            if m["role"] == "user":
                starts.append(position)
            position += 1
        if count <= 0 or not starts:
            return []
        kept = self.messages[starts[-min(count, len(starts))]:]
        if litellm.token_counter(model=MODEL, messages=kept) < 0.2 * CONTEXT_LIMIT:
            return kept
        short = []                                                # too big: question + final answer per task
        for m in kept:
            if m["role"] == "user":
                short.append(m)
            elif m["role"] == "assistant" and not m.get("tool_calls") and m.get("content"):
                short.append({"role": "assistant", "content": m["content"]})
        return short

    def move_old_results(self):
        """every tool result except the newest KEEP_RESULTS becomes a short pointer to its file. results that aren't in a
        file yet are put into one first, so nothing is lost. returns how many were moved"""
        tool_messages = []
        for m in self.messages:
            if m["role"] == "tool" and not m["content"].startswith(MOVED):
                tool_messages.append(m)
        older = tool_messages
        if KEEP_RESULTS:
            older = tool_messages[:-KEEP_RESULTS]                 # the newest ones stay as they are
        moved = 0
        for m in older:
            found = re.match(r"\[result: (results/[^,]+),", m["content"])   # a preview: it is in a file already
            path = found.group(1) if found else self.save_result(m["name"], m["content"])
            m["content"] = MOVED + path + ", " + format(len(m["content"]), ",") + " characters here before. read_result shows it]"
            moved += 1
        return moved

    # --- subagents: given one task, alive for follow-ups until this agent's task ends ---
    def delegate(self, task, template=None, instructions=None, tools=None, skills=None):
        if self.depth >= MAX_DEPTH:
            return "not allowed: agents at depth " + str(self.depth) + " may not create subagents. do the task yourself"

        if template:                                              # a ready-made subagent from the Templates folder...
            blueprint = templates().get(template)
            if not blueprint:
                return "no template called '" + template + "'. available: " + (", ".join(templates()) or "none")
            instructions = blueprint["instructions"]
            tools = tools or blueprint["tools"]                   # the parent may still override tools and skills
            skills = skills or blueprint["skills"]
        elif not instructions:                                    # ...or a one-off: then the parent must say who the subagent is
            return "give a template, or instructions for a one-off subagent"
        else:
            tools = tools or DEFAULT_SUBAGENT_TOOLS
            skills = skills or []

        allowed = []                                              # drop main-only tools, check the rest exist
        for tool in tools:
            if tool in MAIN_ONLY_TOOLS:
                continue
            if tool not in TOOLS:
                return "unknown tool '" + tool + "'. available: " + ", ".join(TOOLS)
            allowed.append(tool)
        for skill in skills:
            if skill not in SKILLS:
                return "unknown skill '" + skill + "'. available: " + (", ".join(SKILLS) or "none")

        with self.lock:                                           # one subagent at a time gets its id and slot
            if len(self.children) >= MAX_CHILDREN:
                return "not allowed: you already have " + str(MAX_CHILDREN) + " subagents. wait for them or ask them more with tell"
            self.spawned += 1
            id = (template or "sub") + "-" + str(self.spawned)    # e.g. "worker-1": what the parent uses in tell
            name = self.name + "." + id                           # e.g. "main.worker-1": unique in the whole tree, shown in the terminal
            agents = os.path.join(self.folder, "agents")          # its folder sits inside this agent's folder: agents/<when>-<id>/
            folder = os.path.join(agents, free_name(agents, timestamp() + "-" + id, ""))
            os.makedirs(folder)
            log = open(os.path.join(folder, "transcript.md"), "w", encoding="utf-8")   # its transcript, for you. stays open while it lives
            child = Agent(name, instructions, allowed, skills, folder, depth=self.depth + 1, log=log)
            log.write("# " + name + "\ntools: " + ", ".join(child.tool_names) + "\nskills: " + ", ".join(child.skills) + "\n")   # what it really got
            self.children[id] = child

        self.say("\n[" + name + " started -> " + os.path.relpath(os.path.join(folder, "transcript.md"), HERE) + "]")
        report = child.ask(task)                                  # waits until the subagent's turn is over (parallel through run_tools' threads)
        child.waiting = self.report_status(name, report) == "QUESTION"   # a QUESTION is not the end: the subagent stays alive for tell
        return self.report_head(id, child) + report               # the id in front, so the parent knows whom to tell

    def tell(self, id, message):
        child = self.children.get(id)
        if not child:
            return "no live subagent called '" + id + "'. live: " + (", ".join(self.children) or "none")
        self.say("\n[" + child.name + " continues]")
        report = child.ask(message)                               # same subagent, full context: it carries on where it stopped
        child.waiting = self.report_status(child.name, report) == "QUESTION"   # asks again? stays alive. otherwise it ends with this task
        return self.report_head(id, child) + report

    def report_head(self, id, child):
        """what comes before a subagent's report: its id (for tell), and where its files are, seen from this agent"""
        return "[" + id + ", its files: " + os.path.relpath(child.folder, self.folder).replace(os.sep, "/") + "/] "

    def report_status(self, name, report):
        """one terminal line that matches the report: DONE, BLOCKED or QUESTION. returns that word"""
        first = report.strip().split(None, 1)[0] if report.strip() else ""   # the first word of the report
        status = first.strip("*:#").upper()                       # "**DONE:**" -> "DONE"
        if status == "QUESTION":
            self.say("\n[" + name + " asks a question, waiting for an answer]")
        elif status in ("DONE", "BLOCKED"):
            self.say("\n[" + name + " reported " + status + "]")
        else:
            self.say("\n[" + name + " replied]")                  # the model ignored the report format
        return status

    def close_children(self, keep_waiting=False):
        """close the subagents. keep_waiting = except the ones waiting for an answer to their QUESTION:
        their parent may pass the question on (to you, or up to its own parent) and answer with tell in a later task"""
        for id in list(self.children):                            # list(...) = a copy of the ids, because we change the dict while looping
            if keep_waiting and self.children[id].waiting:
                continue
            child = self.children.pop(id)
            child.close()
            self.say("\n[" + child.name + " closed]")             # now it is really over

    def close(self):
        self.close_children()                                     # its own subagents first
        if self.log:
            self.log.write("\n[done]\n")
            self.log.close()
            self.log = None
