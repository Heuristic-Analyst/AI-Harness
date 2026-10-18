import sandbox

def run(agent, name, project=None):
    return sandbox.open_sandbox(name, project)                    # the agent picks the sandbox. the user is not asked

TOOL = {
    "name": "open_sandbox",
    "description": "Start a sandbox, so sandbox_shell and the notebooks work. Pick it by what it is made of: check_sandbox shows "
                   "every sandbox's Containerfile. Only one sandbox runs per instance: to switch, close_sandbox first. Every "
                   "start is clean, exactly as its Containerfile says. /workspace/common is always mounted, shared with every "
                   "other instance. Give a project to mount that project folder too (check_projects lists them); mounting "
                   "it later with mount_project restarts the sandbox, so if you already know the project, give it here.",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string", "description": "the sandbox, e.g. python"},
                                  "project": {"type": "string", "description": "optional: a project folder to mount at "
                                              "/workspace/<project>. a new name creates the folder"}},
                   "required": ["name"]},
}
