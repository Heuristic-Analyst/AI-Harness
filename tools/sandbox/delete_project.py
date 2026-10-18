import sandbox

def run(agent, name):
    return sandbox.delete_project(name)

TOOL = {
    "name": "delete_project",
    "description": "Delete a project folder in the user's Shared/ folder, with EVERYTHING in it. It can't be undone: only do it "
                   "when the user asked you to delete that project. Not possible while any sandbox has it mounted (yours "
                   "too: unmount_project first). common and Notebooks_Engine can't be deleted. Tell the user in one short "
                   "sentence what you deleted.",
    "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
}
