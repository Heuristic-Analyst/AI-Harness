# every tool file has two things: run (what we execute) and TOOL (what the model sees).
# run always gets the calling agent as its first argument, then the arguments the model passed. ignore agent if you don't need it.

import sys
import subprocess

TIMEOUT = 5   # seconds. a safety net for large calculations like 9**9**9**9, not a setting

def run(agent, expression):
    if not set(expression) <= set("0123456789+-*/().% "):        # only digits and math symbols. never let a model run code.
        return "invalid expression"
    try:                                                          # in its own small python process: one that never ends can be killed
        done = subprocess.run([sys.executable, "-I", "-c", "print(eval(input()))"], input=expression + "\n",
                              capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:                             # e.g. 9**9**9**9: the process is stopped
        return "too big: no result after " + str(TIMEOUT) + " seconds"
    if done.returncode != 0:                                      # e.g. 1/0 -> "error: ZeroDivisionError: division by zero"
        lines = done.stderr.strip().splitlines()
        return "error: " + (lines[-1] if lines else "exit code " + str(done.returncode))
    return done.stdout.strip()

TOOL = {
    "name": "calculate",
    "description": "Evaluate a math expression, e.g. 2 * (3 + 4).",
    "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
}
