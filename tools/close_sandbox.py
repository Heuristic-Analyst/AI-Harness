import sandbox

def run(agent):
    return sandbox.close_for_agent()

TOOL = {
    "name": "close_sandbox",
    "description": "Stop the running sandbox. Everything installed or changed inside is lost unless the user saved it; "
                   "files in /workspace stay.",
    "parameters": {"type": "object", "properties": {}},
}
