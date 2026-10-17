from config import SKILLS, read_text

def run(agent, name):
    if name not in agent.skills:                                  # only this agent's skills, never a file path from the model
        return "no skill called '" + name + "'. yours: " + (", ".join(agent.skills) or "none")
    return read_text(SKILLS[name]["path"])                        # the whole SKILL.md goes back to the model as a tool result

TOOL = {
    "name": "load_skill",
    "description": "Load the full instructions of a skill from the list in your system prompt. Call it before doing a task that matches a skill.",
    "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
}
