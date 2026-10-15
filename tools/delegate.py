from config import MAX_CHILDREN, MAX_DEPTH

def run(agent, task, template=None, instructions=None, tools=None, skills=None):
    return agent.delegate(task, template, instructions, tools, skills)   # the logic lives in Agent.delegate (agent.py)

TOOL = {
    "name": "delegate",
    "description": "Create a subagent and give it one task; you get its report back. Either name a template (a ready-made subagent: "
                   "the Templates) OR write instructions for a one-off subagent, optionally with its "
                   "tools and skills. The subagent starts with an empty context: it knows only its instructions (either template or instructions, as said before) and your task, so put "
                   "every fact it needs into the task. Several delegate calls in one reply run at the same time = parallel. The report starts with "
                   "DONE, BLOCKED or QUESTION; answer a QUESTION with the tool tell, so tell(id, answer), it continues with its full context. Your subagents "
                   "end when your current task ends, except the ones waiting for an answer to their QUESTION: they stay alive, so you may "
                   "pass the question on and answer later with tell. "
                   "Limits: " + str(MAX_CHILDREN) + " live subagents, " + str(MAX_DEPTH) + " levels of depth in total.",
    "parameters": {"type": "object",
                   "properties": {"task": {"type": "string", "description": "objective, all needed context, expected output, limits"},
                                  "template": {"type": "string", "description": "name of a template, e.g. worker"},
                                  "instructions": {"type": "string", "description": "who the subagent is, if no template"},
                                  "tools": {"type": "array", "items": {"type": "string"}, "description": "tool names, if not the default"},
                                  "skills": {"type": "array", "items": {"type": "string"}, "description": "skill names, default none"}},
                   "required": ["task"]},
}
