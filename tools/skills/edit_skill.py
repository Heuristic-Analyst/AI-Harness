from . import _skillfile
from config import SKILLS

def run(agent, name, body, description=None):
    problem = _skillfile.may_change(name)
    if problem:
        return problem
    problem = _skillfile.write(agent, name, description or SKILLS[name]["description"], body,   # no description: keep the old one
                               path=_skillfile.file_of(name))                                    # its real file, wherever it is
    if problem:
        return problem
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
