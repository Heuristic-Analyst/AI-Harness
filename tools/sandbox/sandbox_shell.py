import sandbox
from config import MAX_TOOL_TIMEOUT

def run(agent, command):
    return sandbox.exec(command, MAX_TOOL_TIMEOUT)                # runs inside the sandbox, never on the user's machine. the limit is fixed

TOOL = {
    "name": "sandbox_shell",
    "description": "Run a bash command inside this instance's sandbox (a Linux container, you are root in it). Two folders in it "
                   "are the user's and are kept: /workspace/common (shared with every other instance) and /workspace/<project> "
                   "if a project is mounted. The command starts in the project, or in /workspace/common when none is mounted. "
                   "Everything else inside is yours, install and build freely, but it is gone when the sandbox stops. Files in "
                   "the user's folders can't be executed directly: run them with an interpreter (python x.py, bash x.sh). "
                   "Returns what the command printed. A command still running after " + str(MAX_TOOL_TIMEOUT) + " seconds "
                   "is stopped - set by the user; for longer jobs, start them in the background with their output in a file "
                   "(nohup ... > x.log 2>&1 &) and check the file later.",
    "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
}
