import sandbox

def run(agent, name):
    return sandbox.create_project(name)

TOOL = {
    "name": "create_project",
    "description": "Create a new, empty project folder in the user's Shared/ folder. Then mount_project mounts it into your "
                   "sandbox. Check the list first (check_projects): if the work belongs to an existing project, use that one.",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string", "description": "letters, digits, - _ . only, e.g. sales-2026"}},
                   "required": ["name"]},
}
