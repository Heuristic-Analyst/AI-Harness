import sandbox

def run(agent):
    return sandbox.open_for_agent()                               # the user picks which one. nothing runs without that choice

TOOL = {
    "name": "open_sandbox",
    "description": "Start a sandbox so sandbox_shell works. The user is asked which sandbox to start. Only one can run at a time.",
    "parameters": {"type": "object", "properties": {}},
}
