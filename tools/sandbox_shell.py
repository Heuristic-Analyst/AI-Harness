import sandbox
from config import TOOL_TIMEOUT, MAX_TOOL_TIMEOUT

def run(agent, command, timeout=None):
    seconds = min(max(int(timeout or TOOL_TIMEOUT), 1), MAX_TOOL_TIMEOUT)   # between 1 and the maximum. 0 would mean "no limit" to `timeout`
    return sandbox.exec(command, seconds)                         # runs inside the sandbox, never on the user's machine

TOOL = {
    "name": "sandbox_shell",
    "description": "Run a bash command inside the running sandbox (a plain Linux container, you are root in it). /workspace is the "
                   "shared folder the user can see; files there cannot be executed directly, run them with an interpreter "
                   "(python x.py, bash x.sh). Everything else inside is yours: install, build, test. Returns what the command printed.",
    "parameters": {"type": "object",
                   "properties": {"command": {"type": "string"},
                                  "timeout": {"type": "integer", "description": "seconds to wait, default " + str(TOOL_TIMEOUT)
                                                                                + ", at most " + str(MAX_TOOL_TIMEOUT)}},
                   "required": ["command"]},
}
