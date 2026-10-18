import sandbox

def run(agent, name, new_name):
    return sandbox.rename_project(name, new_name)

TOOL = {
    "name": "rename_project",
    "description": "Rename a project folder in the user's Shared/ folder. Not possible while any sandbox has it mounted (yours "
                   "too: unmount_project first), and common and Notebooks_Engine can't be renamed. Tell the user in one short "
                   "sentence what you renamed.",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string", "description": "the project's name now"},
                                  "new_name": {"type": "string", "description": "letters, digits, - _ . only, e.g. sales-2026"}},
                   "required": ["name", "new_name"]},
}
