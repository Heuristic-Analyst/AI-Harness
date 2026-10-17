import sandbox

def run(agent, name=None):
    return sandbox.status(name)                                   # only looks, never changes anything. the same text as /sandbox check

TOOL = {
    "name": "check_sandbox",
    "description": "Check the sandboxes without changing anything: which exist, which one is running (only one can), whether its "
                   "network is on, and whether its image is built. Without a name: an overview of all. Call it before open_sandbox "
                   "or close_sandbox, so you know whether a sandbox already runs (then sandbox_shell works and you don't open one) "
                   "or not (then open one if the task needs it).",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string", "description": "a sandbox name for details, or leave it out for all"}}},
}
