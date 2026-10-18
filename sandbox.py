# sandbox.py — the sandboxes: throwaway Linux containers where the agent may run anything.
# how it works: each folder in Sandboxes/ is one sandbox, and its Containerfile is the whole truth about it. building it
# gives an IMAGE. running it starts a CONTAINER (a throwaway copy of the image) that is deleted when it stops.
# nothing is ever saved: the image is built from the Containerfile again at every start. unchanged steps come from podman's
# cache, so that takes a second or two, and a change you make in a Containerfile is in the very next start.
# every running main.py (an "instance") has at most one container, and the agent opens and closes it itself. several
# instances may run at the same time, each with its own container: of the same sandbox or of different ones.
# what a container sees of your machine, all of it in Shared/:
#   Shared/common/            -> /workspace/common              always, in every container of every instance: the shared desk
#   Shared/<project>/         -> /workspace/<project>           one project at most, mounted by the agent. one container at a time
#   Shared/Notebooks_Engine/  -> /workspace/Notebooks_Engine    the notebook engine, read-only: it can't be changed from inside
# all mounted noexec: files there can't be run directly, only through an interpreter (python x.py, bash x.sh).
# podman can't add or remove a folder of a running container, so mounting or unmounting a project restarts the container.
# every container carries labels: who started it (owner), which sandbox, which project. that is how an instance finds its
# own container, never by the name alone, so containers you start yourself are never touched.
# everything in here is podman commands; `podman(...)` below runs one and returns what it printed.

import os
import re
import json
import shutil
import threading
import subprocess
from config import *


NOT_FOUND = 127                                                   # the exit code shells use for "no such command"
COMMON = "common"                                                 # the folder in Shared/ every container sees
ENGINE = "Notebooks_Engine"                                       # the folder in Shared/ with the notebook engine (kernel.py, client.py)
INSTANCE = str(os.getpid())                                       # this running main.py: its process number
PROJECT_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"                      # what a project folder must be called to be mounted

# this instance's container. changed only by start() and forget()
my_container = None                                               # e.g. "sandbox-python-48213-1". None = none runs here
my_sandbox = None                                                 # e.g. "python"
my_project = None                                                 # the mounted project, e.g. "website". None = none
starts = 0                                                        # containers this instance started so far, for their names
lock = threading.Lock()                                           # parallel tool calls: one opens, closes or mounts at a time


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
    """the sandboxes: every folder in Sandboxes/ with a Containerfile inside"""
    found = []
    if os.path.isdir(SANDBOXES_DIR):
        for name in sorted(os.listdir(SANDBOXES_DIR)):
            if os.path.isfile(os.path.join(SANDBOXES_DIR, name, "Containerfile")):   # a stray file (.DS_Store) is no sandbox
                found.append(name)
    return found

def image(name):
    return "localhost/sandbox-" + name

def has_image(name):
    return podman("image", "exists", image(name))[0] == 0

def containerfile(name):
    return read_text(os.path.join(SANDBOXES_DIR, name, "Containerfile"))

def engine_dir():
    """the notebook engine's folder on your machine"""
    return os.path.normpath(os.path.join(SHARED_DIR, ENGINE))    # normpath: the right slashes on windows too

def reserved(name):
    """common and Notebooks_Engine are no projects: no project tool touches them (in any spelling: Common = common on mac)"""
    return name.lower() in (COMMON.lower(), ENGINE.lower())

def workdir():
    """the working folder inside this instance's container: the project if one is mounted, otherwise common"""
    if my_project:
        return "/workspace/" + my_project
    return "/workspace/" + COMMON


# --- every container of every instance: found by their labels, asked from podman every time ---
def containers():
    """all containers this program started, in any instance, running or not. a list of
    {"name", "owner", "sandbox", "project", "shared"}"""
    code, out = podman("ps", "-a", "--filter", "label=harness.owner", "--format", "json")
    if code != 0 or not out:
        return []
    try:
        listed = json.loads(out)
    except ValueError:                                            # not json: podman printed an error instead
        return []
    found = []
    for c in listed:
        labels = c.get("Labels") or {}                            # "or {}": podman writes null when there are none
        names_of_it = c.get("Names") or [""]
        found.append({"name": names_of_it[0],
                      "owner": labels.get("harness.owner", ""),   # the process number of the main.py that started it
                      "sandbox": labels.get("harness.sandbox", ""),
                      "project": labels.get("harness.project", ""),   # "" = no project mounted
                      "shared": labels.get("harness.shared", "")})    # which Shared/ folder (two copies of this program
    return found                                                  # on one machine have two)

def alive(owner):
    """is the main.py with this process number still running? asked from the operating system"""
    if owner == INSTANCE:
        return True
    if not owner.isdigit():
        return False
    if os.name == "nt":                                           # windows: os.kill would END the process, so ask tasklist
        try:
            done = subprocess.run(["tasklist", "/FI", "PID eq " + owner, "/NH"], capture_output=True, text=True)
        except OSError:
            return True                                           # can't tell: count it as alive, so nothing is removed
        return (" " + owner + " ") in done.stdout
    try:
        os.kill(int(owner), 0)                                    # signal 0 = "are you there?", it does nothing to the process
    except ProcessLookupError:
        return False
    except PermissionError:                                       # it exists, it just belongs to another user
        return True
    return True

def cleanup():
    """remove leftover containers: the ones of instances that are gone (a crash, a closed terminal), so they don't hold
    their project forever, and old ones of this instance. containers of instances that still run are never touched"""
    for c in containers():
        old_one_of_mine = c["owner"] == INSTANCE and c["name"] != my_container   # e.g. from a crashed main.py that
        if old_one_of_mine or not alive(c["owner"]):                            # had the same process number before
            podman("rm", "-f", c["name"])


# --- the network: off at every start, only you can switch it on ---
def network_on():
    code, networks = podman("inspect", "-f", "{{json .NetworkSettings.Networks}}", my_container)
    return code == 0 and '"podman"' in networks

def set_network(on):
    """internet for this instance's container, switched live. returns True if the state is now as asked"""
    if not my_container:
        return False
    if on and not network_on():
        podman("network", "connect", "podman", my_container)
    if not on and network_on():
        podman("network", "disconnect", "podman", my_container)
    return network_on() == on                                     # verify, don't assume


# --- starting and stopping this instance's container ---
def build(name):
    """build the image from the Containerfile. returns None if it worked, otherwise the end of the build log"""
    print("[sandbox] building " + name + " from Sandboxes/" + name + "/Containerfile (quick if nothing changed) ...")
    code, out = podman("build", "-t", image(name), os.path.join(SANDBOXES_DIR, name))
    if code != 0:
        return "the build of " + name + " failed. the end of its log:\n" + out[-2000:]
    return None

def start(name, project, network):
    """start a new container of this sandbox for this instance, with common, the engine and (if given) the project.
    network: switch it on right away (after a restart, when it was on before). returns None if it runs, otherwise why not"""
    global my_container, my_sandbox, my_project, starts
    cleanup()
    problem = build(name)
    if problem:
        return problem
    os.makedirs(os.path.join(SHARED_DIR, COMMON), exist_ok=True)
    starts += 1
    container = "sandbox-" + name + "-" + INSTANCE + "-" + str(starts)   # unique: never clashes with another instance,
                                                                         # or with our last one that is still being removed
    args = ["run", "-d", "--rm", "--name", container,             # --rm = deleted when it stops: every start is clean
            "--label", "harness.owner=" + INSTANCE,               # who started it: how every instance finds its own
            "--label", "harness.sandbox=" + name,
            "--label", "harness.shared=" + SHARED_DIR,
            "--network", "podman",                                # on the named network at birth, sealed right below
            "--security-opt", "no-new-privileges",                # no way to gain more rights than it starts with
            "--init",                                             # a tiny first process that cleans up finished background
                                                                  # programs (e.g. a stopped notebook kernel) so none pile up
            "--pids-limit", "512", "--memory", SANDBOX_MEMORY, "--cpus", SANDBOX_CPUS,   # a runaway script can't take the machine down
            "-v", os.path.join(SHARED_DIR, COMMON) + ":/workspace/" + COMMON + ":z,noexec"]   # z = other containers may use it too
    if os.path.isdir(engine_dir()):                               # missing? the sandbox still starts, only notebooks won't work
        args = args + ["-v", engine_dir() + ":/workspace/" + ENGINE + ":z,ro,noexec"]   # ro = read-only: the agent can't change it
    if project:
        args = args + ["--label", "harness.project=" + project,  # the lock: no other instance mounts it while this runs
                       "-v", os.path.join(SHARED_DIR, project) + ":/workspace/" + project + ":Z,noexec"]   # Z = only this container
    args = args + ["-w", "/workspace/" + (project or COMMON), image(name), "sleep", "infinity"]   # sleep forever = stay up, waiting for exec
    code, out = podman(*args)
    if code != 0:
        return "could not start " + name + ": " + out
    my_container = container
    my_sandbox = name
    my_project = project
    set_network(network)                                          # off, or on again after a restart. the callers say which it is
    return None

def forget():
    """this instance has no container anymore"""
    global my_container, my_sandbox, my_project
    my_container = None
    my_sandbox = None
    my_project = None

def stop():
    podman("stop", "-t", "2", my_container)                       # the container is deleted by itself (--rm)
    forget()

def running_here():
    """the sandbox running in this instance, or None. asked from podman, so a container that died meanwhile is noticed"""
    if not my_container:
        return None
    code, out = podman("container", "inspect", "-f", "{{.State.Running}}", my_container)
    if code == 0 and out == "true":
        return my_sandbox
    forget()                                                      # gone (out of memory, removed by hand): it holds nothing anymore
    return None

def restart(project):
    """podman can't add or remove a folder of a running container: so stop it and start a new one with the new folders.
    the network stays as it was"""
    name = my_sandbox
    network = network_on()
    stop()
    problem = start(name, project, network)
    if problem:
        return "the sandbox was stopped, but could not start again: " + problem
    return ("restarted " + name + " with the new folders: whatever was installed or started inside since its start is gone, "
            "open notebooks are closed (nb_open them again), network " + ("on" if network_on() else "off") + ". " + where())

def where():
    """what this instance's container sees, for the agent"""
    text = "/workspace/common = Shared/common, shared with every other instance"
    if my_project:
        text += "; /workspace/" + my_project + " = Shared/" + my_project + ", your project, no other instance can mount it now"
    else:
        text += "; no project mounted"
    return text + ". working folder: " + workdir() + ". everything outside these folders is gone when the sandbox stops"


# --- projects: the folders directly in Shared/, except common and Notebooks_Engine ---
def projects():
    found = []
    if os.path.isdir(SHARED_DIR):
        for name in sorted(os.listdir(SHARED_DIR)):
            if not reserved(name) and not name.startswith(".") and os.path.isdir(os.path.join(SHARED_DIR, name)):
                found.append(name)
    return found

def holder(project):
    """who has this project mounted right now: "you", "another instance", or None = it is free"""
    cleanup()                                                     # a crashed instance's container must not hold it forever
    for c in containers():
        if c["project"] == project and c["shared"] == SHARED_DIR:
            if c["name"] == my_container:
                return "you"
            return "another instance"
    return None

def name_problem(name):
    """None if this is a good name for a project folder, otherwise why not"""
    if name.lower() == COMMON.lower():
        return "common is not a project: it is always mounted in every sandbox, at /workspace/common, and no tool changes it"
    if name.lower() == ENGINE.lower():
        return "Notebooks_Engine is not a project: it holds the notebook engine, and no tool changes it"
    if not re.fullmatch(PROJECT_NAME, name) or len(name) > 60:
        return "invalid project name: letters, digits, - _ . only, at most 60 characters, e.g. sales-2026"
    return None

def spelled(name):
    """the existing project with this name in another spelling (Web for web), or None. on windows and mac those are
    the same folder, so every tool uses the one spelling the folder really has"""
    for existing in projects():
        if existing.lower() == name.lower() and existing != name:
            return existing
    return None

def check_project(project):
    """None if this instance may mount the project, otherwise why not"""
    problem = name_problem(project)
    if problem:
        return problem
    if spelled(project):
        return "that project is called '" + spelled(project) + "': use that spelling"
    if project not in projects():
        return ("no project called '" + project + "'. projects: " + (", ".join(projects()) or "none")
                + ". create_project makes a new one")
    if holder(project) == "another instance":
        return (project + " is mounted by another instance right now, and only one sandbox at a time may have a project. "
                "pick another one, or try again later")
    return None

def projects_status():
    """the projects, and who has which one mounted. for the check_projects tool"""
    if not available():
        return NOT_AVAILABLE
    here = running_here()
    cleanup()
    taken = {}                                                    # project -> the name of the container that has it
    for c in containers():
        if c["project"] and c["shared"] == SHARED_DIR:
            taken[c["project"]] = c["name"]
    lines = ["projects are the folders directly in the user's Shared/ folder. a sandbox mounts one at a time, at "
             "/workspace/<project>, and while it does, no other instance can mount it.",
             "common (Shared/common) is not a project: it is always mounted in every sandbox of every instance, at "
             "/workspace/common, to share files between them. it can't be unmounted.",
             "Notebooks_Engine (Shared/Notebooks_Engine) is not a project either: it holds the notebook engine, mounted read-only."]
    if not here:
        lines.append("this instance: no sandbox runs. open_sandbox starts one, and can mount a project right away")
    elif my_project:
        lines.append("this instance: sandbox " + here + ", project " + my_project + " mounted at /workspace/" + my_project
                     + " (the working folder)")
    else:
        lines.append("this instance: sandbox " + here + ", no project mounted (working folder /workspace/common)")
    if not projects():
        lines.append("projects: none yet. create_project makes one")
        return "\n".join(lines)
    lines.append("projects:")
    for name in projects():
        if not re.fullmatch(PROJECT_NAME, name):
            state = "can't be mounted, its name has other characters than letters, digits, - _ . (the user can rename it)"
        elif name not in taken:
            state = "free"
        elif taken[name] == my_container:
            state = "mounted by you"
        else:
            state = "mounted by another instance, not available now"
        lines.append("- " + name + ": " + state)
    return "\n".join(lines)


# --- the status: what exists, what runs where. for /sandbox check and the check_sandbox tool ---
def built_at(name):
    """when its image was last built (e.g. 2026-10-11 18:12:03), or None if there is none yet"""
    code, out = podman("image", "inspect", "-f", "{{.Created}}", image(name))
    return out[:19] if code == 0 and out else None                # "2026-10-11 18:12:03.123 +0200 CEST" -> the first 19 characters

def running_info():
    """for this instance's container: since when it runs, its network, its project"""
    code, since = podman("inspect", "-f", "{{.State.StartedAt}}", my_container)
    text = "running in this instance since " + since[:19] + ", network " + ("on" if network_on() else "off")
    if my_project:
        return text + ", project " + my_project + " mounted"
    return text + ", no project mounted"

def others_running(name):
    """how many other instances run this sandbox right now, each in its own container"""
    count = 0
    for c in containers():
        if c["sandbox"] == name and c["owner"] != INSTANCE:
            count += 1
    return count

def status(name=None):
    """one sandbox, or (no name) all of them: each with its whole Containerfile, so you see what is in it. plain text"""
    if not available():
        return NOT_AVAILABLE
    if name and name not in names():
        return "no sandbox called '" + name + "'. sandboxes: " + (", ".join(names()) or "none")
    if not names():
        return "no sandboxes yet. the user makes one: a folder in Sandboxes/ with a Containerfile inside"
    here = running_here()
    cleanup()
    lines = []
    if name:
        chosen = [name]
    else:
        chosen = names()
        lines.append("running in this instance: " + (here + " (" + running_info() + ")" if here else "none")
                     + ". one sandbox per instance.")
        lines.append("every start builds the image from its Containerfile again, so a Containerfile below is exactly what "
                     "you get. nothing installed at runtime is kept.")
    for each in chosen:
        lines.append("")
        lines.append("=== sandbox: " + each + " ===")
        built = built_at(each)
        lines.append("image: " + ("built " + built if built else "not built yet, it is built at the first start (can take a while)"))
        if each == here:
            lines.append("state: " + running_info())
        elif here:
            lines.append("state: not running in this instance (" + here + " runs here)")
        else:
            lines.append("state: not running in this instance")
        others = others_running(each)
        if others:
            lines.append("also running in " + str(others) + " other instance(s), each in its own container")
        lines.append("Containerfile:")
        lines.append(containerfile(each) or "(empty)")
    return "\n".join(lines).strip()


# --- using this instance's container ---
def exec(command, timeout=MAX_TOOL_TIMEOUT):
    """run a shell command inside this instance's container and return what it printed. this is the agent's only way in"""
    if not running_here():
        return "no sandbox runs in this instance. start one with open_sandbox (check_sandbox shows which ones there are)"
    try:
        code, out = podman("exec", "-w", workdir(), my_container,
                           "timeout", "-k", "5", str(timeout), "bash", "-c", command, timeout=timeout + 10)   # timeout inside AND outside the container. -k 5 = hard kill 5 s after the polite stop
    except subprocess.TimeoutExpired:
        return "error: no result after " + str(timeout) + " seconds, command stopped"
    if code == 124:
        return out + "\nerror: stopped after " + str(timeout) + " seconds"
    if code != 0:
        return out + "\n(exit code " + str(code) + ")"
    return out or "(no output)"

def shell():
    if not running_here():
        return "no sandbox runs in this instance"
    print("[sandbox] you are root inside " + my_sandbox + ". type exit to come back to the chat.")
    try:
        subprocess.run([CONTAINER_CMD, "exec", "-it", "-w", workdir(), my_container, "bash"])
    except FileNotFoundError:
        return CONTAINER_CMD + " not found"
    return "back in the chat"

def shutdown():
    """at exit: stop this instance's container. its project is free again. nothing to save, nothing to ask"""
    if my_container:
        print("[sandbox] stopping " + my_sandbox)
        stop()


# --- the agent's tools ---
def open_sandbox(name, project=None):
    """start this sandbox for this instance (one at most), optionally with a project mounted. the agent chooses"""
    with lock:
        if not available():
            return NOT_AVAILABLE + ". tell the user"
        here = running_here()
        if here:
            return ("a sandbox already runs in this instance: " + here + ". only one per instance: close_sandbox first "
                    "if you need another one")
        if name not in names():
            return ("no sandbox called '" + name + "'. sandboxes: " + (", ".join(names()) or "none")
                    + " (check_sandbox shows what is in them)")
        if project:
            problem = check_project(project)
            if problem:
                return problem
        problem = start(name, project, False)
        if problem:
            return problem
        if network_on():
            network = "network could NOT be sealed, careful"
        else:
            network = "network off"
        return "running " + name + ", " + network + ". " + where()

def close_sandbox():
    with lock:
        here = running_here()
        if not here:
            return "no sandbox runs in this instance"
        project = my_project
        stop()
        answer = "stopped " + here + ". whatever was installed or started inside is gone; the files in the mounted folders stay"
        if project:
            answer += ". " + project + " is free for other instances again"
        return answer

def mount_project(project):
    """mount a project for this instance (at most one: another one replaces it). restarts the container"""
    with lock:
        if not running_here():
            return "no sandbox runs in this instance. open_sandbox first (it can mount the project right away)"
        if project == my_project:
            return project + " is mounted already, at /workspace/" + project
        problem = check_project(project)
        if problem:
            return problem
        old = my_project
        answer = restart(project)
        if old:
            answer = "unmounted " + old + " (free for other instances again). " + answer
        return answer

def unmount_project():
    with lock:
        if not running_here():
            return "no sandbox runs in this instance"
        if not my_project:
            return "no project is mounted. (common is always mounted and can't be unmounted)"
        old = my_project
        return "unmounted " + old + ", it is free for other instances again. " + restart(None)

def create_project(name):
    """a new, empty project folder in Shared/"""
    with lock:
        problem = name_problem(name)
        if problem:
            return problem
        if name in projects() or spelled(name):
            return "a project called '" + (spelled(name) or name) + "' exists already"
        if os.path.exists(os.path.join(SHARED_DIR, name)):         # a file with that name, not a folder
            return "there is a file called '" + name + "' in Shared/ already: pick another name"
        os.makedirs(os.path.join(SHARED_DIR, name))
        return "created project " + name + " (Shared/" + name + "). mount_project mounts it"

def delete_project(name):
    """delete a project folder in Shared/ with everything in it. not common, not Notebooks_Engine, not while mounted"""
    with lock:
        if reserved(name):
            return name_problem(name)
        if spelled(name):
            return "that project is called '" + spelled(name) + "': use that spelling"
        if name not in projects():
            return "no project called '" + name + "'. projects: " + (", ".join(projects()) or "none")
        path = os.path.join(SHARED_DIR, name)
        if os.path.islink(path):                                  # a link to a folder somewhere else: never delete through it
            return name + " is a link to another folder, not a folder in Shared/: the user has to remove it"
        who = holder(name)
        if who == "you":
            return name + " is mounted in your sandbox: unmount_project first, then delete it"
        if who:
            return name + " is mounted by another instance right now: it can only be deleted when no sandbox has it mounted"
        shutil.rmtree(path)                                       # the folder and everything in it. there is no undo
        return "deleted project " + name + " and everything in it"

def rename_project(old, new):
    """rename a project folder in Shared/. not common, not Notebooks_Engine, and not while a sandbox has it mounted"""
    with lock:
        if reserved(old):
            return name_problem(old)
        if old not in projects():
            return "no project called '" + old + "'. projects: " + (", ".join(projects()) or "none")
        problem = name_problem(new)
        if problem:
            return problem
        for existing in projects():
            if existing.lower() == new.lower() and existing != old:   # only a new spelling of the same name is fine (web -> Web)
                return "a project called '" + existing + "' exists already"
        who = holder(old)
        if who == "you":
            return old + " is mounted in your sandbox: unmount_project first, then rename it"
        if who:
            return old + " is mounted by another instance right now: it can only be renamed when no sandbox has it mounted"
        os.rename(os.path.join(SHARED_DIR, old), os.path.join(SHARED_DIR, new))
        return "renamed project " + old + " -> " + new + " (Shared/" + new + ")"


# --- your /sandbox commands. opening and closing is the agent's job, and every exit closes too ---
def users(name):
    """how many containers of this sandbox exist right now, in any instance (leftovers of crashed ones are removed first)"""
    cleanup()
    count = 0
    for c in containers():
        if c["sandbox"] == name:
            count += 1
    return count

INVALID_NAME = "invalid name: lowercase letters, digits and hyphens only, e.g. my-box-2"

def valid_name(name):
    """what podman accepts in an image name: lowercase letters and digits, hyphens only in between"""
    return re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) is not None

def remove(name):
    if name not in names():
        return "no sandbox called '" + name + "'"
    if users(name):
        return name + " runs right now (here or in another instance). it can only be removed when no instance runs it"
    if has_image(name):
        code, out = podman("rmi", image(name))                    # no -f: that would also remove containers using it
        if code != 0:
            return "could not remove its image: " + out
    shutil.rmtree(os.path.join(SANDBOXES_DIR, name))              # the folder and everything in it
    return "removed " + name + ": its folder and its image"

def rename(name, new_name):
    if name not in names():
        return "no sandbox called '" + name + "'"
    if not valid_name(new_name):
        return INVALID_NAME
    if new_name in names():
        return "'" + new_name + "' exists already"
    if users(name):
        return name + " runs right now (here or in another instance). it can only be renamed when no instance runs it"
    if has_image(name):                                           # the image moves along: new name on first, then the old name off
        code, out = podman("tag", image(name), image(new_name))
        if code != 0:
            return "rename failed: " + out
        podman("untag", image(new_name), image(name))             # removes only the old name. the image stays, under its new name
    os.rename(os.path.join(SANDBOXES_DIR, name), os.path.join(SANDBOXES_DIR, new_name))
    return "renamed " + name + " -> " + new_name

HELP = """/sandbox list                 all sandboxes: which one runs here, which run in other instances, which are built
/sandbox check [name]         one sandbox in detail with its whole Containerfile, or all of them without a name
/sandbox remove <name>        delete a sandbox: its folder and its image (only when no instance runs it)
/sandbox rename <old> <new>   rename a sandbox, its image included (only when no instance runs it)
/sandbox net on|off           internet for this instance's sandbox (off at every start)
/sandbox shell                a root shell inside this instance's sandbox, for you. type exit to come back
the agent opens and closes its sandbox itself. a new sandbox: a folder in Sandboxes/ with a Containerfile inside"""

SUBCOMMANDS = ["list", "check", "remove", "rename", "net", "shell"]

def command(words):
    """words = what you typed after /sandbox, split into a list"""
    what = words[0] if words else "help"                          # a bare /sandbox shows the subcommands
    if what in SUBCOMMANDS and not available():                   # a real subcommand, but no podman: say so once, instead of failing in pieces
        print(NOT_AVAILABLE)
    elif what == "list":
        here = running_here()
        cleanup()                                                 # leftovers of crashed instances don't count as running
        for name in names():
            marks = ""
            if name == here:
                marks += " (running here)"
            others = others_running(name)
            if others:
                marks += " (running in " + str(others) + " other instance(s))"
            if not has_image(name):
                marks += " (not built yet)"
            print("  " + name + marks)
        if not names():
            print("  none. a new sandbox: a folder in Sandboxes/ with a Containerfile inside")
    elif what == "check" and len(words) <= 2:
        print(status(words[1] if len(words) == 2 else None))
    elif what == "remove" and len(words) == 2:
        print(remove(words[1]))
    elif what == "rename" and len(words) == 3:
        print(rename(words[1], words[2]))
    elif what == "net" and len(words) == 2 and words[1] in ("on", "off"):
        if not running_here():
            print("no sandbox runs in this instance")
        elif set_network(words[1] == "on"):
            print("network " + words[1])
        else:
            print("could not switch the network")
    elif what == "shell":
        print(shell())
    else:
        print(HELP)
