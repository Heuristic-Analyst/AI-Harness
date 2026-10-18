from config import MEMORY_FILE, read_text

def run(agent):
    agent.memory_seen = read_text(MEMORY_FILE)                    # what it saw: write_memory checks nobody changed it since
    return agent.memory_seen or "(memory is empty)"               # always the file as it is now, even if the system prompt is older

TOOL = {
    "name": "read_memory",
    "description": "Read your memory file as it is right now. Always call it right before write_memory.",
    "parameters": {"type": "object", "properties": {}},
}
