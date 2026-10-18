# main.py — start here: `python main.py`. the chat loop and the /commands.
# the agent lives in agent.py, the sandboxes in sandbox.py, the settings in config.py, the tools in tools/.
#
# next to this file:
#   .env                     API keys, one line each: DEEPSEEK_API_KEY=...   (only the provider you use needs a value)
#   Ego/SOUL.md              who the main agent is. you write it
#   Ego/MEMORY.md            what it remembers across conversations. it edits this itself (memory skill)
#   Skills/<name>/SKILL.md   one folder per skill
#   Templates/<name>.md      ready-made subagents: instructions + tools + skills
#   tools/<folder>/<name>.py one file per tool, sorted into folders (tools/notebook/nb_add.py)
#   Sandboxes/<name>/        one folder per sandbox (a Containerfile inside)
#   Shared/                  what a sandbox sees: Shared/common always, and one project folder Shared/<project> if the agent mounts one
#   Conversations/<name>/    one folder per conversation: state.json (what /open loads), log.jsonl (everything, word for word),
#                            checkpoint.md (the agent's notes), results/ (long tool results), agents/ (its subagents)
#   Locks/                   "in use" signs of the running instances (see locks.py). you can run main.py several times at once
#
# setup once: pip install -r requirements.txt, and podman installed (on mac/windows also `podman machine start`)

import os
import json
import atexit
from config import *
from agent import Agent
import sandbox
import locks


def new_main_agent(name):
    soul = read_text(SOUL_FILE) or "You are a helpful assistant."    # the soul is the start of the system prompt. empty file? fallback
    return Agent("main", instructions=soul, tools="all", skills="all", folder=conversation_folder(name), memory=True)

def conversation_folder(name):
    return os.path.join(CONVERSATIONS_DIR, name)                  # created with the first thing written into it

def old_file(name):
    return os.path.join(CONVERSATIONS_DIR, name + ".json")        # how a conversation was saved before folders: one .json

def exists(name):
    return os.path.isdir(conversation_folder(name)) or os.path.isfile(old_file(name))

def lock_of(name):
    return "conversation-" + name                                 # an open conversation is locked: no other instance can open it

def new_name():
    """a fresh name, e.g. 20261007-14-05-09, with -2, -3 ... added if it is taken. its lock is taken right away, so another
    instance started in the same second can't get the same name, even before anything is saved"""
    base = timestamp()
    name = base
    number = 2
    while exists(name) or not locks.take(lock_of(name)):
        name = base + "-" + str(number)
        number += 1
    return name

def save_conversation(agent, name):
    """state.json: what the agent carries right now (since its last checkpoint), so /open can go on. it is replaced every
    time. the log next to it is what keeps everything"""
    data = {"mode": agent.mode, "messages": agent.messages[1:]}   # [1:] = without the system message, it's rebuilt on open
    write_text(os.path.join(conversation_folder(name), "state.json"), json.dumps(data, indent=1, ensure_ascii=False))

def convert_old(name):
    """a conversation saved the old way, as Conversations/<name>.json, becomes a folder: its messages go into state.json,
    its summary (if it had one) into checkpoint.md. the old file is kept in the folder, as old.json"""
    with open(old_file(name), encoding="utf-8") as f:
        data = json.load(f)
    folder = conversation_folder(name)
    os.makedirs(folder)
    state = {"mode": data.get("mode", "ask"), "messages": data.get("messages", [])}
    write_text(os.path.join(folder, "state.json"), json.dumps(state, indent=1, ensure_ascii=False))
    if data.get("summary"):
        write_text(os.path.join(folder, "checkpoint.md"),
                   "## Earlier conversation (a summary, from before checkpoints existed)\n" + data["summary"])
    os.rename(old_file(name), os.path.join(folder, "old.json"))

def open_conversation(name, current):
    """a fresh main agent with the saved conversation inside. returns None if there is no such conversation, or if
    another instance has it open"""
    if not exists(name):
        print("no conversation called '" + name + "'. /list shows them")
        return None
    if not locks.take(lock_of(name)):                             # open in another instance: both would save over each other
        print("'" + name + "' is open in another instance. close it there first")
        return None
    if not os.path.isdir(conversation_folder(name)):
        convert_old(name)                                         # saved the old way: becomes a folder now
    data = {"mode": "ask", "messages": []}                        # a folder without state.json (nothing finished yet): empty
    state = os.path.join(conversation_folder(name), "state.json")
    if os.path.isfile(state):
        with open(state, encoding="utf-8") as f:
            data = json.load(f)
    agent = new_main_agent(name)
    agent.mode = data["mode"]
    agent.messages = [{"role": "system", "content": agent.build_system()}] + data["messages"]   # new system message (memory may have changed) + the saved turns
    agent.record("opened", messages=len(data["messages"]))
    if name != current:
        locks.release(lock_of(current))                           # the one you leave is free for other instances again
    print("opened " + name + ": " + str(len(data["messages"])) + " messages")
    return agent

def list_conversations(current):
    found = []
    if os.path.isdir(CONVERSATIONS_DIR):
        for file in sorted(os.listdir(CONVERSATIONS_DIR)):
            folder = os.path.join(CONVERSATIONS_DIR, file)
            if os.path.isfile(os.path.join(folder, "state.json")) or os.path.isfile(os.path.join(folder, "log.jsonl")):
                found.append(file)                                # a conversation folder
            elif file.endswith(".json"):
                found.append(file[:-5])                           # one saved the old way
    for name in found:
        mark = ""
        if name != current and not locks.free(lock_of(name)):
            mark = " (open in another instance)"
        print(("* " if name == current else "  ") + name + mark)  # * = the one you're in
    if current not in found:
        print("* " + current + " (nothing said yet, not saved)")

def rename_conversation(old, new, current, agent):
    """returns the name of the current conversation afterwards (it changes if you renamed the current one)"""
    if not new or "/" in new or "\\" in new or new.startswith("."):
        print("invalid name")
    elif not exists(old):
        print("no conversation called '" + old + "'")
    elif exists(new):
        print("'" + new + "' exists already")
    elif not locks.take(lock_of(old)):                            # yours, the current one, is taken already: that's fine
        print("'" + old + "' is open in another instance. it can be renamed when it is closed there")
    elif not locks.take(lock_of(new)):
        if old != current:
            locks.release(lock_of(old))
        print("'" + new + "' is in use by another instance")
    else:
        if os.path.isdir(conversation_folder(old)):
            os.rename(conversation_folder(old), conversation_folder(new))
        else:
            os.rename(old_file(old), old_file(new))               # saved the old way: stays a file until it is opened
        locks.release(lock_of(old))
        print("renamed " + old + " -> " + new)
        if current == old:
            agent.moved(conversation_folder(old), conversation_folder(new))   # it writes into the new folder from now on
            return new                                            # you are in it: its new name stays locked for you
        locks.release(lock_of(new))
    return current


HELP = """commands:
  /new                 start a new conversation (the current one stays saved)
  /list                show saved conversations
  /open <name>         continue a saved conversation (not one that is open in another instance)
  /rename <old> <new>  rename a saved conversation
  /mode ask|auto       ask = the agent may ask you questions. auto = it decides on its own (just /mode shows the current one)
  /sandbox ...         look at the sandboxes, internet on/off, a shell (a bare /sandbox shows the subcommands)
  /help                this list
  /exit  (or /quit)    leave. the conversation is saved already; this instance's sandbox is stopped
anything else is a message to the agent. ctrl+c also leaves."""


if __name__ == "__main__":                                        # runs only when you start main.py directly, not when another file imports it
    locks.start()                                                 # this instance's own lock: the others see that it runs
    atexit.register(locks.stop)                                   # runs last (atexit goes backwards): every lock is given back
    atexit.register(sandbox.shutdown)                             # whatever happens, python stops this instance's sandbox on the way out
    if sandbox.available():
        sandbox.cleanup()                                         # sandboxes left over by crashed instances are removed first
    else:
        print("podman not found: sandbox tools will not work")
    current = new_name()                                          # a clean new conversation at every start
    agent = new_main_agent(current)
    print("model: " + MODEL + " | tools: " + str(len(agent.tools)) + " | skills: " + (", ".join(SKILLS) or "none")
          + " | templates: " + (", ".join(templates()) or "none") + " | sandboxes: " + (", ".join(sandbox.names()) or "none"))
    print("conversation: " + current + "   (/help for commands)")

    try:
        while True:                                               # chat forever, until /exit or ctrl+c
            text = input("\n>>> ").strip()
            if text == "":
                continue
            words = text.split()

            if words[0] == "/new":
                agent.close()                                     # subagents still waiting for an answer end with their conversation
                locks.release(lock_of(current))                   # free for other instances again
                current = new_name()
                agent = new_main_agent(current)
                print("new conversation: " + current)
            elif words[0] == "/list":
                list_conversations(current)
            elif words[0] == "/open" and len(words) == 2:
                opened = open_conversation(words[1], current)
                if opened:
                    agent.close()
                    agent = opened
                    current = words[1]
            elif words[0] == "/rename" and len(words) == 3:
                current = rename_conversation(words[1], words[2], current, agent)
            elif words[0] == "/mode":
                if len(words) == 2 and words[1] in ("ask", "auto"):
                    agent.mode = words[1]
                    agent.refresh_system()                        # the mode is part of the system prompt, so rebuild it
                    agent.record("mode", mode=words[1])
                    if len(agent.messages) > 1:
                        save_conversation(agent, current)         # so /open finds it in this mode too
                print("mode: " + agent.mode)
            elif words[0] == "/sandbox":
                sandbox.command(words[1:])
            elif words[0] == "/help":
                print(HELP)
            elif words[0] in ("/exit", "/quit"):
                break
            elif text.startswith("/"):
                print("unknown command. /help shows the list")
            else:
                load_skills()                                     # skills another instance made or changed meanwhile: in the
                agent.refresh_system()                            # menu now. (an unchanged system prompt stays the same text)
                try:
                    agent.ask(text)
                except Exception as e:                            # the model or the connection failed: say so, but keep chatting
                    print("\nerror: " + type(e).__name__ + ": " + str(e))   # e.g. "ModuleNotFoundError: No module named 'mcp'"
                    print("(what the agent did so far is kept. if it did nothing yet, your message was taken back: just send it again)")
                if len(agent.messages) > 1:                       # only if something is in it besides the system message
                    save_conversation(agent, current)
    except KeyboardInterrupt:
        print()

    agent.close()                                                 # subagents still waiting for an answer: their transcripts are closed properly
    sandbox.shutdown()                                            # stop this instance's sandbox. its project is free again
    print("bye")
