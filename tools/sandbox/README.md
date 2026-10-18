# sandbox

The agent's only way to run commands: inside a Podman container, never on your machine. The work itself is done in `sandbox.py` in the project folder; these tools only call it.

| Tool | Who gets it | What it does |
|---|---|---|
| `sandbox_shell` | all | Runs a bash command inside this instance's sandbox and returns what it printed. |
| `check_sandbox` | main only | Shows every sandbox with its whole Containerfile, whether its image is built, and which one runs here. Changes nothing. |
| `open_sandbox` | main only | Starts the sandbox the agent picked, optionally with a project mounted. You are not asked. |
| `close_sandbox` | main only | Stops this instance's sandbox. Its project is free again; files in the mounted folders stay. |
| `check_projects` | main only | Lists the project folders in `Shared/`: free, mounted here, or mounted by another instance. Changes nothing. |
| `mount_project` | main only | Mounts one existing project folder at `/workspace/<project>`. Restarts the sandbox. |
| `unmount_project` | main only | Unmounts the project, so other instances can mount it. Restarts the sandbox. |
| `create_project` | main only | Creates a new, empty project folder in `Shared/`. |
| `delete_project` | main only | Deletes a project folder with everything in it. Only when the user asked; not while any sandbox has it mounted. |
| `rename_project` | main only | Renames a project folder. Not while any sandbox has it mounted. |

## Good to know

- An instance is one running `main.py`. Each instance has at most one sandbox running, in its own container. Several instances can run at the same time, with the same sandbox or different ones.
- The Containerfile is the whole truth. The image is built from it again at every start (unchanged steps come from Podman's cache, so that's quick), and nothing is ever saved: whatever the agent installs is gone when the sandbox stops. Need something for good? Add it to the Containerfile.
- What a sandbox sees of your machine:
  - `Shared/common/` at `/workspace/common`: always, in every instance. That's where instances share files. It can't be unmounted.
  - `Shared/<project>/` at `/workspace/<project>`: one project at most, mounted by the agent. While one instance has it, no other can mount it.
  - `Shared/Notebooks_Engine/` at `/workspace/Notebooks_Engine`, read-only: the notebook engine.
  - `Shared/<project>/.graph/`, read-only, if the project has one: the plan and state of a project run. Only the node tools change it, from outside.
- Nothing else of your machine, not even the rest of `Shared/`. `common` and `Notebooks_Engine` are not projects: no project tool creates, mounts, renames or deletes them.
- All of them are mounted `noexec`, so scripts there run through an interpreter (`python x.py`, `bash x.sh`).
- Podman can't add or remove a folder of a running container, so `mount_project` and `unmount_project` restart the sandbox. Opening a sandbox with the project right away avoids that.
- A project counts as taken while a container of a running instance has it. When an instance ends, gracefully or in a crash, its project is free again: a crashed instance's container is removed the next time any instance looks.
- Only one sandbox runs per instance, and inside it the agent is root.
- A command that runs longer than `MAX_TOOL_TIMEOUT` seconds (600) is stopped. Longer jobs go in the background, with their output in a file.
- The network is off at every start. Only you can turn it on, with `/sandbox net on`; the agent has no tool for it. A restart by `mount_project` or `unmount_project` keeps it as it was.
- Only the main agent gets the tools that open, close, check or mount. Subagents run their commands with `sandbox_shell` in their parent's sandbox.
- Each container carries labels (owner, sandbox, project). That's how an instance finds its own, so containers you start yourself are never touched.
