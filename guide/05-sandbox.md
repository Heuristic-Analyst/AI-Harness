# 05 — sandbox.py: the containers your code runs in

**In this chapter:** (each section then goes function by function, or tool by tool)
- 1. The big idea in plain words
- 2. The mental model of one running instance
- 3. Every function, in file order
- 4. The mounts: exactly what the container sees of the machine
- 5. The actual Podman command lines
- 6. What the user and the model actually see
- What this chapter hands to the rest of the guide

---

`sandbox.py` (616 lines) is the only file that touches the outside world: it builds images, starts containers, runs
commands inside them, cleans up after them. Everything else (`tools/sandbox/*.py`, `tools/notebook/*.py`,
`tools/results/copy_result.py`) only calls a function here and gets text back. This chapter covers the file
completely: what a sandbox is, the mental model of one running instance, every function in file order, the mounts, the
exact Podman command lines, and what the model actually sees.
## 1. The big idea in plain words

**Model-written code must not run on the user's machine.** The agent's main verb is "run this bash command", and a
model that is 99% right is still wrong 1% of the time — `rm -rf ~`, a loop that fills the disk, `cat ~/.ssh/id_rsa`.
Handing that the user's home folder is not a risk worth taking, and approving every command by hand makes the agent
useless. So the harness does the third thing: it hands the command to a separate operating-system world whose only
reachable files are a few folders the user chose, and where nothing survives afterwards.

**What a container is.** An ordinary process (a small tree of them) that the OS has been told to lie to: its own view
of the filesystem (its "root" is not the machine's root), its own process numbers (inside, the first process is pid
1), its own network address. The lies are kernel features (namespaces, cgroups, security flags), so software inside
believes it is alone on a small Linux machine while outside it is one more process owned by the user. No emulation, no
second OS booting — it starts in a fraction of a second.

**Why Podman, and why rootless.** `config.py:47`: `CONTAINER_CMD = "podman"`, comment "podman is rootless: 'root'
inside is just you outside". Podman runs containers as the user who typed the command (user namespaces on Linux, a
small hidden VM on macOS/Windows), with no root daemon: the agent's "root" inside is a costume, and files it writes
into mounted folders belong to the user, who can still open and edit them.

**Throwaway.** The container starts with `--rm` (`sandbox.py:154`), so when it stops Podman deletes it and everything
that ever existed inside: installed packages, `/tmp`, background processes, notebook kernels, shell history. Only the
*image* (the built filesystem template) is kept, and it is rebuilt from the Containerfile at every start
(`sandbox.py:147`). The only things that persist are files in the mounted folders.

**A volume / bind mount** is the door through the lie: "this host folder also appears at this path inside the
container". Writes go straight to the real folder — no copy, no sync — so a file saved at `/workspace/common/x.py` is
really `Shared/common/x.py` at that instant. Doors are dangerous, so exactly three are opened, all inside `Shared/`
(`sandbox.py:163-168`), and all marked `noexec`: a file there cannot be run as a program, only through an interpreter
(`python x.py`, `bash x.sh`). **Why only `Shared/`:** the user's life is in their home folder and `Shared/` is the one
folder they made for this program — the difference between "the agent can lose a project" and "lose everything".

**Why the network is off by default.** A network is a way out (send the user's data) and a way in (fetch code and run
it). Few tasks need it, and the user can grant it for the running container with `/sandbox net on`. So the container
is disconnected right after start (`sandbox.py:176`), and the agent's own `open_sandbox` never turns it on
(`sandbox.py:422`).

**Why memory/CPU/pid limits exist.** The likeliest disaster is a runaway script: memory until the machine swaps to
death, or forks until nothing else can start. `--memory 2g --cpus 2 --pids-limit 512` (`sandbox.py:162`; values from
`config.py:48-49`) make the sandbox suffer instead of the user's machine.

**The lifecycle has four stages (five verbs).** (1) **pick** — the agent reads the Containerfiles and chooses a name;
pure looking, `status()` / `check_sandbox` (`sandbox.py:336`). (2) **build + open** — `open_sandbox()` (`408`) calls
`start()` (`142`), which first calls `build()` (`134`) then `podman run -d`; build and open are one step for the
caller. (3) **use** — `exec()` (`375`), the agent's only way in, plus notebook kernels running inside. (4) **close** —
`close_sandbox()`/`stop()` (`433`, `187`), and `shutdown()` at process exit (`400`).

**Cached by hash or checksum? Not in this code.** `start()` calls `build()` unconditionally on every open
(`sandbox.py:147`), and `build()` always runs `podman build` (`136-137`). Change detection is Podman's own build
cache: Podman hashes the Containerfile and each instruction's inputs, reuses unchanged layers, re-runs only what
follows a change. The module header states the intent (`sandbox.py:4-6`: "unchanged steps come from podman's cache ...
a change you make in a Containerfile is in the very next start"). So "build on first open" means "rebuild on every
open, cheap after the first"; the only thing read back is the image's creation time, for display (`built_at`, `315`).
## 2. The mental model of one running instance

An **instance** is one running `main.py`, identified by `INSTANCE` (`config.py:71`) = `str(os.getpid()) + "-" +
datetime.now().strftime("%Y%m%d%H%M%S")`, e.g. `48213-20261018165603` — process number plus start time, unique for
good.

**One instance = at most one container.** Not a pool, not one per tool call. `open_sandbox` refuses a second one
(`sandbox.py:412-415`: "only one per instance: close_sandbox first"); `status` says it too (`356`: "one sandbox per
instance").

**How the container is named** (`sandbox.py:152`):

```python
container = "sandbox-" + name + "-" + INSTANCE + "-" + str(starts)
```

so a real name is `sandbox-python-48213-20261018165603-1`: literal `sandbox-`, the sandbox folder name, the instance
id, and a per-process counter `starts` (`37`) incremented on every attempt (`151`) so a new container never
collides with the previous one still being removed (comment at `152-153`). The *image* is named separately:
`localhost/sandbox-<name>` (`63`).

**Where the state lives: in memory, in five module globals, nowhere on disk** (`sandbox.py:34-38`):

```python
my_container = None      # e.g. "sandbox-python-48213-1". None = none runs here
my_sandbox = None        # e.g. "python"
my_project = None        # the mounted project, e.g. "website". None = none
starts = 0               # containers this instance started so far, for their names
lock = threading.Lock()  # parallel tool calls: one opens, closes or mounts at a time
```

No state file, no JSON, no database. `my_container` is written only by `start()` (`173-175`) and cleared only by
`forget()` (`179-185`) — what line 33's comment means. Cross-process truth travels in **labels on the container**
(`harness.owner`, `harness.sandbox`, `harness.project`, `harness.shared`; `155-157,167`), read back with `podman ps -a
--filter label=harness.owner --format json` (`89`). That is how one instance learns another has a project mounted, and
how a new instance finds a crashed one's leftovers.

**What happens to an open notebook when the sandbox closes.** A kernel is a Python process *inside* the container
(`tools/notebook/_notebook.py:2-5`: each tool call runs `client.py` in the sandbox, which talks to a long-running
`kernel.py`). Stop the container and every kernel dies; `--rm` deletes the corpse. The code does not merely hope so:
`forget()` calls `locks.release_all("notebook-")` (`sandbox.py:184`). `nb_open`'s description says it for the model:
"Needed after the sandbox restarted (also mount_project and unmount_project restart it), because that stops every
kernel" (`tools/notebook/nb_open.py:11`). Same cause behind `restart()`: Podman cannot add or remove a mount of a
*running* container, so changing mounts means a new container (`sandbox.py:201-211`) — hence the restart message "open
notebooks are closed (nb_open them again)" (`210`) and `open_sandbox`'s project argument.
## 3. Every function, in file order

### Group A — the plumbing (`sandbox.py:28-51`)

Constants quoted by most functions: `NOT_FOUND = 127` (`28`, a shell's "no such command", reused as "podman is not
here"), `COMMON = "common"` (`29`), `ENGINE = "Notebooks_Engine"` (`30`) — the two `Shared/` folders that are not
projects — `PROJECT_NAME` (`31`, a mountable project name), and the five state variables at `34-38` (section 2).
### podman(*args, timeout=None)

**Why it exists:** one place that runs Podman, so "missing", "printed to stderr" and "returned 125" are handled the
same everywhere.
**How it works, line by line:** `subprocess.run([CONTAINER_CMD] + list(args), capture_output=True, text=True,
timeout=timeout)` (`43`) passes a list, never a shell string, so nothing is word-split or needs quoting; `except
FileNotFoundError: return NOT_FOUND, CONTAINER_CMD + " not found"` (`44-45`) makes a missing binary an answer; `return
done.returncode, (done.stdout + done.stderr).strip()` (`46`) merges both streams and trims.
**Gotchas:** stdout and stderr become indistinguishable, so an error looks like ordinary output. No default timeout
(only `exec()` passes one), so a hung `podman build` hangs that tool call; an escaping `TimeoutExpired` becomes
`"error: ..."` via `agent.run_tool` (`agent.py:267-268`).
### available() (`sandbox.py:48`)

**Why it exists:** one cheap yes/no for "Podman installed *and* running" (on macOS/Windows it may exist with its VM
stopped).
**How it works:** `podman("info", "--format", "ok")[0] == 0` (`49`).
**Gotchas:** a subprocess, never cached; four callers.
### NOT_AVAILABLE (`sandbox.py:51`)

A message, not a function: "podman is not installed or not running, so there are no sandboxes right now", which the
tools return with ". tell the user" (`410`) so the model stops retrying.
### Group B — sandbox folders, image names, paths (`sandbox.py:53-84`)

### names()

**Why it exists:** the sandboxes *are* the folders the user made; `check_sandbox` lists them, `open_sandbox` validates
against them.
**How:** sorted `os.listdir(SANDBOXES_DIR)` (`57`), keeping a folder only if `os.path.isfile(.../name/Containerfile)`
(`58`).
**Gotchas:** that is the only test — a stray `.DS_Store` is no sandbox (`58`), and a broken Containerfile is caught
only as a failed build.
### image(name)

**Why it exists:** one spelling of the image tag for `build`, `has_image`, `built_at`, `remove`, `rename`.
**How:** `"localhost/sandbox-" + name` (`63`) — the `localhost/` prefix marks it as locally built, so Podman never
looks in a registry and `rmi` never pulls.
**Gotchas:** renaming a sandbox means re-tagging the image (`563-566`).
### has_image(name)

**Why it exists:** tells "never built" from "built" in `/sandbox list` (`596`) and before remove/rename (`546,562`).
**How:** `podman("image", "exists", image(name))[0] == 0` (`66`).
### containerfile(name)

**Why it exists:** the Containerfile *is* the sandbox, so showing it shows what the sandbox can do.
**How:** `read_text(SANDBOXES_DIR/name/Containerfile)` (`69`); `read_text` (`config.py:74-78`) returns `""` for a
missing file, so an empty one prints "(empty)" (`367`) instead of raising.
### The two Containerfiles in the repo

`Sandboxes/ubuntu/Containerfile` is one line, `FROM docker.io/library/ubuntu:24.04`; `Sandboxes/python/Containerfile`
is that plus `RUN pip install --no-cache-dir numpy pandas matplotlib` on a `python:3.12-slim` base. `FROM` picks a
prebuilt base image, `RUN` executes at build time and freezes the result into a layer. Notebooks need `python3` inside
(`tools/notebook/_notebook.py:52`), so `python` is the notebook sandbox; `ubuntu` is bare, the one to extend. Note
what is *absent*: no `VOLUME`, `WORKDIR`, `CMD` — mounts, working folder and `sleep infinity` all come from
`start()`'s `podman run` arguments (`163-169`).
### engine_dir()

**Why it exists:** the notebook engine sits in `Shared/Notebooks_Engine/` on the host and must be mounted;
`sandbox.py` mounts it, `tools/notebook/_notebook.py:21` checks `client.py` is there.
**How:** `os.path.normpath(os.path.join(SHARED_DIR, ENGINE))` (`74`) — `normpath` fixes Windows slashes.
### reserved(name)

**Why it exists:** `common` and `Notebooks_Engine` are not projects: no tool may create, mount, rename or delete them.
**How:** `name.lower() in (COMMON.lower(), ENGINE.lower())` (`77`) — lower-cased, because on macOS/Windows `Common`
and `common` are one folder.
### workdir()

**Why it exists:** a shell must start somewhere sensible: the project if mounted, else `common`.
**How:** `if my_project: return "/workspace/" + my_project` else `"/workspace/" + COMMON` (`81-84`).
**Gotchas:** reads the module global, so it answers for *this* instance only; `exec()` passes it as `-w` every call
(`380`), so the working folder follows the mount.
### Group C — finding containers, and the network switch (`sandbox.py:87-131`)

### containers()

**Why it exists:** an instance must see every container this program started, in any instance, including leftovers of
crashed ones — for project locking, cleanup and `users()`.
**How it works, line by line:**
- `podman("ps", "-a", "--filter", "label=harness.owner", "--format", "json")` (`89`) — `-a` includes stopped ones; the
  label filter is why hand-started containers are never listed, locked or removed (header `18-19`).
- `if code != 0 or not out: return []` (`90-91`), `except ValueError: return []` (`92-96`) — a missing, unhappy or
  chatty Podman yields "no containers", not an exception. `c.get("Labels") or {}` and `c.get("Names") or [""]`
  (`99-102`) handle Podman's `null`s and several names (the first is the one `--name` gave); the result is `{"name",
  "owner", "sandbox", "project", "shared"}` (`102-106`).

**Gotchas:** `"project": ""` means "no project mounted"; `shared` is the absolute `Shared/` path, which tells two
copies of this program on one machine apart. Because of `-a`, stopped containers count, so callers `cleanup()` first.
### cleanup()

**Why it exists:** instances die badly (crash, closed terminal, kill) and their containers keep running, holding a
project mounted so nobody else can use it. Nothing else would free it.
**How it works, line by line:**
- `old_one_of_mine = c["owner"] == INSTANCE and c["name"] != my_container` (`111`) — a container of *this* instance
  that is not the current one (the previous one, still being removed).
- `if old_one_of_mine or not locks.alive(c["owner"]):` (`112`) — `locks.alive` (`locks.py:133-137`) asks "is that
  instance running?" via its instance lock file, which the OS drops when the process ends, however it ends.
- `podman("rm", "-f", c["name"])` (`113`).

**Gotchas:** an owner-less container gives `owner == ""`, `locks.alive("")` is false, so it is removed (harmless: only
this program writes that label). One `podman ps` plus a `podman rm` per leftover.
### network_on()

**Why it exists:** the network is a live switch; the code must ask "is it on right now?" to avoid useless
connect/disconnect calls and to report the truth.
**How:** `podman("inspect", "-f", "{{json .NetworkSettings.Networks}}", my_container)` (`119`), then `code == 0 and
'"podman"' in networks` (`120`) — a container on Podman's default named network prints JSON containing `"podman"`.
**Gotchas:** a substring test on JSON, not parsing; it assumes `my_container` is set, and callers check.
### set_network(on)

**Why it exists:** the only place the internet is switched — for `/sandbox net on|off` (`607`) and to restore the
state after start/restart (`176`).
**How:** `if not my_container: return False` (`124-125`); `podman("network", "connect", "podman", my_container)`
(`126-127`) or `disconnect` (`128-129`) — `podman` here is the *name* of Podman's default network; then `return
network_on() == on` (`130`), "verify, don't assume".
**Gotchas:** the return value is the truth, so failures get reported: "network could NOT be sealed, careful" (`427`),
"could not switch the network" (`615`).
### Group D — the lifecycle: build, open, close (`sandbox.py:134-222`)

### build(name)

**Why it exists:** the Containerfile is the whole truth about a sandbox, so the image is re-derived from it at every
open.
**How:** a print (`135`, "quick if nothing changed"), then `podman("build", "-t", image(name),
os.path.join(SANDBOXES_DIR, name))` (`136`) — the sandbox folder is the build context, so files next to the
Containerfile would be visible to `COPY`/`ADD` (neither shipped one uses them).
**Gotchas:** on failure it returns `"the build of " + name + " failed. the end of its log:\n" + out[-2000:]` (`138`) —
the *last* 2000 characters, because Podman's log ends with the real error. No timeout, no `--pull`.
### start(name, project, network)

**Why it exists:** this is where the container is actually created — the heart of the file.
**How it works, line by line:**
- `cleanup()` (`146`) frees leftovers of dead instances; `problem = build(name)` with early return (`147-149`).
- `os.makedirs(SHARED_DIR/common, exist_ok=True)` (`150`) — so Podman does not create the host folder itself, owned
  oddly; `starts += 1` (`151`), the name from section 2 (`152`), then `["run", "-d", "--rm", "--name", container,
  ...]` (`154`).
- Labels (`155-157`): `harness.owner=INSTANCE`, `harness.sandbox=name`, `harness.shared=SHARED_DIR` — what
  `containers()` and `cleanup()` read. `--network podman` (`158`, "sealed right below"), `--security-opt
  no-new-privileges` (`159`), `--init` (`160-161`, a pid 1 that reaps finished background programs such as a stopped kernel),
  `--pids-limit 512 --memory SANDBOX_MEMORY --cpus SANDBOX_CPUS` (`162`).
- `"-v", SHARED_DIR/common + ":/workspace/common:z,noexec"` (`163`); the engine mount only `if
  os.path.isdir(engine_dir())` (`164-165`, `:z,ro,noexec`); the project (`166-168`) adds `--label
  harness.project=<project>` and `:Z,noexec`.
- `["-w", "/workspace/" + (project or COMMON), image(name), "sleep", "infinity"]` (`169`) — the command that keeps the
  container alive; without it the container exits at once and, with `--rm`, vanishes.
- `code, out = podman(*args)`; failure → `"could not start " + name + ": " + out` (`170-172`); success → set the
  globals (`173-175`) and `set_network(network)` (`176`).

**Gotchas:** the globals are set *after* Podman succeeded, so a failed start leaves the instance knowing it has no
container. `starts` was already incremented, so names skip numbers. The container is on the network for the few
milliseconds between `run` and `disconnect` — unclear from the code whether anything closes that window.
### forget()

**Why it exists:** "this instance has no container anymore" must be one operation, including giving back the notebook
locks its kernels held.
**How:** `my_container = my_sandbox = my_project = None` (`181-183`), then `locks.release_all("notebook-")` (`184`).
**Gotchas:** pure bookkeeping — it stops and removes nothing; called by `stop()`, `running_here()`, `restart()`. Locks
of *other* instances are untouched (`locks.py:108-112`).
### stop()

**Why it exists:** the orderly way to end this instance's container.
**How:** `podman("stop", "-t", "2", my_container)` (`188`) — 2 seconds of grace before SIGKILL; `--rm` then deletes
it, so no `rm` is needed; then `forget()` (`189`).
**Gotchas:** the exit code is ignored; it assumes `my_container` is set, and every caller checks first (`shutdown`
tests `if my_container`, `close_sandbox`/`unmount_project` test `running_here()`), but `stop()` itself would raise
`TypeError` on `None` — unreachable today, not guarded here.
### running_here()

**Why it exists:** "does this instance have a live sandbox?" must come from Podman, not memory, because a container
can die meanwhile (out of memory, removed by hand).
**How:** `if not my_container: return None` (`193`); `podman("container", "inspect", "-f", "{{.State.Running}}",
my_container)` (`194-195`); `if code == 0 and out == "true": return my_sandbox` (`196-197`); else `forget()` and
`None`.
**Gotchas:** the exact test `out == "true"` (Podman prints lowercase); any other answer — an error, `false`, empty —
means "gone", and the instance quietly loses its claim on notebooks and project. Runs on *every* `exec()`.
### restart(project)

**Why it exists:** Podman cannot add or remove a mount of a running container, so changing the project means a new
container.
**How:** `name = my_sandbox; network = network_on()` (`203-204`) captured before the container dies; `stop()`;
`start(name, project, network)` (`206`); failure → `"the sandbox was stopped, but could not start again: " + problem`
(`208`); success → "restarted <name> with the new folders: whatever was installed or started inside since its start is
gone, open notebooks are closed (nb_open them again), network on/off. " + `where()` (`209-211`).
**Gotchas:** the network state is carried over, so a restart never silently grants or removes internet.
### where()

**Why it exists:** the model must know which host folders it sees, in its own words.
**How:** "/workspace/common = Shared/common, shared with every other instance", plus "/workspace/<project> = your
project, no other instance can mount it now" or "no project mounted", ending "working folder: <workdir()>. everything
outside these folders is gone when the sandbox stops" (`214-220`).
**Gotchas:** the same information reappears in `projects_status` and `status`.
### Group E — projects: the folders in `Shared/` (`sandbox.py:224-313`)

### projects()

**Why it exists:** a project is a folder directly in `Shared/`, nothing else; this list drives every project tool.
**How:** keeps an entry when `not reserved(name) and not name.startswith(".") and os.path.isdir(...)` (`229`).
**Gotchas:** no name validation here; a bad name is still listed, with "can't be mounted" in `projects_status`
(`306-307`).
### holder(project)

**Why it exists:** a project may be mounted by one container at a time; this answers "who has it now?".
**How:** `cleanup()` (`234`) so a dead instance cannot hold it forever, then scan `containers()` for `c["project"] ==
project and c["shared"] == SHARED_DIR` (`236`): "you" if that container is `my_container`, else "another instance",
`None` if free.
**Gotchas:** the truth lives in the label, not in a lock; the `shared` comparison keeps two harness installations on
one machine from blocking each other.
### name_problem(name)

**Why it exists:** every path that creates, mounts, renames or deletes a project needs the same validation and
messages.
**How:** `common`/`Notebooks_Engine` get explaining sentences (`244-247`); then "invalid project name: letters,
digits, - _ . only, at most 60 characters, e.g. sales-2026" for `not re.fullmatch(PROJECT_NAME, name) or
len(name) > 60` (`248-249`); `None` when fine.
**Gotchas:** `fullmatch`, so the whole string must match; existence is `check_project`'s job.
### spelled(name)

**Why it exists:** on Windows/macOS `Web` and `web` are one folder; tools must speak the spelling the folder really
has.
**How:** the first `existing.lower() == name.lower() and existing != name` from `projects()` (`254-257`), else `None`.
### check_project(project)

**Why it exists:** the single gate before a project is mounted. **How, in order:** `name_problem` (`262-264`);
`spelled` → "that project is called '<real spelling>': use that spelling" (`265-266`); not in `projects()` → "no
project called '<x>'. projects: <list>. create_project makes a new one" (`267-270`); `holder(...) == "another
instance"` → "<project> is mounted by another instance right now, and only one sandbox at a time may have a project.
pick another one, or try again later" (`271-274`). `None` means mountable.
**Gotchas:** "you" passes here; remounting your own project is stopped earlier by "is mounted already" (`449-450`).
### projects_status()

**Why it exists:** the `check_projects` tool: what projects exist and who has which, in one readable block.
**How:** `NOT_AVAILABLE` if Podman is missing (`277-278`); `here = running_here()` **before** `cleanup()` (`279-280`)
so this instance is not cleaned away by itself; `taken` = project → container name (`282-285`); three fixed
explanation lines (`286-290`), this instance's line (`291-297`), then per project "can't be mounted ..." / "free" /
"mounted by you" / "mounted by another instance, not available now" (`304-313`).
**Gotchas:** empty case is "projects: none yet. create_project makes one" (`299-301`).
### Group F — the status texts (`sandbox.py:315-372`)

### built_at(name)

**Why it exists:** "built 2026-10-11 18:12:03" tells whether an image exists without dumping JSON.
**How:** `podman("image", "inspect", "-f", "{{.Created}}", image(name))` (`317`), then `out[:19] if code == 0 and out
else None` (`318`) — the first 19 characters of `2026-10-11 18:12:03.123 +0200 CEST`, i.e. no fraction, no zone.
### running_info()

**Why it exists:** one line about this instance's container for `status()`.
**How:** `podman("inspect", "-f", "{{.State.StartedAt}}", my_container)` (`322`), then "running in this instance since
<first 19 chars>, network on/off", plus ", project X mounted" or ", no project mounted" (`323-327`).
**Gotchas:** the exit code is ignored — if the container just died, `since` is Podman's error text and the line is
nonsense (callers normally asked `running_here()` first).
### others_running(name)

**Why it exists:** to say "running in N other instance(s)" — several instances may use one sandbox, a container each.
**How:** count `containers()` with `c["sandbox"] == name and c["owner"] != INSTANCE` (`330-334`).
**Gotchas:** counts stopped leftovers too; both callers call `cleanup()` first.
### status(name=None)

**Why it exists:** the `check_sandbox` tool and `/sandbox check`: look at everything, change nothing.
**How it works, line by line:**
- Guards: `not available()` → `NOT_AVAILABLE` (`338-339`); unknown name → "no sandbox called '<x>'. sandboxes: ..."
  (`340-341`); none at all → "no sandboxes yet. the user makes one: a folder in Sandboxes/ with a Containerfile
  inside" (`342-343`). Then `here = running_here()` **then** `cleanup()` (`344-345`), the same order as
  `projects_status`.
- Without a name: this instance's line ("running in this instance: python (...) . one sandbox per instance." or
  "none") and the note that every start rebuilds from the Containerfile and nothing installed at runtime is kept
  (`348-354`). Per sandbox: "=== sandbox: <name> ===", "image: built <built_at>" or "not built yet, it is built at the
  first start (can take a while)" (`358-360`), the state line (`361-365`), "also running in N other instance(s), each
  in its own container" (`366-368`), then "Containerfile:" and its whole text (`369-371`); `"\n".join(lines).strip()`
  (`372`).

**Gotchas:** the whole Containerfile is included on purpose — that is what lets the model *pick* a sandbox.
### Group G — using the container (`sandbox.py:375-405`)

### exec(command, timeout=MAX_TOOL_TIMEOUT)

**Why it exists:** the agent's only way in; every `sandbox_shell` call lands here.
**How it works, line by line:** a guard (`377-378`: "no sandbox runs in this instance. start one with open_sandbox
(check_sandbox shows which ones there are)"), then `podman("exec", "-w", workdir(), my_container, "timeout", "-k",
"5", str(timeout), "bash", "-c", command, timeout=timeout + 10)` (`380-381`), then four ways out: `TimeoutExpired` →
"error: no result after N seconds, command stopped" (`382-383`); `code == 124` → `out + "\nerror: stopped after N
seconds"` (`384-385`); another non-zero → `out + "\n(exit code N)"` (`386-387`); zero → `out or "(no output)"`
(`388`).
**Gotchas:** `bash -c` means the model's string is shell-interpreted, so quoting mistakes become bash errors, not
harness errors. A command that legitimately exits 124 is reported as a timeout. The `timeout` binary must exist in the
image (127 otherwise; both shipped images have it). The outer `timeout+10` lets the inner one fire first.
### shell()

**Why it exists:** the user's `/sandbox shell`: a real terminal inside, for debugging.
**How:** needs `running_here()` (`391-392`), prints "you are root inside <name>. type exit to come back to the chat."
(`393`), then `subprocess.run([CONTAINER_CMD, "exec", "-it", "-w", workdir(), my_container, "bash"])` (`395`),
returning "back in the chat" (`398`).
**Gotchas:** the exit code is ignored and the sandbox keeps running; a missing binary is caught here
(`FileNotFoundError` → "podman not found", `396-397`) because this call bypasses `podman()`.
### shutdown()

**Why it exists:** leaving must not leave a container behind; `main.py` registers it with `atexit` (`main.py:160`) and
calls it on a normal exit (`main.py:224`).
**How:** `if my_container: print("[sandbox] stopping " + my_sandbox); stop()` (`402-404`) — "nothing to save, nothing
to ask" (docstring).
**Gotchas:** it only knows *this* instance's container; leftovers of a crash are `cleanup()`'s job
(`main.py:161-162`).
### Group H — the agent's tools (`sandbox.py:408-524`)

Each of these wraps the pieces above in `with lock:` (`38`) and returns plain English; the lock is why two parallel
tool calls cannot open or mount at once.
### open_sandbox(name, project=None)

**Why it exists:** the `open_sandbox` tool: start a sandbox, optionally with a project mounted right away.
**How it works:** `not available()` → `NOT_AVAILABLE + ". tell the user"` (`410-411`); `running_here()` → refuse a
second sandbox ("only one per instance: close_sandbox first", `412-415`); unknown name → the real list (`416-418`);
`check_project` (`419-421`); `start(name, project, False)` (`422`, the network always starts off for the agent); then
"network off" or "network could NOT be sealed, careful" (`426-429`) and `"running <name>, <network>. " + where()`
(`430`).
**Gotchas:** `check_project` runs *after* the "already running" test, so a bad project name is reported only when a
sandbox could actually be opened.
### close_sandbox()

**Why it exists:** the `close_sandbox` tool.
**How it works:** `running_here()` or "no sandbox runs in this instance" (`435-437`); remember `my_project`; `stop()`;
"stopped <here>. whatever was installed or started inside is gone; the files in the mounted folders stay", plus ".
<project> is free for other instances again" (`439-444`).
**Gotchas:** "free again" holds because the container carrying the `harness.project` label is gone, so `holder()`
finds nobody.
### mount_project(project)

**Why it exists:** the `mount_project` tool: mount a project later, at the price of a restart.
**How it works:** needs `running_here()` (`447-448`); `project == my_project` → "is mounted already, at
/workspace/<p>" (`449-450`); `check_project`, then `restart(project)`, prefixed "unmounted <old> (free for other
instances again). " when one was mounted before (`452-459`).
**Gotchas:** a bad name or a taken project is refused *before* anything is stopped, so a failed mount never costs the
running container; a successful one costs everything inside it.
### unmount_project()

**Why it exists:** the `unmount_project` tool.
**How it works:** needs `running_here()` (`463-464`); without a project → "no project is mounted. (common is always
mounted and can't be unmounted)" (`465-466`); else "unmounted <old>, it is free for other instances again. " +
`restart(None)` (`468-469`) — it still restarts, the only way to drop a mount.
### create_project(name)

**Why it exists:** the `create_project` tool: a new, empty folder in `Shared/`.
**How it works:** `name_problem`; "a project called '<x>' exists already" (`474-475`); "there is a file called
'<name>' in Shared/ already: pick another name" (`476-478`); `os.makedirs` → "created project <name> (Shared/<name>).
mount_project mounts it" (`479-480`).
**Gotchas:** existence is checked twice on purpose — a *file* with that name is neither a project nor absent, and
`makedirs` would raise.
### delete_project(name)

**Why it exists:** the `delete_project` tool: remove a project folder and everything in it (`rmtree`, no undo).
**How it works:** `if reserved(name): return name_problem(name)` (`485-486`); "use that spelling" (`487-488`); not a
project → the list (`489-490`); `os.path.islink(path)` → "is a link to another folder, not a folder in Shared/: the
user has to remove it" (`492-494`); `holder(name)` refuses for "you" ("unmount_project first, then delete it",
`495-497`) and for another instance (`498-499`); `shutil.rmtree(path)` (`500`).
**Gotchas:** `rmtree` is final and walks into every subfolder; the symlink check is the one guard against deleting a
folder outside `Shared/`.
### rename_project(old, new)

**Why it exists:** the `rename_project` tool.
**How it works:** `reserved(old)`; `old not in projects()`; `name_problem(new)`; a *different* existing project with
the same case-insensitive name is refused (`509-511`), so `web -> Web` passes but `web -> Web` beside a separate
`Web` does not; `holder(old)` refuses while mounted (`512-517`); `os.rename` → "renamed <old> -> <new> (Shared/<new>)"
(`518-519`).
### Group I — the user's `/sandbox` commands (`sandbox.py:526-616`)

### users(name)

**Why it exists:** "how many containers of this sandbox exist right now, in any instance" — the guard before removing
or renaming one.
**How it works:** `cleanup()` (`528`), then count `containers()` with `c["sandbox"] == name` (`530-533`); stopped
leftovers still count.
### INVALID_NAME / valid_name(name)

**Why they exist:** a sandbox name becomes part of an image tag, so it must be what Podman accepts.
**How they work:** `INVALID_NAME` (`535`) is "invalid name: lowercase letters, digits and hyphens only, e.g.
my-box-2"; `valid_name` is `re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) is not None` (`539`) — lowercase alphanumerics
with single hyphens *between* groups.
### remove(name)

**Why it exists:** `/sandbox remove <name>`: delete a sandbox (folder + image).
**How it works:** not in `names()` → "no sandbox called '<name>'" (`541-542`); `users(name)` → "runs right now ... it
can only be removed when no instance runs it" (`543-544`); `podman("rmi", image(name))`, failure → "could not remove
its image: " + out (`545-548`); `shutil.rmtree(SANDBOXES_DIR/name)` (`549-550`).
**Gotchas:** no `-f` on `rmi` deliberately (the comment: it would also remove containers using the image); the folder
goes only after the image.
### rename(name, new_name)

**Why it exists:** `/sandbox rename <old> <new>`: rename the folder *and* move the image tag along.
**How it works:** checks `names()`, `valid_name`, "exists already", `users(name)` (`554-561`); if an image exists,
`podman("tag", image(name), image(new_name))` then `podman("untag", image(new_name), image(name))` (`562-567`) — new
tag first, then drop only the old one, so the image survives without a rebuild; `os.rename` of the folder (`568-569`).
**Gotchas:** `untag`'s exit code is ignored; a failing `tag` gives "rename failed: " + out and no folder change.
### HELP / SUBCOMMANDS (`sandbox.py:570-578`)

`HELP` is the six-line usage text (`list|check|remove|rename|net|shell`, plus "the agent opens and closes its sandbox
itself"); `SUBCOMMANDS` is that list, used only to recognise a typed subcommand.
### command(words)

**Why it exists:** the dispatcher behind `/sandbox ...`, called from `main.py:203`.
**How it works, line by line:**
- `what = words[0] if words else "help"` (`582`); `if what in SUBCOMMANDS and not available(): print(NOT_AVAILABLE)`
  (`583-585`) — one clear sentence instead of six failing subcommands; the chain is `if/elif`, so nothing else runs
  then.
- `list` (`586-599`): `running_here()`, `cleanup()`, per sandbox the marks " (running here)", " (running in N other
  instance(s))", " (not built yet)", or "none. a new sandbox: a folder in Sandboxes/ with a Containerfile inside".
- `check` with at most one word → `print(status(...))` (`600-601`); `remove`/`rename` with strict word counts
  (`602-605`); `net` only with `on|off` (`606-614`); `shell` (`615-616`); anything else → `HELP` (`617-618`, the
  file's last line).

**Gotchas:** wrong argument counts silently fall through to `HELP` rather than an error.
## 4. The mounts: exactly what the container sees of the machine

Everything a container can reach on the host is created in `start()` (`sandbox.py:163-168`):

| host path | inside | flags | when | why |
|---|---|---|---|---|
| `Shared/common/` | `/workspace/common` | `z,noexec` | always (made at `150`) | the shared desk: every container of every instance sees it, so instances hand files to each other |
| `Shared/<project>/` | `/workspace/<project>` | `Z,noexec` | when a project is mounted (`166-168`) | the one project this container works on; the `harness.project` label beside it makes it exclusively taken |
| `Shared/Notebooks_Engine/` | `/workspace/Notebooks_Engine` | `z,ro,noexec` | when the folder exists (`164-165`) | the notebook engine (`kernel.py`, `client.py`); read-only, so nothing inside can change the code that runs notebooks |

`z`/`Z` are SELinux labels — `z` ("shared") lets several containers use the folder, `Z` ("private") gives it to this
one container only, which matches `common` being shared and a project being exclusive. `ro` is read-only, `noexec`
means files there cannot be executed as programs (`python3 x.py` still works: the *interpreter* is executed, it only
reads the file). What is **not** mounted: the rest of `Shared/`, the home folder, the program folder, any container
socket, and `/tmp` — the container has its own `/tmp`, deleted with it (there is no `/tmp` mount anywhere in
`sandbox.py`). `-w` (`169`) is a working *directory*, not a mount, and must be one of the two mounted folders — which
is why `workdir()` (`79-84`) only returns `/workspace/<project>` or `/workspace/common`.
## 5. The actual Podman command lines

**Command the code builds (a) — building an image** (`sandbox.py:136`):

```
podman build -t localhost/sandbox-python /…/AI-Harness-main/Sandboxes/python
```

`-t` tags the result; the last argument is the build context folder, where the `Containerfile` is found.

**Command the code builds (b) — running a shell command** (`sandbox.py:380-381`):

```
podman exec -w /workspace/common sandbox-python-48213-20261018165603-1 \
  timeout -k 5 600 bash -c 'python3 -c "print(2+2)"'
```

`exec` runs a second process in a running container; `-w` is the working directory (`workdir()`); the name is
`my_container`; after it comes the command *inside*: GNU `timeout` with `-k 5` (hard kill 5 s after the polite stop)
and the limit `600` = `MAX_TOOL_TIMEOUT` (`config.py:50`), then `bash -c` with the model's string as one argument.
Python also passes `timeout=610` to `subprocess.run` (`381`), always 10 s longer than the in-container limit.

**Command the code builds (c) — starting with a project mounted** (`sandbox.py:154-169`, line breaks added):

```
podman run -d --rm --name sandbox-python-48213-20261018165603-1 \
  --label harness.owner=48213-20261018165603 --label harness.sandbox=python \
  --label harness.shared=/…/AI-Harness-main/Shared \
  --network podman --security-opt no-new-privileges --init \
  --pids-limit 512 --memory 2g --cpus 2 \
  -v /…/Shared/common:/workspace/common:z,noexec \
  -v /…/Shared/Notebooks_Engine:/workspace/Notebooks_Engine:z,ro,noexec \
  --label harness.project=website \
  -v /…/Shared/website:/workspace/website:Z,noexec \
  -w /workspace/website localhost/sandbox-python sleep infinity
```

`-d` returns at once; `--rm` deletes the container when it stops; `--init` gives it a real pid 1 that reaps zombies;
`no-new-privileges` blocks setuid-style privilege gain; `--pids-limit/--memory/--cpus` are the limits; `-v
host:container:flags` is one mount; the last three arguments are the image and the command that keeps it alive.

**Command the code builds (d) — stopping** (`sandbox.py:188`):

```
podman stop -t 2 sandbox-python-48213-20261018165603-1
```

`-t 2` waits two seconds after SIGTERM before SIGKILL; because of `--rm` Podman then deletes the container, so a clean
stop needs no separate `podman rm` (only `cleanup()` uses `podman rm -f`, `sandbox.py:113`).
## 6. What the user and the model actually see

`tools/sandbox/sandbox_shell.py:5` passes the model's string straight to `sandbox.exec(command, MAX_TOOL_TIMEOUT)`,
and the model sees `exec()`'s return value in full: the command's output only on success (e.g. `4`); `(no output)` for
silence (`sandbox.py:388`); the output plus `(exit code 1)` on failure (`386-387`); `error: stopped after 600 seconds`
when the in-container `timeout` fired (`384-385`), or `error: no result after 600 seconds, command stopped` if even
Python's longer wait ran out (`382-383`). With no container — including a container that died under the tool, since
`running_here()` notices and `forget()`s (`191-199`) — it is "no sandbox runs in this instance. start one with
open_sandbox (check_sandbox shows which ones there are)" (`377-378`). Missing podman arrives as "podman not found"
with code 127 (`44-45`), ordinary text like any other answer.

Truncation is not the sandbox's doing: text longer than `RESULT_TO_FILE` (8,000 characters, `config.py:31`) is written
by `agent.run_tool` to `results/000042-sandbox_shell.txt`, and the model gets the start, the end and the path, to
continue with `read_result` (`agent.py:269-281`). A failing command never raises from `exec()`; only a real Python
exception inside a tool becomes `"error: " + str(e)` (`agent.py:267-268`).
## What this chapter hands to the rest of the guide

- `sandbox.exec(command, timeout)` (`sandbox.py:375`) — the only entry `sandbox_shell` uses
  (`tools/sandbox/sandbox_shell.py:5`); `tools/notebook/_notebook.py:52` uses it too, to run `client.py` in the
  sandbox.
- `open_sandbox` / `close_sandbox` / `mount_project` / `unmount_project` / `status` / `projects_status`
  (`sandbox.py:408`, `433`, `445`, `461`, `336`, `275`) — one line each in `tools/sandbox/*.py`; they are
  `MAIN_ONLY_TOOLS` (`config.py:39-42`), never given to subagents.
- The in-memory state `sandbox.my_container` / `my_sandbox` / `my_project` (`sandbox.py:34-36`), read from outside by
  `tools/results/copy_result.py:18` and `tools/notebook/_notebook.py:29-31`.
- Constants others reuse: `sandbox.COMMON` (`29`), `sandbox.ENGINE` (`30`), `sandbox.engine_dir()` (`71`),
  `sandbox.running_here()` (`191`).
- The labels `harness.owner` / `harness.sandbox` / `harness.project` / `harness.shared` (`sandbox.py:155-157,167`) —
  the cross-process truth behind `containers()` (`87`) and `cleanup()` (`108`); the project "lock" is the label, not a
  file.
- Error strings to quote: `NOT_AVAILABLE` (`51`), "no sandbox runs in this instance ..." (`377`), "could not start
  <name>: ..." (`172`), "the build of <name> failed ..." (`138`), "the sandbox was stopped, but could not start again:
  ..." (`208`), "invalid project name ..." (`249`), "<project> is mounted by another instance right now ..." (`272`),
  `INVALID_NAME` (`535`).
- `MAX_TOOL_TIMEOUT = 600` (`config.py:50`), `SANDBOX_MEMORY`/`SANDBOX_CPUS` (`config.py:48-49`) — the limits are
  configuration passed into `exec()` and `start()`, not code.
- `shutdown()` (`sandbox.py:400`) is wired to `atexit` (`main.py:160`) and to the normal exit (`main.py:224`);
  `cleanup()` (`sandbox.py:108`) is the safety net when a process dies without running it.

