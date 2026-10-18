# config.py — all settings and folders in one place, plus a few small helpers everybody uses.
# every other file does `from config import *`, so every name in here is available there.

import os
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))     # the folder this project lives in. everything is found from here
if HERE not in sys.path:                               # so the tools find `import sandbox` and `from config import *` from anywhere
    sys.path.insert(0, HERE)

# Model
MODEL = "deepseek/deepseek-flash"      # any litellm model works, e.g. "anthropic/claude-sonnet-5", "openai/gpt-5", "ollama/llama3"
STREAM = True                          # True = reply arrives piece by piece. False = wait, then get it all at once.
EFFORT = "high"                        # thinking depth. low / medium / high everywhere, except DeepSeek: low / high / max

# What you see in the terminal (subagent transcripts always contain everything)
PRINT_THINKING = False                  # False = hide the THINKING blocks, show only answers
PRINT_TOOLS = True                     # False = hide the TOOL blocks (which tool was called, with what, and the result)
PRINT_SUBAGENT_TALK = False            # False = hide what the agent and its subagents say to each other (the delegate and tell calls).
                                       # the [started] / [reported DONE] lines stay, and the transcripts in Conversations/agents/ have it all

# Conversation size (see agent.py: nothing is summarized, the agent writes checkpoints. the log keeps everything)
CONTEXT_LIMIT = 500_000                # tokens an agent may use at most. keep it at or below the model's real limit
CHECKPOINT_AT = 0.60                   # after a task, the context is above 60% of CONTEXT_LIMIT? the agent writes its checkpoint,
                                       # then its context is cleared: system prompt (with the checkpoint) + the last KEEP_TASKS tasks
EMERGENCY_AT = 0.80                    # in the middle of a task, above 80%? old tool results become pointers to their files first.
                                       # still above? the agent writes its checkpoint right away, and the task goes on from there
KEEP_TASKS = 1                         # this many recent tasks stay word for word after a checkpoint. 0 or more (one task is
                                       # everything from one user input to the next)
RESULT_TO_FILE = 8_000                 # tool results longer than this (in characters) go into a file in the conversation folder.
                                       # the model gets the start and the end of it, and reads the rest with read_result
KEEP_RESULTS = 3                       # in an emergency, the newest tool results stay in the context as they are
REPORT_LIMIT = 8_000                   # a subagent's report should stay below this many characters: details go into files

# Subagents
MAX_CHILDREN = 5                       # subagents one agent may have alive at the same time
MAX_DEPTH = 3                          # you talk to depth 1. it may create depth 2, which may create depth 3, which may not create any
MAIN_ONLY_TOOLS = ["read_memory", "write_memory", "open_sandbox", "close_sandbox", "check_sandbox",   # subagents never get these,
                   "check_projects", "mount_project", "unmount_project",                               # whatever a template says.
                   "create_project", "delete_project", "rename_project",                               # they work in their
                   "create_skill", "edit_skill", "delete_skill"]                                       # parent's sandbox
DEFAULT_SUBAGENT_TOOLS = ["calculate", "load_skill", "sandbox_shell", "delegate", "tell",       # for a subagent made
                          "read_result", "search_result", "copy_result"]                       # without a template

# Sandbox (see sandbox.py)
CONTAINER_CMD = "podman"               # the container program. podman is rootless: "root" inside is just you outside
SANDBOX_MEMORY = "2g"                  # limits for a running sandbox, so a runaway script can't take your machine down
SANDBOX_CPUS = "2"
MAX_TOOL_TIMEOUT = 600                 # seconds a sandbox command may run before it is stopped. the same for every command

# Folders and files. want to rename something? change it here, nowhere else
ENV_FILE = os.path.join(HERE, ".env")
SOUL_FILE = os.path.join(HERE, "Ego", "SOUL.md")                  # who the main agent is. you write it, the agent only reads it
MEMORY_FILE = os.path.join(HERE, "Ego", "MEMORY.md")              # what the main agent remembers. it edits this with its tools
SKILLS_DIR = os.path.join(HERE, "Skills")                         # Skills/<name>/SKILL.md = your skills. the agent can't change them
LEARNED_SKILLS_DIR = os.path.join(SKILLS_DIR, "Learned")          # Skills/Learned/<name>/SKILL.md = skills the agent wrote itself.
                                                                  # the ONLY skills it may create, edit and delete (tools/skills/)
TEMPLATES_DIR = os.path.join(HERE, "Templates")                   # Templates/<name>.md = ready-made subagent: instructions, tools, skills
TOOLS_DIR = os.path.join(HERE, "tools")                           # tools/<folder>/<name>.py = one tool each, folders as deep as you like
SANDBOXES_DIR = os.path.join(HERE, "Sandboxes")                   # Sandboxes/<name>/Containerfile = one sandbox each
SHARED_DIR = os.path.join(HERE, "Shared")                         # the ONLY folder of your machine a sandbox sees parts of: common/ (always),
                                                                  # one project folder, and Notebooks_Engine read-only (see sandbox.py)
CONVERSATIONS_DIR = os.path.join(HERE, "Conversations")           # your conversations, one folder each: Conversations/<name>/
                                                                  # (state.json, log.jsonl, checkpoint.md, results/, agents/)
LOCKS_DIR = os.path.join(HERE, "Locks")                           # the lock files of all running instances (see locks.py)


# this running main.py (an "instance"): its process number, and when it started. the time makes it unique for good:
# after a restart (of main.py, or of the computer) another program may get the same process number, never the same id
INSTANCE = str(os.getpid()) + "-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")   # e.g. 48213-20261018165603


def read_text(path):
    if not os.path.isfile(path):                                  # missing file = empty text, no crash
        return ""
    with open(path, encoding="utf-8") as f:                       # "with" closes the file again when we're done
        return f.read().strip()

def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)             # folder missing? create it
    with open(path, "w", encoding="utf-8") as f:                  # "w" = replace the whole file
        f.write(text.strip() + "\n")

def timestamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H-%M-%S")   # e.g. 20261007-14-05-09

def free_name(folder, name, ending):
    """name, or name-2, name-3 ... the first one that has no file in folder yet.
    so two things named in the same second (timestamps) don't overwrite each other"""
    result = name
    number = 2
    while os.path.exists(os.path.join(folder, result + ending)):
        result = name + "-" + str(number)
        number += 1
    return result

def read_front_matter(path):
    """SKILL.md and templates start with a header between two '---' lines, one 'key: value' per line.
    returns the header as a dict, and the text after the header"""
    header = {}
    body = ""
    dashes = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip() == "---" and dashes < 2:              # a "---" line opens or closes the header
                dashes += 1
            elif dashes == 1 and ":" in line:                     # inside the header: "key: value"
                key, value = line.split(":", 1)
                header[key.strip()] = value.strip().strip('"\'')  # strip spaces, then quotes: "x" -> x
            elif dashes != 1:                                     # outside the header: the body
                body += line
    return header, body.strip()

def names_from(text):
    """'a, b, c' -> ['a', 'b', 'c']. used for the tools and skills lines in templates"""
    result = []
    for part in text.split(","):
        if part.strip():
            result.append(part.strip())
    return result


# API key: the line PROVIDER_API_KEY=... from .env, for the provider in MODEL. never touches the environment
provider = MODEL.split("/")[0].upper()                            # "deepseek/deepseek-flash" -> "DEEPSEEK"
API_KEY = None
for line in read_text(ENV_FILE).splitlines():
    if line.startswith(provider + "_API_KEY="):
        API_KEY = line.split("=", 1)[1].strip().strip('"\'')     # everything after the first "=", without quotes: "sk-..." -> sk-...


# Skills: the menu. only name + description; the instructions are loaded on demand with load_skill
SKILLS = {}                                                       # skill name -> description, file, and whether the agent may change it

def load_skills():
    """read the menu: your skills first, then the ones the agent wrote. at startup, and again whenever the agent
    creates, edits or deletes one. SKILLS is filled in place, so every file that imported it sees the new menu"""
    fresh = {}                                                    # read everything first...
    for folder, editable in ((SKILLS_DIR, False), (LEARNED_SKILLS_DIR, True)):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):                   # one subfolder per skill
            if not os.path.isdir(os.path.join(folder, name)):     # a file, e.g. Learned/README.md: not a skill
                continue
            path = os.path.join(folder, name, "SKILL.md")
            if not os.path.isfile(path):                          # a folder without SKILL.md is not a skill (e.g. Learned/ itself)
                continue
            header, body = read_front_matter(path)
            skill = header.get("name", name)
            if skill in fresh:                                    # same name as one of yours: yours wins, the agent's is skipped
                continue
            fresh[skill] = {"description": header.get("description", ""), "path": path,
                            "editable": editable}                 # decided by the folder, never by what the file claims
    SKILLS.clear()                                                # ...then swap it in at once, so an agent starting in another
    SKILLS.update(fresh)                                          # thread right now never sees a half-filled menu

load_skills()


# Templates: ready-made subagents. read fresh every time, so you can add one while the program runs
def templates():
    result = {}                                                   # name -> description, instructions, tools, skills
    if os.path.isdir(TEMPLATES_DIR):
        for file in sorted(os.listdir(TEMPLATES_DIR)):
            if file.endswith(".md"):
                header, body = read_front_matter(os.path.join(TEMPLATES_DIR, file))
                result[header.get("name", file[:-3])] = {
                    "description": header.get("description", ""),
                    "instructions": body,
                    "tools": names_from(header.get("tools", "")),
                    "skills": names_from(header.get("skills", "")),
                }
    return result
