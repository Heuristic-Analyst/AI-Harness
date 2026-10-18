import locks
from . import _skillfile                                      # the helper next to this file
from config import SKILLS, load_skills

def run(agent, name, description, body):
    if not locks.wait_take("skills"):                         # one instance at a time changes skills
        return "not saved: another instance is changing a skill right now. try again"
    try:
        load_skills()                                         # the menu as it is now, with what other instances made meanwhile
        return create(agent, name, description, body)
    finally:
        locks.release("skills")

def create(agent, name, description, body):
    problem = _skillfile.check_name(name)
    if problem:
        return problem
    if name in SKILLS:
        if SKILLS[name]["editable"]:
            return "you already have a skill called '" + name + "'. change it with edit_skill, or pick another name"
        return "'" + name + "' is the name of one of the user's skills. pick another name"
    problem = _skillfile.write(agent, name, description, body)
    if problem:
        return problem
    return "created skill '" + name + "' in Skills/Learned (editable). it is in your skill list now; load it with load_skill"

TOOL = {
    "name": "create_skill",
    "description": "Save a new skill: step-by-step instructions you follow the next time a similar task comes up. Create one "
                   "when you solved a task that will likely come again and you had to work out how (the steps, the "
                   "pitfalls), or when the user asks you to remember how to do something. Not for facts about the user "
                   "(that is memory) and not for one-off tasks. Check your skill list first: improve an existing skill "
                   "instead of making a second one. The skill is saved in Skills/Learned, marked editable, and usable "
                   "right away. Tell the user in one short sentence what you saved.",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string", "description": "lowercase letters, digits and hyphens, e.g. clean-csv-files"},
                                  "description": {"type": "string", "description": "ONE line that says when to use it, starting "
                                                  "with 'Use when ...'. It is all you see of the skill until you load it, so "
                                                  "it decides whether you ever use it"},
                                  "body": {"type": "string", "description": "the instructions in markdown, short: a title, when "
                                           "to use it, numbered steps, pitfalls. no header, the tool writes it"}},
                   "required": ["name", "description", "body"]},
}
