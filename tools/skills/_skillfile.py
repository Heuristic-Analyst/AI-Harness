# _skillfile.py — what create_skill, edit_skill and delete_skill share. (the _ in front: not a tool, the tool loader skips it)
# they may only ever touch Skills/Learned/<name>/SKILL.md: the skills the agent wrote itself. your own skills are out of reach.
# whether a skill is editable is decided by its folder, never by what the file says about itself.

import os
import re
import datetime
from config import *

MARK = ("> Editable: you wrote this skill yourself. You may improve it with edit_skill or remove it with delete_skill. "
        "When you learn it is wrong or outdated, fix it.")    # written into every learned skill by these tools, never by the agent
MAX_BODY = 15_000                                          # characters. a skill is loaded whole into the conversation: keep it short

def check_name(name):
    """the name is also the folder name, so only safe characters. returns None if fine, otherwise the problem"""
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 40:
        return "invalid name: lowercase letters, digits and hyphens only, at most 40 characters, e.g. clean-csv-files"
    return None

def path_of(name):
    path = os.path.join(LEARNED_SKILLS_DIR, name, "SKILL.md")
    inside = os.path.realpath(LEARNED_SKILLS_DIR) + os.sep  # also through links: it must really be inside Skills/Learned
    if not os.path.realpath(path).startswith(inside):
        raise PermissionError("that path is outside Skills/Learned")
    return path

def file_of(name):
    """the real file of an existing learned skill (its folder may have another name than its header): checked to be inside"""
    path = SKILLS[name]["path"]
    if not os.path.realpath(path).startswith(os.path.realpath(LEARNED_SKILLS_DIR) + os.sep):
        raise PermissionError("that skill's file is outside Skills/Learned")
    return path

def editable_names():
    return ", ".join(s for s in SKILLS if SKILLS[s]["editable"]) or "none yet"

def may_change(name):
    """None if the agent may edit or delete this skill, otherwise why not"""
    problem = check_name(name)
    if problem:
        return problem
    if name not in SKILLS:
        return "there is no skill called '" + name + "'. your editable skills: " + editable_names()
    if not SKILLS[name]["editable"]:
        return "'" + name + "' is one of the user's skills: you can't change or delete it. your editable skills: " + editable_names()
    return None

def header_value(text):
    """one line, and safe for the header: GitHub reads it as YAML, where ': ' or a leading quote would break it"""
    text = " ".join(str(text).split())
    if ":" in text or "#" in text or text[:1] in "'\"[]{}>|*&!%@`,?-":
        text = '"' + text.replace('"', "'") + '"'
    return text

def clean_body(body):
    """the agent may pass back the whole text it got from load_skill. keep only its own part: no header, no mark"""
    body = str(body).strip()
    if body.startswith("---"):                             # a header block (with a name: line): drop it, the tools write their own.
        parts = body.split("\n---", 1)                     # a plain --- divider line at the top is left alone
        if len(parts) == 2 and "\nname:" in "\n" + parts[0]:
            body = parts[1].strip()
    if body.startswith("> Editable:"):
        body = body.split("\n", 1)[1].strip() if "\n" in body else ""
    return body

def write(agent, name, description, body, path=None):
    """write the skill file: header (with editable: yes), the mark, the body. then the agent's menu is updated right away.
    path: the existing file when editing; a new skill gets Skills/Learned/<name>/SKILL.md"""
    body = clean_body(body)
    description = " ".join(str(description or "").split())
    if not description:
        return "the description is empty. one line saying when to use the skill, e.g. 'Use when the user asks to clean a CSV file.'"
    if not body:
        return "the body is empty. write the instructions: when to use it, the steps, the pitfalls"
    if len(body) > MAX_BODY:
        return "too long (" + str(len(body)) + " characters, at most " + str(MAX_BODY) + "). a skill should be short: cut it down"
    text = ("---\nname: " + name + "\ndescription: " + header_value(description) + "\neditable: yes\n"
            "updated: " + datetime.date.today().isoformat() + "\n---\n\n" + MARK + "\n\n" + body)
    write_text(path or path_of(name), text)
    load_skills()                                          # the menu, read again from the folders
    agent.refresh_system()                                 # and the agent's system prompt with it: usable at once with load_skill
    return None
