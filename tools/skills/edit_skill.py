import locks
from . import _skillfile
from config import SKILLS, load_skills, read_text

def run(agent, name, body, description=None):
    if not locks.wait_take("skills"):                         # one instance at a time changes skills
        return "not saved: another instance is changing a skill right now. try again"
    try:
        load_skills()                                         # the menu as it is now, with what other instances changed meanwhile
        return edit(agent, name, body, description)
    finally:
        locks.release("skills")

def edit(agent, name, body, description):
    problem = _skillfile.may_change(name)
    if problem:
        return problem
    seen = agent.skills_seen.get(name)
    if seen is None:
        return "not saved: load the skill with load_skill first. edit_skill replaces its whole text"
    if read_text(_skillfile.file_of(name)) != seen:           # someone changed it in between: writing now would undo that
        return ("not saved: the skill changed since you loaded it (another running instance, or the user). "
                "load_skill it again, put your change into what is there now, then edit_skill")
    problem = _skillfile.write(agent, name, description or SKILLS[name]["description"], body,   # no description: keep the old one
                               path=_skillfile.file_of(name))                                    # its real file, wherever it is
    if problem:
        return problem
    agent.skills_seen[name] = read_text(_skillfile.file_of(name))   # what is there now is what this agent wrote
    return "updated skill '" + name + "'"

TOOL = {
    "name": "edit_skill",
    "description": "Rewrite one of your own skills (those marked [editable] in your skill list). Load it with load_skill "
                   "first, then pass the WHOLE new body, not only the change: what you leave out is gone. The user's "
                   "skills can't be edited. Tell the user in one short sentence what you changed.",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string"},
                                  "body": {"type": "string", "description": "the complete new instructions in markdown"},
                                  "description": {"type": "string", "description": "a new one-line 'Use when ...'. leave it "
                                                  "out to keep the current one"}},
                   "required": ["name", "body"]},
}
