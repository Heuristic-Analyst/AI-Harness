import re
from . import _results

MAX_HITS = 50                                                     # matching lines shown per call at most
MAX_CHARS = 6_000
HIT_CUT = 300                                                     # a matching line is shown up to this many characters

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
    hits = []
    size = 0
    count = 0
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
                line = line.rstrip("\n")
                entry = name + ":" + str(number) + ": " + (line[:HIT_CUT] + " ..." if len(line) > HIT_CUT else line)
                if size + len(entry) > MAX_CHARS:
                    continue
                hits.append(entry)
                size += len(entry) + 1
    if not count:
        return "no line contains '" + text + "'" + (" in " + file if file else " in your " + str(len(files)) + " result files")
    answer = format(count, ",") + " matching lines" + (", the first " + str(len(hits)) + " shown" if count > len(hits) else "")
    return answer + ". read_result with from_line shows what is around one:\n" + "\n".join(hits)

TOOL = {
    "name": "search_result",
    "description": "Find lines in your result files (tool results too long for your context, saved as results/...), like "
                   "grep: every matching line with its file and line number, at most " + str(MAX_HITS) + ". Then read_result "
                   "shows what is around a hit. Leave out file to search all your result files, your subagents' included.",
    "parameters": {"type": "object",
                   "properties": {"text": {"type": "string", "description": "what to look for. upper or lower case doesn't matter"},
                                  "file": {"type": "string", "description": "one file, e.g. results/000042-sandbox_shell.txt. "
                                           "leave out = all of them"},
                                  "regex": {"type": "boolean", "description": "true = text is a regular expression. default false"}},
                   "required": ["text"]},
}
