import os
import locks
from . import _skillfile
from config import load_skills

def run(agent, name):
    if not locks.wait_take("skills"):                         # one instance at a time changes skills
        return "not deleted: another instance is changing a skill right now. try again"
    try:
        load_skills()                                         # the menu as it is now, with what other instances changed meanwhile
        return delete(agent, name)
    finally:
        locks.release("skills")

def delete(agent, name):
    problem = _skillfile.may_change(name)
    if problem:
        return problem
    path = _skillfile.file_of(name)                           # its real file, wherever it is in Skills/Learned
    os.remove(path)
    folder = os.path.dirname(path)
    if not os.listdir(folder):                                # only the empty folder goes. anything else in it stays
        os.rmdir(folder)
    load_skills()
    agent.refresh_system()                                    # gone from the agent's skill list at once
    return "deleted skill '" + name + "'"

TOOL = {
    "name": "delete_skill",
    "description": "Delete one of your own skills (those marked [editable] in your skill list), e.g. when it turned out "
                   "wrong or is no longer useful. It can't be undone. The user's skills can't be deleted. Tell the user "
                   "in one short sentence what you deleted.",
    "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
}
