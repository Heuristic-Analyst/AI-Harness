---
name: project-run
description: Use when the user wants a long project done in the background (a build, an analysis, research that takes hours), or asks about, answers, changes or pauses a project run.
---

# Project runs

A project run works on one project folder in the background, for hours or days, until its goal is met. The project is split into a graph of nodes: each node is one task, worked on in shifts by fresh agents, and a node that is too big splits into children. A scheduler (no model) starts the shifts. Everything is in files, in the project's .graph/ folder, so the run survives closing the chat, and even a crash.

Your part: set it up well with the user, start it, and later report on it, pass on answers and changes. You don't do the work of the run yourself.

## Before you start: get these right with the user

1. **The project.** check_projects lists them, create_project makes a new one. It must not be mounted while the run works on it: if your sandbox has it, unmount_project first.
2. **The goal.** What should exist at the end, in a few sentences. Not "improve the website" but "a search page for the recipes, with filters for time and diet".
3. **Done when.** 3 to 6 points someone can check: "tests pass", "report.md has a table per month", "≥95% of rows have a category". This is what the whole run is judged by, so it matters most. Vague points ("works well") make a run that never ends or ends too early.
4. **The budget.** Tokens for the whole run. Rough guide: a small tool 500,000 to 1,000,000, a bigger build or analysis 2,000,000 to 5,000,000. Say what it costs if the user doesn't know their price per token. Ask, don't guess.
5. **The sandbox.** The one whose Containerfile has what the work needs (check_sandbox). The network is off: if the work needs internet (installs, downloads), the user switches it on, or adds what's needed to the Containerfile.
6. **A plan (optional).** If you and the user already know the big parts, give them as plan: the first level of nodes, each with goal, why, done_when, budget and depends_on. Otherwise the root plans itself.

Repeat goal, done-when, budget and sandbox to the user in a few lines, and start only when they agree.

## Starting

start_run with project, goal, done_when, budget, sandbox_name (and plan). It runs in the background: tell the user they can close the chat, and that you can show the status any time.

## While it runs

- **Status:** run_status. Tell the user in a few lines: how far it is (which parts are done, which are running), the budget used, and any question. Don't paste the whole tree unless they ask.
- **Questions:** the root asks the user when it can't decide alone. run_status shows them. Pass the question on in plain words, and the user's answer with message_run. A run that waits for an answer stops; message_run starts it again.
- **Changes:** "add X", "drop Y", "do Z better": send it with message_run, in the user's words plus anything you know that helps. The root decides how: it reopens finished parts, adds nodes or cancels them. Works during the run and after it finished.
- **Pause:** pause_run. It stops after the shifts going on now. start_run goes on.
- **Out of budget:** when the root reports BLOCKED because of budget, tell the user what is done, what is missing, and what it says it would need. If they want to go on: message_run with extra_budget (the run must be stopped or paused), saying what to finish first.

## When it is finished

run_status shows the root's result: what was done, one answer per done-when point, and where the files are (the project folder, Shared/<project>/). Tell the user that in a few lines, and where to look.
