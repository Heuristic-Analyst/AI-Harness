# agent.py — the Agent class. one Agent = one conversation with one model.
# the main agent you talk to and every subagent are the same class. the differences: the instructions, the tools and skills
# it may use, how deep it sits, and where its output goes (your terminal, or its transcript file).

import os
import json
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
- QUESTION: exactly what you need to know to continue (the parent may answer and continue you)"""

AUTO_MODE = """
Autonomous mode: the user is not available for questions. You are the final decision maker. When something is unclear,
make the most reasonable assumption, say in one line what you assumed, and continue. Answer your subagents' QUESTION reports
yourself; never pass them on to the user."""

SUMMARY_PROMPT = ("Summarize the conversation below, so it can be continued later without it. "
                  "Keep what the user wants, decisions made, facts learned from tools, and anything unfinished. "
                  "Leave out small talk. If there is an earlier summary, merge it in, so your summary covers everything. "
                  "Be short and use plain sentences.")


def as_text(m):
    """one message as plain text, for the summary request. thinking is left out on purpose"""
    if m["role"] == "tool":                                       # a tool result -> "tool calculate: 42"
        if m["name"] in ("load_skill", "read_memory"):            # file contents: still in their files, nothing to summarize
            return "tool " + m["name"] + ": (content was read)"
        return "tool " + m["name"] + ": " + m["content"]
    text = m.get("content") or ""
    for call in m.get("tool_calls") or []:                        # a tool request -> "[calls calculate({"expression": "6*7"})]"
        text += "\n[calls " + call["function"]["name"] + "(" + call["function"]["arguments"] + ")]"
    return m["role"] + ": " + text


class Agent:
    def __init__(self, name, instructions, tools, skills, depth=1, memory=False, log=None):
        self.name = name                                          # "main", or e.g. "main.worker-1" for a subagent
        self.instructions = instructions                          # the soul (main agent) or the template / one-off text (subagent)
        self.depth = depth                                        # 1 = talks to you. 2 = subagent. 3 = subagent of a subagent
        self.memory = memory                                      # True = MEMORY.md is shown in the system prompt (main agent only)
        self.log = log                                            # None = print to the terminal. a file = write there (subagents)
        self.mode = "ask"                                         # "ask" = may ask you questions. "auto" = decides on its own (/mode)
        self.summary = ""                                         # summary of old tasks after a compaction. empty until then
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
        if self.summary:                                          # 7. the summary of old tasks, once there is one
            system += "\n\nSummary of the earlier conversation:\n" + self.summary
        return system

    def pick_skills(self):
        """the skills this agent may load, from the menu as it is right now"""
        return [skill for skill in list(SKILLS) if self.skill_choice == "all" or skill in self.skill_choice]   # list(): a snapshot

    def refresh_system(self):
        self.skills = self.pick_skills()                          # skills can come and go while it runs (create_skill, delete_skill)
        self.messages[0] = {"role": "system", "content": self.build_system()}

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
        if len(result) > MAX_TOOL_RESULT:                         # huge result? cut it, so one tool can't flood the context
            result = result[:MAX_TOOL_RESULT] + "\n...(cut off, result was too long)"
        results[call.id] = (args, result)

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
            self.messages.append(
                {"role": "tool", "tool_call_id": call.id, "name": call.function.name, "content": result})

    # --- the agent loop ---
    def ask(self, text):
        with self.busy:                                           # a second question waits until this one is answered
            question = {"role": "user", "content": text}
            self.messages.append(question)                        # 1. add the question to the list
            if self.log:                                          #    a subagent writes what its parent sent into its transcript
                self.say("\nFROM PARENT:\n" + text)

            try:
                while True:                                       # repeat until the model answers without tool calls
                    self.maybe_compact()                          # 2. too big? summarize the old tasks first
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
                    self.messages.append(reply.model_dump(exclude_none=True))   # 5. store the whole reply: answer, thinking, tool calls

                    if not reply.tool_calls:                      # 6. no tool calls -> that was the final answer, done
                        break
                    self.run_tools(reply)                         #    tool calls -> run them, then loop: send the results back
                return reply.content or ""                        #    the final answer, for whoever asked: you, or a parent agent
            except Exception:                                     # the model or the connection failed (rate limit, network, ...)
                if self.messages[-1] is question:                 # nothing happened yet: take the question back, so it can simply be asked again
                    self.messages.pop()
                raise                                             # and let whoever asked know: main.py prints it, a parent gets it as a tool error
            finally:                                              # 7. the task is over (or failed), so its subagents are over too,
                self.close_children(keep_waiting=True)            #    except the ones still waiting for an answer to their QUESTION

    def maybe_compact(self):
        """too many tokens? summarize everything except the last KEEP_TASKS tasks, and put the summary into the system prompt"""
        tokens = litellm.token_counter(model=MODEL, messages=self.messages)   # an estimate, good enough to decide
        if tokens < CONTEXT_LIMIT:
            return
        starts = []                                               # the positions of the user messages: every one starts a task
        position = 0
        for m in self.messages:
            if m["role"] == "user":
                starts.append(position)
            position += 1
        if len(starts) <= KEEP_TASKS:                             # nothing old enough to summarize
            return
        cut = starts[-KEEP_TASKS]                                 # first message of the oldest task we keep word for word
        old = self.messages[1:cut]                                # everything before it, except the system message

        request = SUMMARY_PROMPT
        if self.summary:                                          # 2nd, 3rd... compaction: the earlier summary is merged in
            request += "\n\nEarlier summary:\n" + self.summary
        request += "\n\nConversation:"
        for m in old:
            request += "\n\n" + as_text(m)
        try:
            response = litellm.completion(api_key=API_KEY, model=MODEL, reasoning_effort="low",   # a separate small request, no tools
                                          messages=[{"role": "user", "content": request}])
            new_summary = response.choices[0].message.content
        except Exception as e:                                    # summary failed? don't crash, try again next time
            self.say("\n[compaction skipped: " + str(e) + "]")
            return
        if not new_summary:
            return
        self.summary = new_summary
        self.messages = [{"role": "system", "content": self.build_system()}] + self.messages[cut:]   # fresh system message + kept tasks
        self.say("\n[compacted: " + f"{tokens:,}" + " -> " + f"{litellm.token_counter(model=MODEL, messages=self.messages):,}" + " tokens]")

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
            name = self.name + "." + id                           # e.g. "main.worker-1": unique in the whole tree, used for the file
            os.makedirs(RUNS_DIR, exist_ok=True)
            path = os.path.join(RUNS_DIR, free_name(RUNS_DIR, timestamp() + "-" + name, ".md") + ".md")
            log = open(path, "w", encoding="utf-8")               # the subagent's transcript. stays open while it lives
            child = Agent(name, instructions, allowed, skills, depth=self.depth + 1, log=log)
            log.write("# " + name + "\ntools: " + ", ".join(child.tool_names) + "\nskills: " + ", ".join(child.skills) + "\n")   # what it really got
            self.children[id] = child

        self.say("\n[" + name + " started -> " + os.path.relpath(path, HERE) + "]")
        report = child.ask(task)                                  # waits until the subagent's turn is over (parallel through run_tools' threads)
        child.waiting = self.report_status(name, report) == "QUESTION"   # a QUESTION is not the end: the subagent stays alive for tell
        return "[" + id + "] " + report                           # the id in front, so the parent knows whom to tell

    def tell(self, id, message):
        child = self.children.get(id)
        if not child:
            return "no live subagent called '" + id + "'. live: " + (", ".join(self.children) or "none")
        self.say("\n[" + child.name + " continues]")
        report = child.ask(message)                               # same subagent, full context: it carries on where it stopped
        child.waiting = self.report_status(child.name, report) == "QUESTION"   # asks again? stays alive. otherwise it ends with this task
        return "[" + id + "] " + report

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
