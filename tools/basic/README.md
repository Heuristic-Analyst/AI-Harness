# basic

Two small tools every agent can use.

| Tool | Who gets it | What it does |
|---|---|---|
| `calculate` | all | Evaluates a math expression, e.g. `2 * (3 + 4)`. |
| `load_skill` | every agent with skills | Returns a skill's full instructions. |

## calculate

- Only digits and math symbols are accepted (`0-9 + - * / ( ) . %` and spaces), so the model can never sneak code in.
- It runs in its own small Python process that is stopped after 5 seconds, so something huge like `9**9**9**9` can't hang the program.
- Errors come back as text, e.g. `error: ZeroDivisionError: division by zero`.

## load_skill

- The agent's system prompt only lists each skill's name and one-line description. `load_skill` returns the whole `SKILL.md`, and the agent then follows it.
- It only loads the skills this agent was given, by name. It never takes a file path from the model.
- Any agent with at least one skill gets this tool automatically.
- A skill that was deleted meanwhile (see [`../skills/`](../skills/)) gets a clear "no skill called ..." answer.
