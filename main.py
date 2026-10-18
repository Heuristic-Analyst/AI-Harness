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
#   Conversations/           your conversations (.json), Conversations/agents/ the subagent transcripts (.md)
#
# setup once: pip install -r requirements.txt, and podman installed (on mac/windows also `podman machine start`)

import os
import json
import atexit
from config import *
from agent import Agent
import sandbox


def new_main_agent():
    soul = read_text(SOUL_FILE) or "You are a helpful assistant."    # the soul is the start of the system prompt. empty file? fallback
    return Agent("main", instructions=soul, tools="all", skills="all", memory=True)

def conversation_file(name):
    return os.path.join(CONVERSATIONS_DIR, name + ".json")

def new_name():
    return free_name(CONVERSATIONS_DIR, timestamp(), ".json")     # e.g. 20261007-14-05-09, with -2 added if that one exists already

def save_conversation(agent, name):
    data = {"mode": agent.mode, "summary": agent.summary, "messages": agent.messages[1:]}   # [1:] = without the system message, it's rebuilt on open
    write_text(conversation_file(name), json.dumps(data, indent=1, ensure_ascii=False))

def open_conversation(name):
    """a fresh main agent with the saved conversation inside. returns None if there is no such conversation"""
    if not os.path.isfile(conversation_file(name)):
        print("no conversation called '" + name + "'. /list shows them")
        return None
    with open(conversation_file(name), encoding="utf-8") as f:
        data = json.load(f)
    agent = new_main_agent()
    agent.mode = data["mode"]
    agent.summary = data["summary"]
    agent.messages = [{"role": "system", "content": agent.build_system()}] + data["messages"]   # new system message (memory may have changed) + the saved turns
    print("opened " + name + ": " + str(len(data["messages"])) + " messages")
    return agent

def list_conversations(current):
    found = []
    if os.path.isdir(CONVERSATIONS_DIR):
        for file in sorted(os.listdir(CONVERSATIONS_DIR)):
            if file.endswith(".json"):
                found.append(file[:-5])
    for name in found:
        print(("* " if name == current else "  ") + name)         # * = the one you're in
    if current not in found:
        print("* " + current + " (nothing said yet, not saved)")

def rename_conversation(old, new, current):
    """returns the name of the current conversation afterwards (it changes if you renamed the current one)"""
    if not new or "/" in new or "\\" in new:
        print("invalid name")
    elif not os.path.isfile(conversation_file(old)):
        print("no conversation called '" + old + "'")
    elif os.path.exists(conversation_file(new)):
        print("'" + new + "' exists already")
    else:
        os.rename(conversation_file(old), conversation_file(new))
        print("renamed " + old + " -> " + new)
        if current == old:
            return new
    return current


HELP = """commands:
  /new                 start a new conversation (the current one stays saved)
  /list                show saved conversations
  /open <name>         continue a saved conversation
  /rename <old> <new>  rename a saved conversation
  /mode ask|auto       ask = the agent may ask you questions. auto = it decides on its own (just /mode shows the current one)
  /sandbox ...         look at the sandboxes, internet on/off, a shell (a bare /sandbox shows the subcommands)
  /help                this list
  /exit  (or /quit)    leave. the conversation is saved already; this instance's sandbox is stopped
anything else is a message to the agent. ctrl+c also leaves."""


if __name__ == "__main__":                                        # runs only when you start main.py directly, not when another file imports it
    atexit.register(sandbox.shutdown)                             # whatever happens, python stops this instance's sandbox on the way out
    if sandbox.available():
        sandbox.cleanup()                                         # sandboxes left over by crashed instances are removed first
    else:
        print("podman not found: sandbox tools will not work")
    agent = new_main_agent()                                      # a clean new conversation at every start
    current = new_name()
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
                agent = new_main_agent()
                current = new_name()
                print("new conversation: " + current)
            elif words[0] == "/list":
                list_conversations(current)
            elif words[0] == "/open" and len(words) == 2:
                opened = open_conversation(words[1])
                if opened:
                    agent.close()
                    agent = opened
                    current = words[1]
            elif words[0] == "/rename" and len(words) == 3:
                current = rename_conversation(words[1], words[2], current)
            elif words[0] == "/mode":
                if len(words) == 2 and words[1] in ("ask", "auto"):
                    agent.mode = words[1]
                    agent.refresh_system()                        # the mode is part of the system prompt, so rebuild it
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
