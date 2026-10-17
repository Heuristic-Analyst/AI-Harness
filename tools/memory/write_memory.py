from config import MEMORY_FILE, write_text

def run(agent, content):                                          # the model never passes a path: this can only ever touch MEMORY.md
    write_text(MEMORY_FILE, content)
    agent.refresh_system()                                        # the copy in the system prompt is updated right away
    return "saved (" + str(len(content)) + " characters)"

TOOL = {
    "name": "write_memory",
    "description": "Replace your memory file. Pass the WHOLE new file, not only the change: anything you leave out is deleted.",
    "parameters": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]},
}
