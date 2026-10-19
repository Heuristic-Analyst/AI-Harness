# 07 — Long results and the notebook engine

**In this chapter:** (each section then goes function by function, or tool by tool)
- A1. The problem and the two functions that solve it
- A2. The shared part: which files may be touched (`tools/results/_results.py`)
- A3. `read_result` — paging through a file
- A4. `search_result` — grep over your own results
- A5. `copy_result` — stop reading, start computing
- A6. The life of one 30,000-character result, end to end
- B1. Plain words first: notebook, kernel, and why both are needed
- B2. The two halves: who runs where, and why the split exists
- B3. The protocol
- B4. `client.py`, the one-shot messenger
- B5. `kernel.py`, the thing that holds your variables
- B6. The nine tools the model actually calls
- B7. The rules the model is told to follow (`Skills/notebook/SKILL.md`)
- B8. One worked example (reconstructed from the code)
- Goal
- What to remember

---

Two things that look unrelated and are one story.

**Long tool results.** A command that prints 30,000 characters, a `grep` that finds 5,000 lines: the model
cannot swallow that. The harness does not truncate it (information would be lost) and does not summarise it (a
summariser can lie). It moves it to a file, gives the model a small window onto that file, and adds three small
tools to page through it.

**The notebook engine.** Real `.ipynb` files run by a real Python kernel inside the sandbox, variables alive
from cell to cell. The most machinery-dense part of the codebase: a tool on your machine talks to a one-shot
messenger inside the container, which talks over a socket to a long-lived kernel process that holds your
variables and rewrites a JSON file after every change.

Part A first: it is small, and Part B reuses the same idea (big answers don't fit). Files in play:
`config.py`, `agent.py` (`save_result`, `preview`, `move_old_results`) and `tools/results/*.py` run on your
machine; `Shared/Notebooks_Engine/client.py` and `kernel.py` run **inside the sandbox**; `tools/notebook/*.py`
run on your machine and `Skills/notebook/SKILL.md` holds the rules the model is given.

---

# Part A — tool results that are too big

## A1. The problem and the two functions that solve it

Every tool result handed back to the model is appended to the conversation and stays there for the rest of it.
One `cat` of a big file can eat a fifth of the context window and then be re-sent (and re-paid for) on every
model call for the next two hundred turns. So the harness draws a line, `config.py:31`:

```python
RESULT_TO_FILE = 8_000     # tool results longer than this (in characters) go into a file in the conversation folder.
                           # the model gets the start and the end of it, and reads the rest with read_result
```

Enforced in exactly one place, `agent.py:269`:

```python
if len(result) > RESULT_TO_FILE and name not in WHOLE_RESULTS:   # long? into a file. the model gets a preview
    result = preview(self.save_result(name, result), result)
```

Characters, not tokens: cheap and predictable, and 8,000 characters is roughly 2,000 tokens. `WHOLE_RESULTS`
(`agent.py:94`) is `load_skill`, `read_memory`, `read_result`, `search_result` — never file-ified, because the
agent needs all of them and they cap themselves (the two readers at 6,000 chars per call). `copy_result` is not
on the list; it just always returns one short line. And nothing is thrown away: the result goes to disk, the
model gets a preview saying where the rest is.

### save_result — the file and its number (`agent.py:273`)

```python
def save_result(self, name, text):
    """put a tool result into its own file in results/. returns its path, as the agent uses it: results/000042-name.txt"""
    with self.lock:                                           # parallel tool calls: one number each
        self.results += 1
        path = "results/" + str(self.results).zfill(6) + "-" + name + ".txt"   # 6 digits: in order up to 999,999
    os.makedirs(os.path.join(self.folder, "results"), exist_ok=True)
    with open(os.path.join(self.folder, path), "w", encoding="utf-8") as f:
        f.write(text)
    return path
```

- `with self.lock`: every tool call of one reply runs in its own thread (`agent.py:259`), so two long results
  can be saved at the same instant; without the lock, `+= 1` could hand the same number to both.
- `zfill(6)` → `000042`, so a plain directory listing sorts in creation order.
- `"-" + name`: the tool's registered name (safe as a file name — no slashes), so a human sees who made it.
- `self.folder`: the agent's own folder — `Conversations/<name>/`, or
  `Conversations/<name>/agents/<when>-<id>/` for a subagent (`agent.py:5-10`).
- The returned path is **relative** (`results/000042-sandbox_shell.txt`): the string the model sees and hands
  back to `read_result`.

The counter starts at `highest_result(folder)` (`agent.py:111`, used at `agent.py:134`): list `results/`, take
everything before the first `-`, keep the max. So numbering survives a restart of the program and a name is
never reused in one conversation — an old `read_result` can never silently read a different file.

### preview — exactly what the model sees (`agent.py:99`)

```python
    lines = text.split("\n")
    head = "\n".join(lines[:40])[:3000]                           # the first 40 lines, at most 3000 characters
    tail = "\n".join(lines[-20:])[-1500:] if len(lines) > 40 else ""   # and the last 20
    answer = ("[result: " + path + ", " + format(len(text), ",") + " characters, " + format(len(lines), ",") + " lines. "
              "this is only the start" + (" and the end" if tail else "") + ": read_result and search_result show the rest]\n"
              + head)
    if tail:
        answer += "\n...\n" + tail
```

At most 3,000 + 1,500 characters, whether the original was 9k or 9MB. Head *and* tail are kept because real
output is usually interesting at one end: a traceback ends with the error, an `ls` starts with the listing.

```
[result: results/000042-sandbox_shell.txt, 30,412 characters, 512 lines. this is only the start and the end: read_result and search_result show the rest]
$ python build.py
reading 1,204 records from data/raw.csv
...
Traceback (most recent call last):
  File "build.py", line 88, in <module>
    total += row["amount"]
KeyError: 'amount'
```

Two details that matter later: the header begins with the literal `[result: ` and has a comma after the path
(**`move_old_results` parses it with a regex**, A6); and if the text is 40 lines or fewer there is no tail, so
the header says `this is only the start:` and a 9,000-character 12-line result shows only its first 3,000
characters. Intentional, but surprising the first time.

That leaves two holes: the model saw lines 1-40 and cannot ask for line 300, and cannot `grep` or run pandas
over the file. `read_result`/`search_result` fill the first, `copy_result` the second.

## A2. The shared part: which files may be touched (`tools/results/_results.py`)

All three tools first ask "is this one of *my* result files?". This 60-line file is the security layer.

```python
def parts_of(file):          # 'results/x.txt' -> ['results', 'x.txt']; backslashes count as slashes
    parts = []
    for part in str(file).replace("\\", "/").split("/"):
        if part not in ("", "."):
            parts.append(part)
    return parts
```

`""` and `.` parts are dropped, **`".."` is deliberately kept** so the next function can see it and refuse —
dropping it would turn an escape attempt into a valid path.

```python
def is_result_path(parts):
    """results/<file>, or agents/<x>/results/<file>, or agents/<x>/agents/<y>/results/<file>, ..."""
    if len(parts) < 2 or parts[-2] != "results" or ".." in parts:
        return False
    position = 0
    while position < len(parts) - 2:                              # in front of results/: pairs of agents/<name>
        if parts[position] != "agents" or position + 1 >= len(parts) - 2:
            return False
        position += 2
    return True
```

The grammar in one line: `<rel> ::= ("agents/" <folder>)* "results/" <file>` — as deep as `MAX_DEPTH = 3`.
`log.jsonl`, `checkpoint.md`, `../results/x.txt`, `agents/foo/log.jsonl` and `/etc/passwd` all die here.

```python
def resolve(agent, file):
    """the real path of one of the agent's result files, or None if it isn't one"""
    parts = parts_of(file)
    if not is_result_path(parts):
        return None
    path = os.path.join(agent.folder, *parts)
    inside = os.path.realpath(agent.folder) + os.sep              # also through links: it must really be in the agent's folder
    if not os.path.realpath(path).startswith(inside) or not os.path.isfile(path):
        return None
    return path
```

- `os.path.join(agent.folder, *parts)`: the name is always relative, so `/results/x.txt` is read as
  `<folder>/results/x.txt` — a leading slash can never escape.
- **`realpath` on both sides + `startswith(inside)` with a trailing separator.** This survives symlinks:
  without `realpath`, a link named `results/evil.txt` pointing at `/etc/shadow` would pass a prefix test on the
  unresolved path. The trailing `os.sep` stops the classic `/a/bc` vs `/a/b` prefix bug.
- `isfile` turns a directory or a missing file into a clean "not found" instead of a traceback.

A subagent's folder is physically *inside* its parent's folder, so a parent can read `agents/<id>/results/x.txt`
(intended: it reads its children's work). A subagent cannot reach up (`..` refused) or sideways (a sibling is
not under *this* agent's `agents/`). `all_results` (walk the folder, keep what passes `is_result_path`) gives
the same set for `search_result` with no `file`, and `not_found` (`_results.py:53`) is the refusal message — a
good one, because it lists what the model *can* read and so corrects a hallucinated path in one round trip:

```
no result file 'results/17-log.txt'. yours (the last 20):
results/000039-sandbox_shell.txt
results/000041-sandbox_shell.txt
```

## A3. `read_result` — paging through a file

**Why:** the preview shows lines 1-40 and the last 20; the rest needs a way to be asked for in pieces too small
to flood the context again.

```python
MAX_LINES = 200          # lines per call at most
MAX_CHARS = 6_000        # characters per call at most, so a read never floods the context
LINE_CUT = 1_000         # a single longer line is cut here
```

Three independent limits for three different dangers: 200 short lines, 200 lines of 900 characters each, and
one line that is a megabyte of minified JSON. `MAX_CHARS` is below `RESULT_TO_FILE`, which is why `read_result`
sits in `WHOLE_RESULTS`: its own answer never needs to be file-ified.

```python
def run(agent, file, from_line=1, lines=MAX_LINES):
    path = _results.resolve(agent, file)
    if not path:
        return _results.not_found(agent, file)
    start = max(1, int(from_line))
    count = max(1, min(int(lines), MAX_LINES))
```

Arguments are **clamped, not rejected**: `from_line=0` becomes 1, `lines=9999` becomes 200, `lines=0` becomes
1. A model cannot get an error merely for asking for too much. (`int()` can still raise on garbage, but
`agent.py:267-268` catches everything and hands the model `"error: ..."` as text.)

```python
    # (above this: shown = []; size = 0; total = 0; full = False)
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:                                            # line by line: a huge file never has to fit into memory
            total += 1
            if total < start or full or len(shown) >= count:
                continue
            line = line.rstrip("\n")
            if len(line) > LINE_CUT:
                line = line[:LINE_CUT] + " ...(line cut, " + format(len(line), ",") + " characters)"
            entry = str(total) + ": " + line
            if size + len(entry) > MAX_CHARS and shown:
                full = True                                       # the character limit is reached: the rest is counted, not shown
                continue
            shown.append(entry); size += len(entry) + 1
    if start > total:
        return file + " has " + format(total, ",") + " lines. from_line " + str(start) + " is past the end"
    last = start + len(shown) - 1
    answer = file + ": lines " + str(start) + "-" + str(last) + " of " + format(total, ",") + "\n" + "\n".join(shown)
    if last < total:
        answer += "\n(more: read_result with from_line=" + str(last + 1) + ")"
```

- `for line in f` streams, so a 5GB file costs no memory; the loop always walks to the end, which is how the
  header can say "of 512" when you asked for 12 lines in the middle. The `continue` does three jobs at once —
  before `start`, budget gone, count reached — and all three keep counting instead of breaking.
- `errors="replace"`: results can hold raw bytes from a program that printed binary; without it `open()` would
  raise and lock the agent out of its own data.
- `str(total) + ": "` is the file's own line number: a page of 380-389 is prefixed `380:` … `389:`.
- **`and shown`** is essential: the char limit only applies once one line is in, so a 5,000-character line
  (cut to 1,000) can never produce an empty page.

```
results/000042-sandbox_shell.txt: lines 380-389 of 512
380: Traceback (most recent call last):
381:   File "build.py", line 88, in <module>
382:     total += row["amount"]
383: KeyError: 'amount'
389:     raise SystemExit(1)
(more: read_result with from_line=390)
```

That `(more: ...)` line *is* the paging mechanism: the model is handed the next offset and never computes it.
Other shapes: `results/000007-x.txt has 92 lines. from_line 500 is past the end`, and for an empty file
`... has 0 lines. from_line 1 is past the end`.

**Gotchas.** `from_line` is a line number, not a byte offset — a file that is one enormous line gives 1,000
characters per call with no way to skip ahead (that case wants `copy_result`). And `lines` is a maximum, never
a promise: the character budget can end a page early, with `(more: ...)` telling the truth.

## A4. `search_result` — grep over your own results

**Why:** 512 lines is nothing, 200,000 lines is a data-processing problem, and a language model is the worst
tool for it. This lets the model ask "where does it say KeyError", get three line numbers, then `read_result`
around them: two small context blocks instead of fifty.

```python
MAX_HITS = 50            # matching lines shown per call at most
MAX_CHARS = 6_000
HIT_CUT = 300            # a matching line is shown up to this many characters

def run(agent, text, file=None, regex=False):
    if file:
        path = _results.resolve(agent, file)
        if not path:
            return _results.not_found(agent, file)
        files = [file]
    else:
        files = _results.all_results(agent)                       # no file: all of them
        if not files:
            return "you have no result files yet"
    if regex:
        try:
            pattern = re.compile(text, re.IGNORECASE)
        except re.error as e:
            return "that regex doesn't work: " + str(e)
    else:
        pattern = re.compile(re.escape(text), re.IGNORECASE)      # plain text, upper or lower case doesn't matter
```

- One file: validated through `resolve`, and the *name* is kept for the hit lines. No file: `all_results` —
  own results **plus every subagent's, recursively**, which is why the description says "your subagents'
  included".
- **`regex=False` escapes the text** (`re.escape`), so searching `df.head()` needs no escaping of the dot and
  does not crash on `(`. A very common model mistake, removed by design. `regex=True` compiles the text as a
  pattern and, on a bad pattern, returns the compiler's words instead of raising.
- **Both modes are `IGNORECASE`** and there is no match-case flag, so case can never make an answer wrong.

```python
    # (above this: hits = []; size = 0; count = 0)
    for name in files:
        with open(_results.resolve(agent, name), encoding="utf-8", errors="replace") as f:
            number = 0
            for line in f:
                number += 1
                if not pattern.search(line):
                    continue
                count += 1                                        # every hit is counted, even the ones not shown
                if len(hits) >= MAX_HITS:
                    continue
                entry = name + ":" + str(number) + ": " + (line[:HIT_CUT] + " ..." if len(line) > HIT_CUT else line)
                if size + len(entry) > MAX_CHARS:
                    continue
                hits.append(entry); size += len(entry) + 1
    if not count:
        return "no line contains '" + text + "'" + (" in " + file if file else " in your " + str(len(files)) + " result files")
    answer = format(count, ",") + " matching lines" + (", the first " + str(len(hits)) + " shown" if count > len(hits) else "")
    return answer + ". read_result with from_line shows what is around one:\n" + "\n".join(hits)
```

`count` (true total) versus `len(hits)` (what fits) is what lets the answer say "the first 50 shown". The loop
never breaks, so a common pattern costs a full scan — the price of an honest total.

```
3 matching lines. read_result with from_line shows what is around one:
results/000042-sandbox_shell.txt:88:     total += row["amount"]
results/000042-sandbox_shell.txt:383: KeyError: 'amount'
results/000051-nb_run.txt:12: (error) KeyError: 'amount'
```
```
412 matching lines, the first 50 shown. read_result with from_line shows what is around one:
```
```
no line contains 'KeyError' in your 7 result files
```

**Gotchas.** The search is line-based, so a pattern spanning a newline never matches (a `\n` in a regex is
dead). Each hit is cut at 300 characters and `read_result` then cuts at 1,000, so a hit inside a
5,000-character JSON line is genuinely hard to read — that is the signal to `copy_result` and use `jq`.
Searching all files also searches subagent files, so a hit can point into `agents/<id>/results/...`, which
`read_result` accepts: the round trip works across agents.

## A5. `copy_result` — stop reading, start computing

**Why:** the two readers are for *looking*. For *processing* — filtering a 200MB CSV, parsing 300k lines of
JSON, a pandas table — reading 6,000 characters at a time with the model as the computer is absurd. Result
files live in the agent's folder on the host, outside the sandbox; this copies one into a folder the sandbox
can see, so real code can open it.

```python
def run(agent, file, to, name=None):
    path = _results.resolve(agent, file)
    if not path:
        return _results.not_found(agent, file)
    to = str(to).replace("\\", "/")
    if to.startswith("/workspace/"):                              # "/workspace/common/x" is fine too: it means common/x
        to = to[len("/workspace/"):]
    target = _results.parts_of(to)
    if to.startswith("/") or not target or ".." in target:
        return "the target must be a folder like common or common/data/raw (or your mounted project, e.g. website/data)"
    allowed = sandbox.COMMON + "/..."
    project = sandbox.my_project if sandbox.running_here() else None   # the project only while this instance's sandbox has it
    if project:
        allowed += " or " + project + "/..."
    if target[0] != sandbox.COMMON and target[0] != project:
        return "you can copy into " + allowed + ", nowhere else" + ("" if project else " (no project is mounted right now)")
    name = name or os.path.basename(path)
    if "/" in name or "\\" in name or name in (".", ".."):
        return "name is only a file name, e.g. data.csv: the folder goes into to"
    folder = os.path.join(SHARED_DIR, *target)
    inside = os.path.realpath(os.path.join(SHARED_DIR, target[0])) + os.sep
    if not (os.path.realpath(folder) + os.sep).startswith(inside):   # also through links: it must stay in that folder
        return "that folder is outside " + target[0] + "/"
    destination = os.path.join(folder, name)
    if os.path.exists(destination):
        return "/workspace/" + "/".join(target) + "/" + name + " exists already: pick another name"
    os.makedirs(folder, exist_ok=True)                            # missing folders are created
    shutil.copyfile(path, destination)
```

- The model lives half in the host world (`Shared/common/x`) and half in the container world
  (`/workspace/common/x`); the `/workspace/` rewrite accepts the spelling it will naturally write.
- Only `common` or the mounted project, checked on the **first part**: anywhere else can be wiped when the
  sandbox stops or is invisible to the container. `sandbox.running_here()` gates the project, because the copy
  lands on the host at `Shared/<project>/` — "your mounted project" only means something while *this*
  instance's sandbox has it mounted.
- `name` must be a bare file name, else the model would pick the folder twice. The **`realpath` prefix test**
  is the same symlink defence as `resolve`.
- **`os.path.exists` → refuse**: a copy never overwrites (`tools/results/README.md:27`). Silently replacing a
  user's data file is unrecoverable, so the model is told to pick another name.
- `makedirs(..., exist_ok=True)` makes `common/data/raw` work in one call; `shutil.copyfile` copies contents
  only.

```
copied to /workspace/common/data/raw.csv (for the user: Shared/common/data/raw.csv). work on it in your sandbox, with sandbox_shell or a notebook
```

Both paths on purpose: the model works in `/workspace/...`, the user in `Shared/...`, and the model must be
able to repeat this line in a report without translating. With no sandbox up, `. no sandbox runs right now:
open one first` is appended (the copy still happens — it is a host-side `shutil.copyfile`).

**Gotchas.** The copy is a one-way snapshot: editing the copy does not change the result file, and there is no
tool to copy back — so a result file is immutable from the agent's side, and line numbers quoted in an old tool
call stay valid. And `to` is a *folder*: `to="common/data/raw.csv"` creates a folder called `raw.csv`.

## A6. The life of one 30,000-character result, end to end

1. **The tool returns a string** (`agent.py:266`): `sandbox_shell` ran `python build.py`, 30,412 characters.
2. **`run_tool` checks length** (`agent.py:269`): over 8,000, `sandbox_shell` not in `WHOLE_RESULTS`.
3. **`save_result` numbers it**: `self.results` 41 → 42, path `results/000042-sandbox_shell.txt`, written
   under `Conversations/<name>/results/`.
4. **`preview` builds the window** (`agent.py:99`): header, first 40 lines, `...`, last 20 lines.
5. **The preview enters the conversation** (`agent.py:304`): ~4,500 characters instead of 30,412 — some 1,100
   tokens instead of 7,600, on every later model call too.
6. **The model reads the rest** with `read_result(from_line=381, lines=30)` and finds the `KeyError`. Each
   answer is short and never file-ified itself: no infinite regress.
7. **Later the context fills up mid-task.** `make_room` (`agent.py:360`) fires above `EMERGENCY_AT` (80% of
   `CONTEXT_LIMIT`). Before anything as drastic as a checkpoint, `move_old_results` (`agent.py:433`):

```python
    if KEEP_RESULTS:
        older = tool_messages[:-KEEP_RESULTS]                 # the newest ones stay as they are
    for m in older:
        found = re.match(r"\[result: (results/[^,]+),", m["content"])   # a preview: it is in a file already
        path = found.group(1) if found else self.save_result(m["name"], m["content"])
        m["content"] = MOVED + path + ", " + format(len(m["content"]), ",") + " characters here before. read_result shows it]"
```

   `KEEP_RESULTS = 3` keeps the three newest tool results untouched. For each older one: if it is already a
   preview, the regex recovers its path — which is exactly why `preview`'s header is parseable, written at
   `agent.py:104` and read back at `agent.py:445`; otherwise it gets a file of its own, named after the tool
   stored on the message (`"name": call.function.name`, `agent.py:304`). `MOVED` is `agent.py:96`:

```
[moved out of your context to make room: results/000042-sandbox_shell.txt, 4,481 characters here before. read_result shows it]
```

   The count is the *preview's* size, not the file's 30,412 — odd wording, and it is what the code does.
8. **Only if that was not enough** does `make_room` write an emergency checkpoint and clear the context
   (`agent.py:372-379`): two escalating steps, pointers to files first, checkpoint second. Checkpoints say so
   too (`agent.py:92`): "Earlier tool results are in your results/ files: read_result shows them". The counter
   is never reset, so new files never collide with old ones.

All of Part A in one sentence: **the harness never forgets, it moves things out of sight.** The context is a
viewport; `Conversations/<name>/` is the memory.

One rough edge: the regex only matches paths starting with `results/`, so a preview of a *subagent's* file
(`agents/<id>/results/...`) would not match and `move_old_results` would save the *preview* into a *new* file.
Unreachable in practice (`read_result` answers are never previewed, being in `WHOLE_RESULTS`) and harmless if
hit: you would see a result file whose whole content is a `[result: ...]` header.

---

# Part B — the notebook engine

## B1. Plain words first: notebook, kernel, and why both are needed

**A notebook** is one file, `something.ipynb`, which is really a JSON document:

```json
{"cells": [{"cell_type": "markdown", "id": "7b2c9e10", "source": "## Goal\n- compute revenue"},
           {"cell_type": "code", "id": "3f9a1c0b", "source": "revenue", "execution_count": 2,
            "outputs": [{"output_type": "execute_result", "execution_count": 2,
                         "data": {"text/plain": "36.0"}, "metadata": {}}]}],
 "nbformat": 4, "nbformat_minor": 5, "metadata": {...}}
```

Cells in order; each cell has a type (`code`, `markdown`, `raw`), an id, its source, and — for code cells —
the outputs of the last run and the number `[n]` shown beside it in Jupyter. That is all a notebook is: a
pretty-printed list of cells plus saved outputs. Anyone with Jupyter can open it.

**A kernel** is a separate Python process. The notebook file holds *code*; the kernel holds *the running
state*: every module imported and every variable created, in one long-lived dictionary. In Jupyter you press
Shift+Enter, your editor sends the cell's text to that process over a socket, and the process runs it and
sends back the output.

**Why the harness runs a real kernel instead of `exec()`ing the cells.** You could fake it: read the source of
the cells above, `exec` them all, then `exec` the new one. It breaks almost immediately — it re-does expensive
work every time, it re-prints every earlier output, side effects (a file written, a server started) happen
twice, and an `import` of a 2GB dataframe is repeated on every keystroke. Real Jupyter keeps state *between*
calls, and that is the entire point:

```python
# cell 1
df = load_csv("data/raw.csv")      # 40 seconds, 2 GB in memory

# cell 2
df.head()                          # instant: df already exists in the kernel
```

`df` surviving matters because data analysis is a conversation with your data: load once, look, adjust, look
again. Nothing about this is possible if every cell starts from zero. So the harness gives each open notebook
its own real Python process, and that process keeps `df` alive for as long as it runs.

## B2. The two halves: who runs where, and why the split exists

The engine is two files, and the split between them is the design:

| | `Shared/Notebooks_Engine/kernel.py` | `Shared/Notebooks_Engine/client.py` |
|---|---|---|
| how long it lives | forever, until closed | one command, then exits |
| how many | one per open notebook | one per tool call |
| what it holds | the variables, the cells, the file | nothing |
| talks | socket server (`Listener`) | socket client (`Client`) |
| started by | `client.py` | the tool, via `sandbox.exec` |

The call chain for one `nb_run` is worth memorising:

```
tools/notebook/nb_run.py            host: the thin tool, run(agent, path, cell_ids)
  tools/notebook/_notebook.py       host: packs the command as base64, calls sandbox.exec
    sandbox.py exec                 host: podman exec ... bash -c "python3 -B /workspace/Notebooks_Engine/client.py <payload>"
      client.py                     container: decodes, finds/starts the kernel, sends the command
        kernel.py                   container: runs the cell, saves the file, answers
```

Why a messenger in between, rather than the tool talking to the kernel directly? Because **the tool runs on
your machine and the code must run in the container.** The sandbox is where python3, pandas and the user's
data live; your machine is only the orchestrator. `sandbox.exec` can only run a *command and wait for it to
finish* — it has no channel to a process that stays alive. So:

- `kernel.py` is started once, in the background, in its own session
  (`start_new_session=True`, `client.py:70`), and stays alive holding the variables.
- `client.py` is started per tool call, connects to the kernel's socket, sends one command, prints the answer
  and exits. That is why a tool call's result is just "what a command printed" — the same shape as
  `sandbox_shell`.
- The kernel writes every change into the `.ipynb` file itself, so the answer can be short (cell id + output +
  overview) and the file is still always current.

**Read-only mount.** The engine lives in the shared folder and every sandbox sees it read-only, `sandbox.py:165`:

```python
args = args + ["-v", engine_dir() + ":/workspace/" + ENGINE + ":z,ro,noexec"]   # ro = read-only: the agent can't change it
```

`ro` means the agent (or a cell) can use the engine but never modify it — otherwise a cell could rewrite
`kernel.py` and take over the sandbox's notebook machinery. `noexec` means it cannot even be executed directly
as a binary. That is also why `client.py` is invoked with `-B` (no `__pycache__`): a read-only mount has
nowhere to write bytecode, and the `-B` flag is repeated in `_notebook.py:52` and `client.py:186`. The engine
itself uses **only the Python standard library** (`kernel.py:8`), so it works in any sandbox that has
`python3` at all.

A note on the naming: it is tempting to read `client.py` as "the client side, i.e. the host part". It is not.
`client.py:1` says so plainly: "it runs INSIDE the sandbox". The host part is `_notebook.py`. `client.py` is a
client *of the kernel*, not of the agent.

## B3. The protocol

A command is a JSON dict, base64-encoded into a command line argument (`_notebook.py:50-52`), so quotes, `$`
and backticks in cell source can never confuse bash. The kernel's answer is **a string, always** — not a dict.
(`handle()` returns strings; `client.py` prints them; `sandbox.exec` returns what was printed.) The dicts go
the other way, from host to kernel. The only dict the kernel writes is the notebook file itself.

Every command dict carries these, added by `_notebook.py:50`:

```python
{"cmd": <name>, "notebook": "common/sales.ipynb", "timeout": 570, ...per-command fields...}
```

`timeout` is `MAX_TOOL_TIMEOUT - 30` = 570 seconds: a slow cell is stopped 30 seconds *before* the sandbox's
own limit would kill the whole `podman exec` (`tools/notebook/README.md:36`).

| `cmd` | extra fields | who handles it | what it does | answer (text) |
|---|---|---|---|---|
| `create` | — | `client.prepare` + kernel | refuses if open or file exists; starts a kernel (which creates the empty `.ipynb`); then sends `show` | `created <nb> and started its kernel (no variables yet)` + `open notebooks now: ...` + the `show` answer (for a new file: just `common/x.ipynb: 0 cells`) |
| `open` | — | `client.prepare` + kernel | already open → keeps kernel; else starts one; then sends `show` | `opened <nb> with a fresh kernel: ...` or `<nb> was already open, its variables are kept` + `open notebooks now: ...` + overview |
| `close` | — | `client.prepare` | sends `close` to the kernel, waits for the socket to vanish | `closed <nb>: its variables are gone, the file stays` + `open notebooks now: ...` |
| `rerun` | — | `client.prepare` + kernel | close, start a fresh kernel, then send `run_all` | `fresh kernel (all old variables gone), every code cell run from the top:` + outputs + overview |
| `show` | — | kernel `handle` | nothing changes | `outline` + every cell with full source and output |
| `add` | `source`, `kind` (`code`/`markdown`), `after` (cell id or null), `run` (bool) | kernel | inserts a cell, saves, optionally runs it | `added cell <id>` (+ `>>> output:` + output) + blank line + overview |
| `edit` | `cell_id`, `source`, `run` | kernel | replaces the whole source, saves, optionally runs | `edited cell <id>` (+ output) + blank line + overview |
| `remove` | `cell_id` | kernel | deletes the cell, saves | `removed cell <id> (variables it made stay until the kernel restarts)` + overview |
| `run` | `cell_ids` (list) | kernel | one id → `run_cell`; several → `run_many` (stops at first error) | outputs (+ `--- <id> ---` headers) + overview |
| `run_all` | — | kernel | every code cell top to bottom, stop at first error | outputs + overview |
| `close` (at the kernel) | — | kernel `serve` | sends `"closed"`, breaks the loop, kernel exits | `closed` |
| anything else | — | kernel | — | `unknown command '<name>'` |

The kernel's cell dict (what `self.cells` holds, and what `save` flattens into JSON) —

```python
{"id": "3f9a1c0b", "type": "code", "source": "revenue", "outputs": [...],
 "count": 2, "ran": "revenue", "metadata": {}, "attachments": None}
```

— where `count` is the `[n]` and `ran` is *the source that actually ran* (`None` if never run in this kernel;
that one field is what makes the `EDITED` state possible).

A full, realistic `nb_run` exchange. The tool call:

```python
nb_run(path="common/sales.ipynb", cell_ids=["3f9a1c0b"])
```

The dict `_notebook.py` builds and `client.py` receives (`notebook` is the path as the model wrote it):

```python
{"cmd": "run", "notebook": "common/sales.ipynb", "cell_ids": ["3f9a1c0b"], "timeout": 570}
```

`client.py` adds nothing, normalises `notebook` to `/workspace/common/sales.ipynb`, and sends exactly that
dict to the kernel. The answer — one string, printed by `client.py`, returned by `sandbox.exec`:

```
36.0

common/sales.ipynb: 2 cells
  1. 7b2c9e10  markdown  | ## Goal
  2. 3f9a1c0b  ran [2]  | import csv
```

That is the whole protocol: a dict in, a string out.

## B4. `client.py`, the one-shot messenger

188 lines. Every tool call is one run of `python3 -B client.py <base64 command>` (`client.py:2`). Constants
first (`client.py:23-27`):

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kernel import door, WORKSPACE                         # the same address rule as the kernel, from the file next to us
KERNEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kernel.py")
LOG = "/tmp/nb-kernels.log"                                # what a kernel prints when it breaks. never ends up in a notebook
```

Importing `door` from `kernel.py` is the whole point of that `sys.path` line: host and kernel must agree on the
socket address, so they use *one* implementation. `LOG` is where a kernel's own crashes go — a traceback from
the engine must never be mistaken for a cell's output.

**`door(path)`** (`kernel.py:27`) is the address: `"/tmp/nb-" + md5(path)[:10]`, `kernel.py:29`:

```python
def door(path):
    """the address of the kernel of one notebook: a socket file in /tmp. client.py finds the kernel through it"""
    return "/tmp/nb-" + hashlib.md5(path.encode()).hexdigest()[:10]
```

Deterministic and path-based: given the notebook path, anybody can compute where its kernel listens, without a
registry. The 10 hex characters are enough to avoid collisions and short enough to be a unix socket path (which
has a ~108-character limit). **The path string must match exactly on both sides** — that is why `client.main`
does `os.path.normpath(os.path.join(WORKSPACE, name))` and the kernel does `os.path.abspath(sys.argv[1])` on
the same normalised string. If they disagreed, client and kernel would look at two different doors and every
tool call would think no kernel was running.

**`connect(address, wait=0)`** (`client.py:30`) tries `Client(address)` and retries every 0.1 s until `wait`
seconds have passed, returning `None` on `FileNotFoundError`/`ConnectionRefusedError`. `wait=0` means "answer
now, I only want to know if a kernel is up"; `start` instead loops on `connect(...)` with its own 15 s deadline.

**`only_one(path)`** (`client.py:41`) is a `fcntl.flock` on `door(path) + ".lock"`, held across starting and
stopping a kernel. Two tool calls in one reply run in parallel; without this, both could see "not open" and
both start a kernel for the same notebook — two processes writing the same `.ipynb`. (This is a *different*
lock from `locks.py`, which is host-side and per instance: `notebook-<md5>` in `Locks/`. Two locks because
there are two races: two kernels in one container, and two instances on one machine.)

**`open_notebooks()`** (`client.py:49`) lists `/tmp/nb-*.json`, and for each one reads
`/proc/<pid>/cmdline` to check the process really is `kernel.py` for that notebook. That `/proc` check exists
because after a sandbox restart a stale `.json` file can name a pid that now belongs to something else
entirely. Result: `open notebooks now: common/sales.ipynb, common/report.ipynb` or `... none`.

**`start(path)`** (`client.py:64`) — the exact command line:

```python
process = subprocess.Popen([sys.executable, "-B", KERNEL, path], cwd=os.path.dirname(path),   # the notebook's folder
                           stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                           start_new_session=True)     # own session: it lives on after this messenger quits
```

- `sys.executable` — the same interpreter that runs `client.py` (which is `python3` in the container).
- `-B` — no `__pycache__`, because the engine folder is mounted read-only.
- `path` — absolute, so `kernel.py` can `abspath` it unchanged and land on the same `door`.
- **`cwd=os.path.dirname(path)`** — the kernel's working folder is the notebook's folder, so a cell's relative
  paths (`open("data/raw.csv")`) resolve next to the notebook, exactly like Jupyter. `SKILL.md:58` tells the
  model this, and `os.makedirs` on that folder at `client.py:66` is what lets a notebook live in a folder that
  did not exist yet.
- `stdin=DEVNULL` — nothing can ever read input; the kernel also redirects fd 0 to `/dev/null` itself
  (`kernel.py:351-353`), so `input()` in a cell gets "end of input" instead of hanging forever.
- `stdout=stderr=log` (opened append) — engine crashes go to `/tmp/nb-kernels.log`, never into a notebook.
- `start_new_session=True` — the kernel is not killed when `client.py` exits; it detaches into its own session.

Then it waits up to 15 s: `connect(door)` in a loop, and `process.poll()` to notice a kernel that died while
starting. On failure it returns a string (not a connection) with the last 1,500 characters of the log — this is
what makes "why won't it start" answerable:

```python
return "error: the kernel did not start. the end of its log (" + LOG + "):\n" + last
```

Note the `isinstance(desk, str)` tests in `prepare`: `start` returns *either* a connection *or* an error
string, and every caller has to tell them apart.

**`ask(desk, command, path)`** (`client.py:83`) — send one command, get one answer, with the timeout dance:

```python
    desk.send(command)
    timeout = command.get("timeout", 300)
    try:
        if desk.poll(timeout):                             # the normal case: an answer in time
            return desk.recv()
    except EOFError:                                       # the kernel died while working (e.g. the cell used up all memory)
        return ("error: the notebook kernel crashed (most often: out of memory). ALL variables are gone and the notebook "
                "is closed. ...")
    info = door(path) + ".json"
    with open(info) as f:                                  # too slow: ctrl+c for the kernel. the cell stops, the variables stay
        pid = json.load(f)["pid"]
    os.kill(pid, signal.SIGINT)
    try:
        if desk.poll(15):
            return "(it ran longer than " + str(timeout) + " seconds and was stopped)\n" + desk.recv()
    except EOFError:
        pass
    os.kill(pid, signal.SIGKILL)                           # it ignored ctrl+c (stuck in C code): end it for good
```

Four outcomes, and the handling of each matters:

1. **An answer in time** — the normal path.
2. **`EOFError`** — the socket died, i.e. the kernel process is gone (out of memory is the usual cause). The
   model gets a precise, actionable message: variables are gone, the *cells are still in the file*, `nb_open`
   it again.
3. **No answer within `timeout`** — `client.py` plays the user pressing Ctrl+C: it reads the kernel's pid from
   `<door>.json` and sends `SIGINT`. The kernel's handler (`kernel.py:50`) turns that into a
   `KeyboardInterrupt` **only while a cell is running**, so the cell stops and the variables survive. The
   answer is prefixed with `(it ran longer than 570 seconds and was stopped)`, and note that `desk.recv()` is
   *then* read: the interrupted cell still sends its (error) output, so the model sees where it was.
4. **No answer 15 s after SIGINT** — stuck in C code that ignores signals. `SIGKILL`, then the stale socket and
   `.json` files are removed, and the model gets the "everything is gone, the file is intact" message.

That escalation ladder (wait → Ctrl+C → kill) is why a runaway cell costs you your variables only in the worst
case, and never costs you the notebook.

**`close(path)`** (`client.py:109`) connects (if a kernel is there), sends `{"cmd": "close"}`, waits for the
reply, then waits up to 5 s for the socket file to disappear — because the *next* `open` must be able to bind
the same address. Without that wait, a `nb_rerun` (close + start) could race and the new kernel would find the
address still taken.

**`prepare(what, name, path)`** (`client.py:123`) is the decision table *before* the real work; it returns
`(connection, text-to-put-first)` or `(None, the whole answer)`:

- `create`: already open → refuse (`is already open. use it, or nb_close it first`); file exists → refuse
  (`exists already. nb_open opens it, or pick another name`); else start and report `open notebooks now`.
- `open`: already open → keep the kernel, show the notebooks, then continue (so the model gets the full view);
  no file → `there is no notebook <nb>. nb_create makes a new one`; else start and report the fresh-kernel note.
- `close`: no kernel → `is not open` + list; else close.
- anything else: **needs a running kernel**. No kernel but the file exists → `is not open (or its kernel
  stopped, e.g. the sandbox restarted). nb_open it first`; no file → `there is no notebook ...`.
- `rerun`: close, start fresh, and prefix every output with `fresh kernel (all old variables gone), every code
  cell run from the top:`.

**`main(payload)`** (`client.py:172`) ties it together:

```python
    command = json.loads(base64.b64decode(payload))
    name = command["notebook"]                             # as the agent wrote it, e.g. analysis/sales.ipynb
    path = os.path.normpath(os.path.join(WORKSPACE, name))
    with only_one(path):                                   # starting and stopping kernels: one messenger at a time
        desk, text = prepare(command["cmd"], name, path)
    if desk is None:                                       # nothing more to do: closed, not open, an error, ...
        return text
    work = {"create": "show", "open": "show", "rerun": "run_all"}.get(command["cmd"], command["cmd"])
    return text + ask(desk, dict(command, cmd=work), path)   # the real work, outside the lock: it may take minutes
```

Read the last two lines carefully, they are the trick of the whole file: `create`/`open` are translated into
`show`, `rerun` into `run_all`, and everything else is passed through. And note **the real work happens outside
`only_one`** — the lock protects starting and stopping a kernel (fast), never the cell execution (which may
take ten minutes; holding the lock would block every other tool call on that notebook).

## B5. `kernel.py`, the thing that holds your variables

386 lines, standard library only, because it must run in *any* sandbox with python3.

### Module level

```python
WORKSPACE = os.environ.get("NB_WORKSPACE", "/workspace")   # the shared folder. notebook paths are shown relative to it
SHOW_OUTPUT = 4000                                         # characters of one output the agent sees. the file keeps all of it
def new_id():
    return uuid.uuid4().hex[:8]                            # e.g. "3f9a1c0b". stays the same when cells move around
def cut(text, limit=SHOW_OUTPUT):
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...(" + str(len(text) - limit) + " more characters, all of it is in the notebook file)"
def joined(text):
    return "".join(text) if isinstance(text, list) else (text or "")
```

- `new_id()` — 8 hex characters. **Cell ids are the API**: the model addresses cells by id, never by position,
  so inserting or removing a cell never invalidates an instruction the model already wrote.
- `cut()` — the same idea as `RESULT_TO_FILE`, one level down: 4,000 characters of an output reach the model,
  the file keeps all of it. A 200MB dataframe printout therefore does not enter the conversation, and the
  message says where the rest is.
- `joined()` — the `.ipynb` format allows text either as one string or as a list of lines ("jupyter saves
  lists"). Jupyter itself writes lists; this normalises to one string on load and accepts both on read.

### Running one cell: `execute` (`kernel.py:55`)

This is `exec()` plus everything a notebook needs around it. Five things happen.

**1. Not-an-exit.** `except BaseException as e:` (`kernel.py:78`) — `BaseException`, not `Exception`, because
`sys.exit()` / `exit()` in a cell must not end the kernel. A cell calling `quit()` becomes an error output; the
kernel and every variable live on.

**2. The catch-all stdout/stderr.** File-descriptor level, not `contextlib.redirect_stdout`:

```python
        saved = os.dup(1), os.dup(2)
        os.dup2(caught.fileno(), 1)                        # catch everything the cell prints: print(), errors, and even
        os.dup2(caught.fileno(), 2)                        # programs it starts (os.system, subprocess)
```

Redirecting `sys.stdout` in Python would miss a subprocess that writes to fd 1, a C extension that `printf`s, or
`os.write(1, ...)`. Swapping the descriptors catches all of it. The flushes before and after
(`kernel.py:61-62, 86-87`) are what stop output from leaking across the boundary.

**3. Like Jupyter: a bare last expression is displayed.** `ast.parse` first, and if the last statement is an
expression it is popped off and `eval`'d separately (`kernel.py:68-74`):

```python
            tree = ast.parse(source, name)
            last = None
            if tree.body and isinstance(tree.body[-1], ast.Expr):   # like jupyter: a bare last line is shown (df.head())
                last = ast.Expression(tree.body.pop().value)
            exec(compile(tree, name, "exec"), memory)
            if last is not None:
                result = eval(compile(last, name, "eval"), memory)
```

That is why a cell ending in `revenue` shows `30.0` instead of nothing. Compiled with `name = "<cell 3f9a1c0b>"`,
so every traceback says which cell and which line — the single most useful thing in the whole engine.

**4. An exception becomes an error output, not a crash.** The traceback is *trimmed* to start at the cell:

```python
            tb = e.__traceback__
            while tb and tb.tb_frame.f_code.co_filename != name:   # skip the kernel's own lines, start at the cell
                tb = tb.tb_next
            error = {"output_type": "error", "ename": type(e).__name__, "evalue": str(e),
                     "traceback": traceback.format_exception(type(e), e, tb)}
```

Without the trimming, every error would show three frames of `execute()`/`eval()` internals at the top, and the
model would learn to ignore tracebacks. `Ctrl+C` has its own branch (`kernel.py:75`), producing
`ename: "KeyboardInterrupt"` and `evalue: "stopped because it took too long. the variables are kept"`.

**5. Plots.** `take_figures()` (`kernel.py:114`) looks for `matplotlib.pyplot` **only if it is already in
`sys.modules`** — the engine never imports matplotlib, so a sandbox without it costs nothing. If it is there,
every open figure is saved as a PNG into a `BytesIO`, base64-encoded, and `plt.close("all")` is called so the
next cell does not re-draw the same plot. `MPLBACKEND=Agg` is set in `serve` (`kernel.py:350`) so plots go to
memory, never to a window that does not exist.

The outputs list it returns is exactly the `.ipynb` format:

```python
    outputs = []
    if printed:
        outputs.append({"output_type": "stream", "name": "stdout", "text": printed})
    for png in figures:
        outputs.append({"output_type": "display_data", "data": {"image/png": png, "text/plain": "<Figure>"}, "metadata": {}})
    if error:
        outputs.append(error)
    elif result is not None:
        data = {"text/plain": repr(result)}
        html = getattr(result, "_repr_html_", None)        # pandas tables look like tables in the notebook
        ...
        outputs.append({"output_type": "execute_result", "execution_count": count, "data": data, "metadata": {}})
```

Note: **stdout and stderr are one block**, named `stdout`, because both descriptors point at the same temporary
file. So a Python warning and a `print` arrive interleaved in one stream, and `stderr` never appears in the file
as a separate output. A real Jupyter keeps them apart. This is a deliberate simplification (interleaving in the
right order is more useful than separating them, for a reader of the notebook).

### `as_text` — outputs as the model reads them (`kernel.py:130`)

The model gets text, never JSON. Per output type: `stream` → its text; `display_data`/`execute_result` with a
PNG → the literal line `[figure: a plot, shown in the notebook]`; with `text/plain` → that text; else
`[image/png output, shown in the notebook]` naming the keys; `error` → the formatted traceback, or
`ename: evalue`. All joined by newlines, then `cut()` to 4,000 characters, and `"(no output)"` when there is
nothing at all. That `(no output)` matters: it tells the model the cell ran and said nothing, which is
different from "I do not know".

### The `Notebook` class

**`__init__`** (`kernel.py:155`) sets up the state: `memory = {"__name__": "__main__"}` (the globals dict every
cell runs in — a cell's `if __name__ == "__main__"` therefore behaves like a script), `count = 0` (the `[n]`
counter, **one per kernel, not per cell**, exactly like Jupyter), `cells = []`, a default `metadata` with a
python3 kernelspec, and `saved_at = None`. Then:

```python
        if not os.path.exists(path):
            self.save()                                    # a new notebook: create the file right away
        else:
            try:
                self.load()
            except ValueError:                             # unreadable (half saved?): start empty, but NEVER save over it.
                pass                                       # saved_at stays None, so every command tries to read it again first
```

`nb_create` works because the kernel creates the file on startup. And a corrupt/unreadable file is not fatal:
the kernel starts empty and, because `saved_at` stays `None`, every later command re-reads the file first
(`changed_outside`), so the user's file is not overwritten by an empty notebook.

**`load`** (`kernel.py:172`) reads the JSON, normalises list-text to plain text, builds each cell dict keeping
`id`, `type`, `source`, `outputs`, `count` (= `execution_count`), `metadata`, `attachments`, and — the clever
line — carries over `ran` for cells it already knew:

```python
        known = {c["id"]: c for c in self.cells}
        ...
            if cell["id"] in known:
                cell["ran"] = known[cell["id"]]["ran"]
```

So after re-reading the file (because the *user* saved it in their editor), cells that already ran in this
kernel still say `ran [3]` instead of falling back to "old output". A `json.JSONDecodeError` is re-raised as a
`ValueError` with a readable message ("the notebook file can't be read right now (maybe it is being saved, or it
is broken) ... nothing was changed"), which `serve` turns into `error: ...` for the model.

**`save`** (`kernel.py:199`) writes the **whole** notebook, and writes it atomically:

```python
        temporary = self.path + ".saving"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(notebook, f, indent=1, ensure_ascii=False)
        os.replace(temporary, self.path)          # no one ever sees half a file
```

`os.replace` is atomic on the same filesystem, so Jupyter (or the user) can open the file at any moment and
never see a truncated notebook. `indent=1` and `ensure_ascii=False` are what make the file diff-friendly and
keep non-ASCII text readable. Cells are rebuilt in the canonical order of the format — `cell_type`, `id`,
`metadata`, `source`, then `attachments` if any, and for code cells `execution_count` and `outputs`. Cell ids
are always written (they are the model's handles). Markdown cells get no `outputs`/`execution_count` at all,
which is what the format expects. Finally `saved_at = os.path.getmtime(self.path)`.

**`changed_outside`** (`kernel.py:218`) — the mtime check:

```python
        if os.path.exists(self.path) and os.path.getmtime(self.path) != self.saved_at:
            self.load()
            return "note: the notebook file was changed outside (probably by the user) and was read again.\n\n"
        return ""
```

Why it exists: the user can have the notebook open in Jupyter while the agent works in it. Without this, the
agent's next `save()` would silently overwrite the user's edits with the kernel's stale copy. With it, the user
always wins: their version is loaded, and the model is told, so it re-reads the overview instead of charging
ahead. Every `handle` call and every `run_cell` calls it — `run_cell` *during* a run too, so a save that lands
while a cell executes is not overwritten by the outputs about to be written (`kernel.py:270-274`, including the
case where the cell was deleted meanwhile: the output is returned but not saved).

Two real limits: mtime granularity (a filesystem with 1-second timestamps can miss two writes in the same
second), and float equality on `st_mtime`. It is a heuristic, not a lock — the actual cross-instance protection
is `locks.py` on the host. (The tool description for `nb_open` hedges: "If you edit an open notebook yourself,
the kernel notices before its next step".)

**`status(c)`** (`kernel.py:226`) — one string per cell, the whole state machine:

```python
        if c["type"] != "code":
            return c["type"]                               # markdown (or raw)
        if c["ran"] is None:
            return "not run" if c["count"] is None else "old output, not run in this kernel"
        text = "ran [" + str(c["count"]) + "]"
        if c["ran"] != c["source"]:
            text += ", EDITED since, output is stale"
        if any(o.get("output_type") == "error" for o in c["outputs"]):
            text += ", error"
        return text
```

- `markdown` — nothing to run.
- `not run` — never ran anywhere.
- `old output, not run in this kernel` — the file has an `execution_count` from an earlier session (or an
  earlier kernel), so the output in the file is real but the variables behind it are gone. This is the state
  after `nb_open`, and it is the single most important one for the model to notice.
- `ran [n]` — ran here. `+ ", EDITED since, output is stale"` when the stored `ran` source differs from the
  current source (a `nb_edit` without a re-run), `+ ", error"` when the outputs contain an error.

**`outline()`** (`kernel.py:238`) — the overview appended to (almost) every answer:

```python
        lines = [os.path.relpath(self.path, WORKSPACE) + ": " + str(len(self.cells)) + " cells"]
        for number, c in enumerate(self.cells, 1):
            first = (c["source"].strip().splitlines() or [""])[0]
            first = first[:60] + ("..." if len(first) > 60 else "")
            lines.append("  " + str(number) + ". " + c["id"] + "  " + self.status(c) + "  | " + first)
```

```
common/sales.ipynb: 3 cells
  1. 7b2c9e10  markdown  | ## Goal
  2. 3f9a1c0b  ran [2]  | import csv
  3. a91d4e07  ran [3], EDITED since, output is stale  | revenue * 1.2
```

Two spaces between fields, `N.` is the *position* (not used for addressing), the id is 8 hex characters, then
the state, then `|` and the first line of the source cut at 60 characters. The first line of a markdown cell is
`## Goal` — which is exactly why the skill tells the model to put the goal in the first line of the first cell:
the overview doubles as a table of contents. Without an outline the model would have to call `nb_show` after
every change, and the whole notebook would be in the context.

**`full()`** (`kernel.py:247`) — the outline, then every cell with its complete source and output:

```
--- 2. 3f9a1c0b (ran [2]) ---
import csv
rows = [...]
revenue

>>> output:
36.0
```

(blank line before each header, `(empty)` for an empty cell, and `>>> output:` only when there is output.) This
is what `nb_show`/`nb_open` return — deliberately expensive, which is why the skill says the overview is
usually enough.

**`find(cell_id)`** (`kernel.py:257`) — `(position, cell)` or `LookupError("no cell '<id>'. the cells are:\n" +
outline)`. It never guesses a cell by position, and the error message contains the overview, so a model that
invented an id immediately sees the real ones.

**`run_cell(cell_id)`** (`kernel.py:263`) — the core operation:

```python
        position, c = self.find(cell_id)
        if c["type"] != "code":
            return "(" + c["type"] + " cell, nothing to run)"
        self.count += 1
        source = c["source"]
        outputs = execute(source, self.memory, cell_id, self.count)
        note = self.changed_outside()                      # the user saved the file while the cell ran? read their version
        try:                                               # first, so saving the outputs below doesn't overwrite it
            position, c = self.find(cell_id)
        except LookupError:
            return note + as_text(outputs) + "\n(this cell was deleted outside while it ran, so its output is not saved)"
        c["outputs"] = outputs
        c["count"] = self.count
        c["ran"] = source                                  # what really ran. edited meanwhile? then the overview says EDITED
        self.save()                                        # outputs go into the file right after every run
        return note + as_text(outputs)
```

Six decisions in fifteen lines: markdown is a no-op with a clear message; the counter increments **before** the
run (so a cell that errors still gets its number); `source` is captured before execution and stored in `ran`
(so an edit during the run shows as EDITED, not as silently-stale output); the re-`find` handles the user
deleting the cell mid-run; the file is saved **after every run** (which is what makes the notebook openable at
any moment); and the answer is the cell's text output, not the whole notebook.

**`run_many(cell_ids)`** (`kernel.py:281`) — runs in the given order and **stops at the first error**:

```python
        for cell_id in cell_ids:
            try:
                answer = self.run_cell(cell_id)
            except LookupError:
                answers.append("--- " + cell_id + " ---\n(no such cell, skipped)")
                continue
            answers.append("--- " + cell_id + " ---\n" + answer)
            if any(o.get("output_type") == "error" for o in self.find(cell_id)[1]["outputs"]):
                answers.append("(stopped at this error)")
                break
```

Verified: a missing id is *skipped*, not fatal (so a multi-id `nb_run` with one stale id still does the rest);
the stop test looks at the stored `outputs` for an `error` entry, which also catches a `KeyboardInterrupt`
(whose output is an error output). Stopping matters because later cells usually depend on earlier ones; running
them after a failure produces a pile of misleading `NameError`s.

**`handle(command)`** (`kernel.py:296`) — the dispatcher, and the shape is always the same:
`note = self.changed_outside()` first, then one `if` per command, and every answer ends with `outline()` for the
mutating commands. `add` validates `kind` (`"kind must be code or markdown"`), builds the cell, positions it at
`find(after) + 1` or at the end, saves, and optionally runs it inline:

```python
            answer = "added cell " + cell["id"]
            if command.get("run"):
                answer += "\n>>> output:\n" + self.run_cell(cell["id"])
            return note + answer + "\n\n" + self.outline()
```

`edit` replaces `source` and saves but touches neither `count` nor `outputs` — that is precisely what creates
the `EDITED since, output is stale` state. `remove` warns that variables survive. `run` with one id returns
`run_cell` + outline, with several `run_many` + outline. `run_all` is every code cell. Anything else returns
`unknown command '<x>'`.

**`serve(path)`** (`kernel.py:349`) — the loop that *is* the kernel's life:

```python
    os.environ.setdefault("MPLBACKEND", "Agg")             # plots are drawn into memory, not into a window
    nothing = os.open(os.devnull, os.O_RDONLY)
    os.dup2(nothing, 0)                                    # a cell calling input() gets "end of input" instead of hanging
    sys.stdin = open(os.devnull)
    signal.signal(signal.SIGINT, on_interrupt)
    notebook = Notebook(path)
    address = door(path)
    if os.path.exists(address):                            # left over from a kernel that crashed
        os.remove(address)
    with open(address + ".json", "w") as f:                # who we are: client.py reads it to interrupt us and to list
        json.dump({"pid": os.getpid(), "notebook": os.path.relpath(path, WORKSPACE)}, f)
    with Listener(address) as desk:
        while True:                                        # wait forever: this loop is why the variables survive
            messenger = desk.accept()
            try:
                command = messenger.recv()
                if command["cmd"] == "close":
                    messenger.send("closed")
                    break
                try:
                    messenger.send(notebook.handle(command))
                except (LookupError, KeyError, ValueError) as e:   # a wrong cell id, a missing field, an unreadable file
                    messenger.send("error: " + str(e).strip("'\""))
                except Exception:                          # anything else: report it, but the kernel and its variables live on
                    messenger.send("error inside the notebook kernel (the variables are kept):\n" + traceback.format_exc())
            except (EOFError, OSError):                    # the messenger gave up and left: nothing to answer
                pass
            finally:
                messenger.close()
```

Points worth naming:

- **`while True` is the design.** One `accept()` at a time, one command each. The interpreter state between
  iterations is the state your cells share.
- **The two `except` clauses are the safety net**: a `LookupError` (bad cell id) or a `KeyError` (missing field)
  or `ValueError` (unreadable file) is answered as `error: ...`, and *any* other exception is answered with the
  full traceback and prefixed "the variables are kept". An engine bug therefore never kills the user's session.
- The **`.json` sidecar** next to the socket is the only way `client.py` can find the pid to send SIGINT — a
  socket file gives you no pid.
- A **stale socket file** from a crashed kernel is removed before binding, which is why a killed kernel does not
  block the next `nb_open`.
- On `close` the loop breaks, `os.remove(address + ".json")` runs (`kernel.py:379`), and the `Listener` removes
  the socket. That is what `client.close` waits for.

## B6. The nine tools the model actually calls

Each `tools/notebook/nb_*.py` is ~15 lines: a `run()` that forwards to `_notebook.call`, and a `TOOL` dict the
model sees (name, description, JSON schema). The folder layout is only for humans; `agent.py:34-49` loads every
`*.py` that does not start with `_` and registers `TOOL["name"]`, refusing two tools with the same name.

**`_notebook.py` is where the real host-side logic lives** (`tools/notebook/_notebook.py`):

```python
def call(cmd, notebook, **args):
    """send one command to the engine in the sandbox, for one notebook. returns the answer as text"""
    if not os.path.isfile(os.path.join(sandbox.engine_dir(), "client.py")):   # checked on your machine, before the sandbox
        return ("the notebook engine is missing: ...")
    parts = notebook.replace("\\", "/").split("/")
    if not notebook.endswith(".ipynb") or notebook.startswith("/") or ".." in parts:
        return "the notebook must be a path ending in .ipynb, like common/analysis.ipynb, with no .. in it"
    folders = [sandbox.COMMON]
    allowed = sandbox.COMMON + "/..."
    if sandbox.my_project:
        folders.append(sandbox.my_project)
        allowed += " or " + sandbox.my_project + "/..."
    if len(parts) < 2 or parts[0] not in folders:           # anywhere else it would be gone when the sandbox stops
        return "a notebook must be in a folder the user keeps: " + allowed + ...
    same = os.path.normpath(notebook).lower()               # a/./b.ipynb is a/b.ipynb, and on mac and windows B.ipynb is b.ipynb
    lock = "notebook-" + hashlib.md5(same.encode()).hexdigest()[:12]   # one lock per notebook.
    had_it = lock in locks.held                             # this instance has it open already
    if cmd in ("create", "open") and not locks.take(lock):
        return notebook + " is open in another running instance. ..."
    answer = send(cmd, notebook, args)
    if cmd in ("create", "open"):
        opened = answer.startswith("created ") or answer.startswith("opened ") or answer.startswith(notebook + " was already open")
        if not opened and not had_it:                             # it didn't open (no sandbox, no such file, ...): the lock goes again
            locks.release(lock)
    if cmd == "close":
        locks.release(lock)
    return answer

def send(cmd, notebook, args):
    command = dict(args, cmd=cmd, notebook=notebook, timeout=MAX_TOOL_TIMEOUT - 30)
    payload = base64.b64encode(json.dumps(command).encode()).decode()
    answer = sandbox.exec("python3 -B /workspace/" + sandbox.ENGINE + "/client.py " + payload)
    if "python3: command not found" in answer:
        return "this sandbox has no python3, so notebooks don't work in it. ..."
    return answer
```

Four things this file does that no other layer does:

1. **Early, cheap checks on the host.** Is the engine present? Is the path a `.ipynb`? Is it under `common/` or
   the project? A wrong path is refused in microseconds instead of becoming an obscure `podman exec` error.
   The reason for the folder rule is stated right there: "anywhere else it would be gone when the sandbox stops".
2. **Base64.** `json.dumps` → `base64` → one command-line argument of letters and digits only, so cell source
   containing `"`, `$`, backticks or newlines cannot be reinterpreted by bash. This is why the source can be
   passed at all.
3. **The inter-instance lock** (`locks.py`): `notebook-<md5 of the normalised path>` — lowercased because on
   macOS and Windows `B.ipynb` and `b.ipynb` are the same file. If the user runs `main.py` twice and both work
   in the same notebook, the two sandboxes would both write it. One lock, taken on `create`/`open`, released on
   `close`. The subtle part: if the open *failed* (no sandbox, no file) the lock is released again — unless this
   instance already held it before the call (`had_it`), in which case it is a keep.
4. **`timeout = MAX_TOOL_TIMEOUT - 30`** — see B3: the kernel stops an over-long cell before the sandbox kills
   the whole command.

Now the tools themselves, one line each, plus what they return:

| Tool | Arguments | What it does | What comes back |
|---|---|---|---|
| `nb_create` | `path` | create + open with a fresh kernel | `created <nb> and started its kernel (no variables yet)` / `open notebooks now: ...`, then the view (a new notebook: one header line, `0 cells`) |
| `nb_open` | `path` | open existing; keep the kernel if already open | `opened <nb> with a fresh kernel: ...` or `<nb> was already open, its variables are kept`, then **the whole notebook** (it sends `show`) |
| `nb_close` | `path` | stop the kernel, keep the file | `closed <nb>: its variables are gone, the file stays` / `open notebooks now: ...` |
| `nb_add` | `path`, `source`, `kind="code"`, `after=None`, `run=False` | insert a cell (end, or after `after`) | `added cell <id>` (+ `>>> output:` + output if run) + overview |
| `nb_edit` | `path`, `cell_id`, `source`, `run=False` | replace the whole source | `edited cell <id>` (+ output) + overview |
| `nb_remove` | `path`, `cell_id` | delete the cell | `removed cell <id> (variables it made stay until the kernel restarts)` + overview |
| `nb_run` | `path`, `cell_ids` (list, or a single string — `nb_run.py:4` wraps it) | run in this order | `--- <id> ---` blocks + outputs, + overview |
| `nb_show` | `path` | nothing changes | full notebook: outline + every cell with source and output |
| `nb_rerun` | `path` | fresh kernel + every code cell | `fresh kernel (all old variables gone), every code cell run from the top:` + outputs + overview |

Two gotchas visible only in the code:

- **`nb_run` accepts one id as a string** (`tools/notebook/nb_run.py:4-5`) — models routinely pass a string
  where the schema says array, and this turns that into a working call instead of an error.
- **`nb_add`/`nb_edit` with `run=True` put the output inline**, prefixed `>>> output:`, rather than as a
  separate `--- id ---` block. Cheaper for the model: add-and-run is one call, and the output arrives attached
  to the thing that produced it.

## B7. The rules the model is told to follow (`Skills/notebook/SKILL.md`)

The tools are mechanical; the *habits* are in the skill, which the model loads with `load_skill` before working
in a notebook. Each rule exists because of something the engine cannot enforce:

- **"A sandbox must be running, one whose Containerfile has python3"** (`SKILL.md:17`) — the engine is stdlib
  only, but it needs an interpreter. A bare `ubuntu` sandbox has none, and the tool's answer already says so
  (`_notebook.py:54`).
- **"Mount the project BEFORE you open notebooks"** (`SKILL.md:18`) — `mount_project`/`unmount_project`
  *restart the sandbox*, and a restart kills every kernel. Variables gone.
- **"Make the first cell a markdown cell with the goal, the plan and what is done"** (`SKILL.md:23`) — because
  `outline()` shows the first line of each cell: the goal becomes the first line of the overview, the working
  table of contents, at zero cost. And it is for the user, who opens the file later.
- **"One step per cell, small enough to check its output ... then read the output before the next step"**
  (`SKILL.md:24`) — the outputs are the feedback loop; a cell doing five things hides which one broke.
- **"A cell fails: fix that same cell with `nb_edit` and run true. Do not add a new cell for the fix"**
  (`SKILL.md:25`) — otherwise a notebook accumulates broken `cell2_fixed`, `cell2_fixed2` and stops being
  rerunnable.
- **"When you are done: `nb_rerun`"** (`SKILL.md:27`) — a notebook whose cells only work *in the order you
  happened to run them*, with variables that no longer come from any cell, is worthless to the user. `nb_rerun`
  is a fresh kernel plus every cell from the top, i.e. the proof that the file stands on its own.
- **"`nb_close` when done: every open notebook uses memory in the sandbox"** (`SKILL.md:63`) — each kernel is a
  Python process holding its dataframes, inside a container with `SANDBOX_MEMORY = 2g`
  (`config.py:48`). Two forgotten notebooks can be the difference between a pandas job that fits and an OOM kill.
- **"After `nb_open`, outputs in the file are from earlier runs"** (`SKILL.md:48`) — the `old output, not run in
  this kernel` state; the variables behind those outputs do not exist, and relying on them produces
  `NameError`s the model will misdiagnose.
- **"`nb_edit` replaces the whole code; call `nb_show` first if you have not seen the full code"**
  (`SKILL.md:40`) — because the overview shows only the first 60 characters. Editing blind deletes the user's
  code.
- **"Calls for the same notebook in one reply may run in any order"** (`SKILL.md:57`) — the harness runs tool
  calls of one reply in parallel threads (`agent.py:259`), and the order in which they reach the kernel is not
  guaranteed. Hence: separate replies when order matters, or one `nb_run` with several ids, which *is* ordered.
- **"A cell that runs too long is stopped and the variables are kept"** (`SKILL.md:60`) — the SIGINT ladder in
  B4, described to the model so it knows to split long work into cells instead of writing one 20-minute script.

## B8. One worked example (reconstructed from the code)

Everything below is built from the actual format strings in `kernel.py`, `client.py` and `_notebook.py`; no
engine was run to produce it. Note the exact spacing in the overview: `"  " + number + ". " + id + "  " +
status + "  | " + first line` (`kernel.py:244`).

**1. `nb_create(path="common/sales.ipynb")`** — the tool starts a kernel; the kernel creates the empty file,
`prepare` returns "created ...", and `main` appends the answer to `show` (`client.py:180`):

```
created common/sales.ipynb and started its kernel (no variables yet)
open notebooks now: common/sales.ipynb

common/sales.ipynb: 0 cells
```

**2. `nb_add(path, kind="markdown", source="## Goal\n- revenue per month from sales.csv\n- then a bar chart")`**

```
added cell 7b2c9e10

common/sales.ipynb: 1 cells
  1. 7b2c9e10  markdown  | ## Goal
```

**3. `nb_add(path, source="import csv\nrows = [(\"jan\", 3, 10.0), (\"feb\", 5, 12.0)]\nrevenue = [(m, u * p) for m, u, p in rows]\nsum(r for _, r in revenue)", run=True)`**
— the last line is a bare expression, so `execute`'s `ast` trick evaluates it and makes it an `execute_result`:

```
added cell 3f9a1c0b
>>> output:
90.0

common/sales.ipynb: 2 cells
  1. 7b2c9e10  markdown  | ## Goal
  2. 3f9a1c0b  ran [1]  | import csv
```

**4. `nb_add(path, source="revenue", run=True)`** — `revenue` exists because the kernel kept it:

```
added cell a91d4e07
>>> output:
[('jan', 30.0), ('feb', 60.0)]

common/sales.ipynb: 3 cells
  1. 7b2c9e10  markdown  | ## Goal
  2. 3f9a1c0b  ran [1]  | import csv
  3. a91d4e07  ran [2]  | revenue
```

**5. `nb_edit(path, cell_id="3f9a1c0b", source=<the same code with 12.0 replaced by 11.0>, run=False)`** — the
source changes, the output does not, so the state flips to EDITED:

```
edited cell 3f9a1c0b

common/sales.ipynb: 3 cells
  1. 7b2c9e10  markdown  | ## Goal
  2. 3f9a1c0b  ran [1], EDITED since, output is stale  | import csv
  3. a91d4e07  ran [2]  | revenue
```

**6. `nb_run(path, cell_ids=["3f9a1c0b", "a91d4e07"])`** — in this order, `---` blocks, counts continue:

```
--- 3f9a1c0b ---
85.0
--- a91d4e07 ---
[('jan', 30.0), ('feb', 55.0)]

common/sales.ipynb: 3 cells
  1. 7b2c9e10  markdown  | ## Goal
  2. 3f9a1c0b  ran [3]  | import csv
  3. a91d4e07  ran [4]  | revenue
```

**7. If the cell had raised**, the same call would return the trimmed traceback and the run would stop:

```
--- 3f9a1c0b ---
Traceback (most recent call last):
  File "<cell 3f9a1c0b>", line 2, in <module>
NameError: name 'csv2' is not defined
(stopped at this error)
```

and the overview would show `2. 3f9a1c0b  ran [5], error`. Note `File "<cell 3f9a1c0b>"` — the fake filename is
the cell id (`kernel.py:58`), which is how a traceback in the notebook is traceable back to the cell.

**8. `nb_show(path)`** — the outline, then everything (`kernel.py:247`):

```
common/sales.ipynb: 3 cells
  1. 7b2c9e10  markdown  | ## Goal
  2. 3f9a1c0b  ran [3]  | import csv
  3. a91d4e07  ran [4]  | revenue

--- 1. 7b2c9e10 (markdown) ---
## Goal
- revenue per month from sales.csv
- then a bar chart

--- 2. 3f9a1c0b (ran [3]) ---
import csv
rows = [("jan", 3, 10.0), ("feb", 5, 11.0)]
revenue = [(m, u * p) for m, u, p in rows]
sum(r for _, r in revenue)

>>> output:
85.0

--- 3. a91d4e07 (ran [4]) ---
revenue

>>> output:
[('jan', 30.0), ('feb', 55.0)]
```

**9. `nb_close(path)`**

```
closed common/sales.ipynb: its variables are gone, the file stays
open notebooks now: none
```

The file on disk at that moment has three cells, the last outputs, `execution_count` 3 and 4 on the two code
cells, and the ids — so the user opens it in Jupyter and sees exactly what the model saw, minus the variables.

---

## What to remember

- **Part A**: a tool result over 8,000 characters becomes `results/NNNNNN-tool.txt`; the model sees a header, 40
  lines, `...`, 20 lines; `read_result` pages (200 lines / 6,000 chars / 1,000 per line), `search_result` greps
  (50 hits, case-insensitive, `re.escape` unless `regex`), `copy_result` copies into `common/` so real code can
  work on it. Later, old results become one-line pointers. Nothing is ever lost, only moved.
- **Part B**: one `kernel.py` per open notebook lives in the container and holds everything; one `client.py` per
  tool call carries one base64 command and prints one text answer; the `.ipynb` file is rewritten atomically
  after every change; the overview line (`id`, state `ran [n]` / `not run` / `old output, not run in this
  kernel` / `EDITED since, output is stale` / `error`, first line) is the model's map; and every rule in
  `SKILL.md` exists because the engine cannot enforce it.
