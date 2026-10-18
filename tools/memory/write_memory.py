import locks
from config import MEMORY_FILE, read_text, write_text

def run(agent, content):                                          # the model never passes a path: this can only ever touch MEMORY.md
    if agent.memory_seen is None:
        return "not saved: call read_memory first. write_memory replaces the whole file"
    if not locks.wait_take("memory"):                             # another instance saves it this very moment: wait for it
        return "not saved: another instance is saving the memory right now. try again"
    try:
        if read_text(MEMORY_FILE) != agent.memory_seen:           # someone saved in between: writing now would undo that
            return ("not saved: the memory file changed since you read it (another running instance, or the user). "
                    "call read_memory again, put your change into what is there now, then write_memory")
        write_text(MEMORY_FILE, content)
        agent.memory_seen = read_text(MEMORY_FILE)                # what is there now is what this agent wrote
    finally:
        locks.release("memory")
    agent.refresh_system()                                        # the copy in the system prompt is updated right away
    return "saved (" + str(len(content)) + " characters)"

TOOL = {
    "name": "write_memory",
    "description": "Replace your memory file. Pass the WHOLE new file, not only the change: anything you leave out is deleted.",
    "parameters": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]},
}
