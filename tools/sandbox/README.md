# sandbox

The agent's only way to run commands: inside a Podman container, never on your machine. The work itself is done in `sandbox.py` in the project folder; these tools only call it.

| Tool | Who gets it | What it does |
|---|---|---|
| `sandbox_shell` | all | Runs a bash command inside the running sandbox and returns what it printed. |
| `check_sandbox` | main only | Shows which sandboxes exist, which one runs, and whether its network is on. Changes nothing. |
| `open_sandbox` | main only | Asks **you** which sandbox to start. Nothing starts without your choice. |
| `close_sandbox` | main only | Stops the running sandbox. Whatever wasn't saved is gone; files in `/workspace` stay. |

## Good to know

- Only one sandbox runs at a time, and inside it the agent is root.
- `/workspace` inside is your `Shared/` folder: the same files, two names. It is mounted `noexec`, so scripts there run through an interpreter (`python x.py`, `bash x.sh`).
- A command that runs longer than `MAX_TOOL_TIMEOUT` seconds (600) is stopped. Longer jobs go in the background, with their output in a file.
- The network is off at every start. Only you can turn it on, with `/sandbox net on`.
- The agent can stop a sandbox but never save one. Only you can, with `/sandbox save`.
