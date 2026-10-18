from . import _results

MAX_LINES = 200                                                   # lines per call at most
MAX_CHARS = 6_000                                                 # characters per call at most, so a read never floods the context
LINE_CUT = 1_000                                                  # a single longer line is cut here

def run(agent, file, from_line=1, lines=MAX_LINES):
    path = _results.resolve(agent, file)
    if not path:
        return _results.not_found(agent, file)
    start = max(1, int(from_line))
    count = max(1, min(int(lines), MAX_LINES))
    shown = []
    size = 0
    total = 0
    full = False
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
            shown.append(entry)
            size += len(entry) + 1
    if start > total:
        return file + " has " + format(total, ",") + " lines. from_line " + str(start) + " is past the end"
    last = start + len(shown) - 1
    answer = file + ": lines " + str(start) + "-" + str(last) + " of " + format(total, ",") + "\n" + "\n".join(shown)
    if last < total:
        answer += "\n(more: read_result with from_line=" + str(last + 1) + ")"
    return answer

TOOL = {
    "name": "read_result",
    "description": "Read part of one of your result files: tool results that were too long for your context are saved as "
                   "files (results/000042-sandbox_shell.txt), and you only saw their start and end. This shows the lines you "
                   "ask for, with line numbers: at most " + str(MAX_LINES) + " lines or " + format(MAX_CHARS, ",") + " characters "
                   "per call, like scrolling. In a big file, find the place with search_result first. Your subagents' result "
                   "files work too: agents/<its folder>/results/... (its folder is in its report).",
    "parameters": {"type": "object",
                   "properties": {"file": {"type": "string", "description": "e.g. results/000042-sandbox_shell.txt"},
                                  "from_line": {"type": "integer", "description": "the first line to show. default 1"},
                                  "lines": {"type": "integer", "description": "how many lines. default and at most " + str(MAX_LINES)}},
                   "required": ["file"]},
}
