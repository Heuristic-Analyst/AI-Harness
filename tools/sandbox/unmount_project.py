import sandbox

def run(agent):
    return sandbox.unmount_project()

TOOL = {
    "name": "unmount_project",
    "description": "Unmount the project from this instance's sandbox, so other instances can mount it. Its files stay in the "
                   "user's Shared/ folder. /workspace/common stays mounted, it can't be unmounted. This RESTARTS the sandbox: "
                   "whatever was installed or started inside since its start is gone, open notebooks are closed.",
    "parameters": {"type": "object", "properties": {}},
}
