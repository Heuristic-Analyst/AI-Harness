import sandbox

def run(agent, name=None):
    return sandbox.status(name)                                   # only looks, never changes anything. the same text as /sandbox check

TOOL = {
    "name": "check_sandbox",
    "description": "Look at the sandboxes without changing anything: each one's whole Containerfile (what is installed in it, so "
                   "what it is good for), whether its image is built, and which one runs in this instance (one at most). "
                   "Without a name: all of them. Call it to pick the right sandbox before open_sandbox, and to see whether one "
                   "already runs (then sandbox_shell works and you don't open one).",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string", "description": "a sandbox name for only that one, or leave it out for all"}}},
}
