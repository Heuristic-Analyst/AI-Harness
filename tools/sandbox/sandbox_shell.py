import sandbox
from config import MAX_TOOL_TIMEOUT

def run(agent, command):
    return sandbox.exec(command, MAX_TOOL_TIMEOUT)                # runs inside the sandbox, never on the user's machine. the limit is fixed

TOOL = {
    "name": "sandbox_shell",
    "description": "Run a bash command inside the running sandbox (a plain Linux container, you are root in it). /workspace is the "
                   "shared folder the user can see; files there cannot be executed directly, run them with an interpreter "
                   "(python x.py, bash x.sh). Everything else inside is yours: install, build, test. Returns what the command printed. "
                   "A command still running after " + str(MAX_TOOL_TIMEOUT) + " seconds is stopped - set by the user; for longer jobs, start them in "
                   "the background with their output in a file (nohup ... > /workspace/x.log 2>&1 &) and check the file later.",
    "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
}