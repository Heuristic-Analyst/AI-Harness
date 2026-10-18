---
name: memory
description: Use when the user asks you to remember, forget or update something, or when you learn something about the user worth keeping for future conversations.
---

# Memory

Your memory is the file MEMORY.md. It is shown in your system prompt at the start of every conversation, so anything you save there, you will still know next time. You can only read and replace this one file.

## When to change it

- The user asks you to remember, save or note something: save it.
- The user asks you to forget something: remove it.
- Something you saved turns out to be wrong or outdated: fix or remove it.
- You learn something lasting and useful on your own (their name, preferences, how they like answers, ongoing projects, decisions): if it is clearly useful, save it and tell the user in one short sentence. If you are not sure it is worth keeping, ask first, e.g. "Should I remember that you prefer short answers?"

Do not save:
- details that only matter for the current task
- things that are only true today
- your own guesses about the user
- sensitive things (health, money, passwords, private details about other people), unless the user explicitly asks you to

## How to change it

1. Call read_memory. Always, even if you think you know what is in it: the copy in your system prompt can be outdated.
2. Write the complete new file: keep every entry that is still true, then add, change or remove what is needed.
3. Call write_memory with the WHOLE new file. Anything you leave out is deleted.
   If it says the file changed since you read it: another instance (the user can run several at once) or the user saved something in between. Start again at step 1, so their change stays.
4. Tell the user in one short sentence what you saved, changed or removed.

## Format

Always keep this structure. Sections may be empty.

```
# Memory

## User
- who the user is: name, language, background

## Preferences
- how they like things done

## Projects
- what they are working on

## Notes
- anything else worth keeping
```

Rules:
- one fact per line, as a short bullet
- no duplicates: if a fact changes, update its line instead of adding a new one
- keep it small: the whole file is sent with every request. merge similar lines, drop what stopped being useful
