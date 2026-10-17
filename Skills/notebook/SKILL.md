---
name: notebook
description: Use when you work in a Jupyter notebook with the nb_* tools, for data analysis, step-by-step code, plots, or anything where variables should stay alive between steps.
---

# Notebooks

A notebook is a .ipynb file in the shared folder, made of cells. While it is open, a kernel runs in the sandbox and keeps every variable: what one cell creates, later cells can use. Every change is saved to the file right away, so the user can open it at any time.

## When to use one

- Exploring or analyzing data, building something step by step, making plots: use a notebook.
- A one-off command (install a package, list files, run a finished script): use sandbox_shell instead.

## Before you start

- A sandbox must be running. Call check_sandbox; if none runs, call open_sandbox. Notebooks need python3: the python sandbox has it, the plain ubuntu one does not.
- Never change or delete Notebooks/Engine/ in the shared folder. That is the program that runs the notebooks.

## How to work

1. Open the notebook: nb_create for a new one (e.g. analysis/sales.ipynb, missing folders are created), nb_open for an existing one.
2. Make the first cell a markdown cell with the goal, the plan and what is done. Update it with nb_edit whenever a step is finished or the plan changes. It is how you, and the user, see where the work stands.
3. One step per cell, small enough to check its output. Add it with nb_add and run true, then read the output before the next step.
4. A cell fails or is wrong: fix that same cell with nb_edit and run true. Do not add a new cell for the fix.
5. A quick look you don't need later (df.head(), a test print): run it in a cell, then remove that cell with nb_remove.
6. When you are done: nb_rerun, so you know the notebook works from top to bottom. Fix what fails, rerun again, update the first cell, then nb_close.
7. Tell the user where the notebook is: Shared/ plus its path, e.g. Shared/analysis/sales.ipynb.

## Reading the overview

Every answer ends with a list of all cells: id, state, first line. Always read it. Use the ids from it; they stay the same when cells move.

- ran [n]: ran in this kernel, n is the order of the runs. Fine.
- not run: never ran. Its variables don't exist yet.
- old output, not run in this kernel: the output is from an earlier session. Its variables don't exist yet; run it (or nb_rerun) before you rely on it.
- EDITED since, output is stale: the code changed after it ran. Run it again before you trust its output.
- error: it failed. Fix it before you go on.
- markdown: text, nothing to run.

A note "the notebook file was changed outside" means the user edited it. Read the overview again, and nb_show if you need the details. Never undo the user's changes.

## Good to know

- Calls for the same notebook in one reply may run in any order. When order matters, make one call per reply, or give nb_run several cell ids: they run in that order.
- Only a short part of a long output comes back to you. Print summaries (shape, head, totals), not whole tables.
- Plots are saved into the notebook by themselves. You get a note that there is a figure, not the picture.
- The kernel's working folder is the notebook's folder: relative paths start there. The shared folder is /workspace.
- input() does not work: there is no one to type.
- A cell that runs too long is stopped and the variables are kept. Split long work into smaller cells. For jobs that run for a long time, write a script and start it in the background with sandbox_shell.
- Packages: install them with sandbox_shell (pip install ...). That needs the internet, which only the user can turn on (/sandbox net on). After the install, import works in the open notebook.
- The kernel crashed (most often: out of memory) or the sandbox restarted: all variables are gone. nb_open the notebook, then nb_rerun, or run the cells you need.
- Every open notebook uses memory in the sandbox. Close the ones you are done with.
