def run(agent, id, message):
    return agent.tell(id, message)

TOOL = {
    "name": "tell",
    "description": "Send a follow-up message to one of your live subagents (it keeps its full context) and get its next report. "
                   "Use the id delegate returned, e.g. worker-1. One message per subagent per reply.",
    "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "message": {"type": "string"}},
                   "required": ["id", "message"]},
}
