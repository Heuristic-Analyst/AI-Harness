import sandbox

def run(agent, name):
    return sandbox.mount_project(name)

TOOL = {
    "name": "mount_project",
    "description": "Mount a project folder into this instance's sandbox, at /workspace/<name>. It becomes the working folder. "
                   "A project is a folder directly in the user's Shared/ folder (check_projects lists them, create_project "
                   "makes a new one). One project at a time: mounting another one unmounts the current one. A project another instance has "
                   "mounted can't be mounted. This RESTARTS the sandbox, because a running sandbox can't get a new folder: "
                   "whatever was installed or started inside since its start is gone, open notebooks are closed. So mount "
                   "first, then install and work.",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string", "description": "the project folder, e.g. website"}},
                   "required": ["name"]},
}
