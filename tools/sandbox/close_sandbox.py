import sandbox

def run(agent):
    return sandbox.close_sandbox()

TOOL = {
    "name": "close_sandbox",
    "description": "Stop this instance's sandbox. Everything installed or started inside is gone; the files in /workspace/common "
                   "and in the mounted project stay, and the project is free for other instances again. Needed before "
                   "open_sandbox can start another one. When the user exits, the sandbox is stopped anyway.",
    "parameters": {"type": "object", "properties": {}},
}
