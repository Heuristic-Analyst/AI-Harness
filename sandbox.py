# sandbox.py — the sandboxes: throwaway Linux containers where the agent may run anything.
# how it works: each folder in Sandboxes/ is one sandbox. its Containerfile says what it is made of (plain ubuntu by default).
# building it gives an IMAGE (a frozen snapshot). running it starts a CONTAINER (a copy of the image) that is deleted when it stops,
# so every start is clean. `/sandbox save` turns the running container into the sandbox's new image. only one runs at a time.
# the container sees exactly one folder of your machine: Shared/ (inside: /workspace), mounted so files there can't be executed.
# everything in here is podman commands; `podman(...)` below runs one and returns what it printed.

import os
import shutil
import subprocess
from config import *


NOT_FOUND = 127                                                   # the exit code shells use for "no such command"

def podman(*args, timeout=None):
    try:
        done = subprocess.run([CONTAINER_CMD] + list(args), capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:                                     # no podman command at all: an answer, not a crash
        return NOT_FOUND, CONTAINER_CMD + " not found"
    return done.returncode, (done.stdout + done.stderr).strip()

def available():
    return podman("info", "--format", "ok")[0] == 0               # podman missing, or not started (mac/windows: podman machine start)

NOT_AVAILABLE = CONTAINER_CMD + " is not installed or not running, so there are no sandboxes right now"

def names():
    if not os.path.isdir(SANDBOXES_DIR):
        return []
    return sorted(os.listdir(SANDBOXES_DIR))

def image(name):
    return "localhost/sandbox-" + name

def container(name):
    return "sandbox-" + name

def has_image(name):
    return podman("image", "exists", image(name))[0] == 0

def running():
    """the name of the running sandbox, or None. asked from podman every time, so it is always true"""
    code, out = podman("ps", "--filter", "name=^sandbox-", "--format", "{{.Names}}")
    if code == 0 and out:                                         # code != 0: podman failed, out is its error message, not a name
        return out.splitlines()[0][len("sandbox-"):]            # "sandbox-ubuntu" -> "ubuntu"
    return None


# --- building, starting, stopping ---
def build(name):
    print("[sandbox] building " + name + " from " + os.path.join("Sandboxes", name, "Containerfile") + " ...")
    try:
        done = subprocess.run([CONTAINER_CMD, "build", "-t", image(name), os.path.join(SANDBOXES_DIR, name)])   # shows the build log
    except FileNotFoundError:
        print("[sandbox] " + CONTAINER_CMD + " not found")
        return False
    return done.returncode == 0

def new(name, base=BASE_IMAGE):
    if not name.replace("-", "").isalnum():
        return "invalid name: letters, digits and hyphens only"
    if name in names():
        return "'" + name + "' exists already"
    write_text(os.path.join(SANDBOXES_DIR, name, "Containerfile"), "FROM " + base)   # that's the whole definition: one line
    return "created " + name + " (" + base + ")" if build(name) else "created the folder, but the build failed (see above)"

def run(name):
    if name not in names():
        return "no sandbox called '" + name + "'. /sandbox list shows them"
    if not has_image(name) and not build(name):
        return "build failed"
    os.makedirs(SHARED_DIR, exist_ok=True)
    code, out = podman("run", "-d", "--rm", "--name", container(name),   # --rm = deleted when it stops: every start is clean
                       "--network", "podman",                     # on the named network at birth, sealed right below
                       "--security-opt", "no-new-privileges",     # no way to gain more rights than it starts with
                       "--pids-limit", "512", "--memory", SANDBOX_MEMORY, "--cpus", SANDBOX_CPUS,   # a runaway script can't take the machine down
                       "-v", SHARED_DIR + ":/workspace:Z,noexec", # the ONLY path from your machine. noexec = files there can't be run
                       "-w", "/workspace", image(name), "sleep", "infinity")   # sleep forever = stay up, waiting for exec
    if code != 0:
        return "could not start: " + out
    sealed = set_network(False)
    return "running " + name + (", network off" if sealed else ", network could NOT be sealed, careful") + ", shared folder Shared/"

def stop():
    name = running()
    if not name:
        return "no sandbox is running"
    podman("stop", "-t", "2", container(name))                    # the container is deleted by itself (--rm). unsaved changes are gone
    return "stopped " + name

def save():
    name = running()
    if not name:
        return "no sandbox is running"
    code, out = podman("commit", "-q", container(name), image(name))   # the running state becomes the sandbox's new image
    return "saved " + name + ": the next start begins from this state" if code == 0 else "save failed: " + out

def remove(name):
    if name == running():
        return "stop it first"
    if name not in names():
        return "no sandbox called '" + name + "'"
    podman("rmi", "-f", image(name))
    shutil.rmtree(os.path.join(SANDBOXES_DIR, name))              # the folder and everything in it
    return "removed " + name

def reset(name):
    if name == running():
        return "stop it first"
    if name not in names():
        return "no sandbox called '" + name + "'"
    podman("rmi", "-f", image(name))                              # throw the saved state away...
    return "reset " + name + ": brand new" if build(name) else "reset failed"   # ...and build it again from the Containerfile

def set_network(on):
    """internet for the running sandbox, switched live. returns True if the state is now as asked"""
    name = running()
    if not name:
        return False
    code, networks = podman("inspect", "-f", "{{json .NetworkSettings.Networks}}", container(name))
    if on and '"podman"' not in networks:
        podman("network", "connect", "podman", container(name))
    if not on and '"podman"' in networks:
        podman("network", "disconnect", "podman", container(name))
    code, networks = podman("inspect", "-f", "{{json .NetworkSettings.Networks}}", container(name))   # verify, don't assume
    return ('"podman"' in networks) if on else (networks in ("{}", "null", ""))


# --- the status: what exists, what runs, network on or off. for /sandbox check and the check_sandbox tool ---
def base_of(name):
    """the image a sandbox is made from: the FROM line of its Containerfile"""
    for line in read_text(os.path.join(SANDBOXES_DIR, name, "Containerfile")).splitlines():
        if line.strip().upper().startswith("FROM "):
            return line.strip()[5:].strip()
    return "?"

def built_at(name):
    """when its image was built or last saved (e.g. 2026-10-11 18:12:03), or None if there is no image yet"""
    code, out = podman("image", "inspect", "-f", "{{.Created}}", image(name))
    return out[:19] if code == 0 and out else None                # "2026-10-11 18:12:03.123 +0200 CEST" -> the first 19 characters

def running_info(name):
    """for the running sandbox: since when it runs, and whether its network is on"""
    code, since = podman("inspect", "-f", "{{.State.StartedAt}}", container(name))
    code, networks = podman("inspect", "-f", "{{json .NetworkSettings.Networks}}", container(name))
    network = "on" if '"podman"' in networks else "off"           # the same check set_network uses
    return "running since " + since[:19] + ", network " + network

def status(name=None):
    """the state of one sandbox, or (no name) an overview of all of them. plain text, for you and for the agent"""
    if not available():
        return NOT_AVAILABLE
    now = running()
    if name:                                                      # one sandbox, in detail
        if name not in names():
            return "no sandbox called '" + name + "'. sandboxes: " + (", ".join(names()) or "none")
        built = built_at(name)
        lines = ["sandbox: " + name + " (made from " + base_of(name) + ")",
                 "image: " + ("built or saved " + built if built else "not built yet, it is built on the first start")]
        if name == now:
            lines.append("state: " + running_info(name))
            lines.append("limits: " + SANDBOX_MEMORY + " memory, " + SANDBOX_CPUS + " cpus, " + str(MAX_TOOL_TIMEOUT) + " s per command")
            lines.append("shared folder: Shared/ (inside: /workspace). sandbox_shell works")
        elif now:
            lines.append("state: stopped. another sandbox runs: " + now + " (only one can run at a time)")
        else:
            lines.append("state: stopped. no sandbox runs, sandbox_shell does not work until one is opened")
        return "\n".join(lines)

    if not names():                                               # the overview
        return "no sandboxes yet. the user can create one with /sandbox new <name>"
    lines = ["running: " + (now + " (" + running_info(now) + ")" if now else "none")]
    for each in names():
        built = built_at(each)
        lines.append("- " + each + ": " + ("running" if each == now else "stopped") + ", "
                     + ("image from " + built if built else "not built yet") + ", made from " + base_of(each))
    return "\n".join(lines)


# --- using the running sandbox ---
def exec(command, timeout=MAX_TOOL_TIMEOUT):
    """run a shell command inside the running sandbox and return what it printed. this is the agent's only way in"""
    name = running()
    if not name:
        return "no sandbox is running. open one with the open_sandbox tool, or ask the user to run /sandbox run <name>"
    try:
        code, out = podman("exec", "-w", "/workspace", container(name),
                           "timeout", "-k", "5", str(timeout), "bash", "-c", command, timeout=timeout + 10)   # timeout inside AND outside the container. -k 5 = hard kill 5 s after the polite stop
    except subprocess.TimeoutExpired:
        return "error: no result after " + str(timeout) + " seconds, command stopped"
    if code == 124:
        return out + "\nerror: stopped after " + str(timeout) + " seconds"
    if code != 0:
        return out + "\n(exit code " + str(code) + ")"
    return out or "(no output)"

def shell():
    name = running()
    if not name:
        return "no sandbox is running"
    print("[sandbox] you are root inside " + name + ". type exit to come back to the chat.")
    try:
        subprocess.run([CONTAINER_CMD, "exec", "-it", "-w", "/workspace", container(name), "bash"])
    except FileNotFoundError:
        return CONTAINER_CMD + " not found"
    return "back in the chat"


# --- asking you ---
def choose():
    """print the sandboxes and let you pick one. returns the name, or None"""
    if not names():
        print("no sandboxes yet. create one with /sandbox new <name>")
        return None
    print("which sandbox? " + ", ".join(names()))
    answer = input("sandbox> ").strip()
    if answer in names():
        return answer
    print("no sandbox called '" + answer + "'")
    return None

def stop_with_question():
    """stop the running sandbox, but first ask you whether to save it"""
    name = running()
    if not name:
        return
    if input("save " + name + " before stopping it? (y/n) ").strip().lower() == "y":
        print(save())
    print(stop())

def cleanup():
    """at startup: a sandbox left running by a crash or a hard kill is stopped, so we start clean"""
    code, out = podman("ps", "-a", "--filter", "name=^sandbox-", "--format", "{{.Names}}")
    for leftover in out.splitlines():
        podman("rm", "-f", leftover)

def shutdown(ask):
    """at exit: stop a running sandbox. ask = whether you can still be asked about saving (not after a hard crash)"""
    if not running():
        return
    if ask:
        try:
            stop_with_question()
            return
        except (KeyboardInterrupt, EOFError):                     # a second ctrl+c while asking: just stop
            print()
    print(stop())


# --- the agent's two tools (no saving: only you can save) ---
def open_for_agent():
    if not available():
        return NOT_AVAILABLE + ". tell the user"
    if running():
        return "a sandbox is already running: " + running()
    print("\n[the agent wants a sandbox]")
    name = choose()
    if not name:
        return "the user did not choose a sandbox"
    return run(name)

def close_for_agent():
    return stop()                                                 # unsaved changes are gone; that's the rule


# --- your /sandbox commands ---
HELP = """/sandbox list                 all sandboxes, which one runs, which have an image
/sandbox check [name]         the state of one sandbox (running? network? image?), or of all without a name
/sandbox new <name> [image]   create one (default: plain ubuntu). the image is built right away
/sandbox run [name]           start one clean from its image (a running one is stopped first, you are asked about saving)
/sandbox stop                 stop the running one (you are asked about saving). unsaved changes are gone
/sandbox save                 make the running state the sandbox's new image
/sandbox remove <name>        delete a sandbox: its folder and its image
/sandbox reset <name>         forget the saved state, rebuild it brand new from its Containerfile
/sandbox net on|off           internet for the running sandbox (default off)
/sandbox shell                a root shell inside the running one, for you. type exit to come back"""

SUBCOMMANDS = ["list", "check", "new","run", "stop", "save", "remove", "reset", "net", "shell"]

def command(words):
    """words = what you typed after /sandbox, split into a list"""
    what = words[0] if words else "help"                          # a bare /sandbox shows the subcommands
    if what in SUBCOMMANDS and not available():                   # a real subcommand, but no podman: say so once, instead of failing in pieces
        print(NOT_AVAILABLE)
    elif what == "list":
        for name in names():
            marks = " (running)" if name == running() else ("" if has_image(name) else " (not built yet)")
            print("  " + name + marks)
        if not names():
            print("  none. /sandbox new <name> creates one")
    elif what == "check" and len(words) <= 2:
        print(status(words[1] if len(words) == 2 else None))
    elif what == "new" and len(words) in (2, 3):
        print(new(words[1]) if len(words) == 2 else new(words[1], words[2]))
    elif what == "run" and len(words) <= 2:
        name = words[1] if len(words) == 2 else choose()
        if name:
            stop_with_question()
            print(run(name))
    elif what == "stop":
        stop_with_question()
    elif what == "save":
        print(save())
    elif what == "remove" and len(words) == 2:
        print(remove(words[1]))
    elif what == "reset" and len(words) == 2:
        print(reset(words[1]))
    elif what == "net" and len(words) == 2 and words[1] in ("on", "off"):
        ok = set_network(words[1] == "on")
        print("network " + words[1] if ok else "could not switch the network (is a sandbox running?)")
    elif what == "shell":
        print(shell())
    else:
        print(HELP)