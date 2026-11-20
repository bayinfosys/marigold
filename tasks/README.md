# Tasks

Work on this repository is planned and recorded here. A workplan
breaks one goal into tasks, and each task is one patch.

## Layout

    tasks/
      <date>/
        WORKPLAN.md
        OUTCOME.md
        0000/
          TASK.md
          BREAKDOWN.md
          output.patch
        0001/
          ...

`<date>` is the day the workplan was agreed. Tasks are numbered in the
order they are applied.

## Files

`WORKPLAN.md` holds the goal, the context needed to work in the code,
the findings that explain why the work is needed, and the tasks in
order with their dependencies. It is the current accepted plan and is
edited as the plan changes.

`TASK.md` states one change and its effects. A task touches this
repository only and needs no further decisions before work starts.

`BREAKDOWN.md` lists the steps that make the change, in order. A task
that changes what an operator or a client sees ends with a step that
updates the documents affected.

`output.patch` is the change, as `git format-patch` output, applied
with `git am`.

`OUTCOME.md` is written once every task has been applied and run. It
records each finding and what now addresses it, how the work was
checked, where a task departed from its breakdown, and anything left
for a later workplan.

## Steps

1. Agree the workplan and its tasks, and commit them.
2. For each task in order: confirm the tasks it depends on have landed
   and the code is in the state the task expects; write output.patch;
   review and apply it; run it; commit.
3. Write OUTCOME.md and commit it.
4. Review the workplan as a whole.
5. Squash-merge to master, with the workplan goal and the outcome as
   the message.

## Review

The review reads WORKPLAN.md, the task files, OUTCOME.md and the diff
of the workplan's commits, without the discussion that produced them,
and answers:

- does the diff reach the workplan goal?
- is OUTCOME.md true of the diff?
- does the diff hold to the principles below and to docs/principles.md?
- does the diff contain changes that no task accounts for?

## Principles

- the smallest possible change; when new functionality needs a lot of
  code, propose a refactoring that keeps the logic simple
- few CLI commands and parameters; two existing commands in preference
  to a new one
- no fallbacks or compatibility code; breaking changes are acceptable
- documentation changes with the code, in the same task
- every write goes through the maintainer: patches are reviewed and
  applied by hand
- no tests while interfaces are changing

docs/principles.md holds the principles of the platform itself.
