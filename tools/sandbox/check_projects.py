import sandbox

def run(agent):
    return sandbox.projects_status()                              # only looks, never changes anything

TOOL = {
    "name": "check_projects",
    "description": "List the project folders in the user's Shared/ folder, and for each whether it is free, mounted by you, or "
                   "mounted by another instance. Also says what this instance has mounted, and about /workspace/common, the "
                   "folder every instance shares. Call it before mount_project or open_sandbox with a project.",
    "parameters": {"type": "object", "properties": {}},
}
