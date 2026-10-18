# skills

Lets the agent write its own skills, improve them later, and delete them. It can only ever touch `Skills/Learned/`. Your skills, one level up in `Skills/`, are out of reach.

| Tool | Who gets it | What it does |
|---|---|---|
| `create_skill` | main only | Saves a new skill: a name, a one-line "Use when ..." description, and the instructions. |
| `edit_skill` | main only | Rewrites one of the agent's own skills. Keeps the description unless a new one is given. |
| `delete_skill` | main only | Deletes one of the agent's own skills. |

`_skillfile.py` holds what the three share: checking names, writing the file, and refreshing the skill list.

## How the agent knows a skill is editable

The tools write these, never the agent:

- `editable: yes` in the skill's header, plus `updated: <date>`
- a note at the top of the skill's text: `> Editable: you wrote this skill yourself...`
- an `[editable]` tag after the skill's name in the agent's skill list, which it always sees

What counts is the **folder**, not the header. A skill elsewhere that claims `editable: yes` is still yours and stays locked.

## Rules

- Names: lowercase letters, digits and hyphens, at most 40 characters, e.g. `clean-csv-files`. The name is also the folder name.
- A new skill can't take the name of an existing one. A learned skill with the same name as one of yours is ignored.
- The text may be at most 15,000 characters, because a skill is loaded whole into the conversation.
- A new or changed skill is usable at once, no restart needed. Other running instances see it from your next message there.
- `edit_skill` only saves if the skill is still as `load_skill` showed it. If another running instance (or you) changed it in between, it refuses, and the agent loads it again first. One instance at a time creates, edits or deletes a skill.
- Only the main agent gets these tools, like the memory tools.

## For you

- Keep a learned skill for good: move its folder from `Skills/Learned/` up into `Skills/`. From then on it is yours, and the agent can't change it.
- `Skills/Learned/README.md` explains the folder. Files lying directly in it are never read as skills, only `<name>/SKILL.md` folders.
- Look at `Skills/Learned/` now and then. These are instructions the agent wrote for its future self, and git shows you every change.
- Another folder name: change `LEARNED_SKILLS_DIR` in `config.py`.
