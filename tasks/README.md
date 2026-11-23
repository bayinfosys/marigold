# Tasks

Work on this repository is planned and recorded here. A workplan
breaks one goal into tasks, and each task is one commit. This file is
the whole process: the files, the steps, the branches, the merge and
how several developers share the work.

## Layout

    tasks/
      scripts/
        task.sh
      <date>/
        WORKPLAN.md
        OUTCOME.md
        SQUASH_COMMIT_MSG
        0000/
          TASK.md
          BREAKDOWN.md
          NOTES.md
          output.patch
          COMMIT_MSG
        0001/
          ...

`<date>` is the day the workplan was agreed. Tasks are numbered in the
order they are applied.

## Files

`WORKPLAN.md` holds the goal, the context needed to work in the code,
the findings that explain why the work is needed, and the tasks in
order with their dependencies. It is the current accepted plan and is
edited as the plan changes.

`TASK.md` states one change and its effects. A task changes marigold:
its code, its documentation or its build. It touches this repository
only and needs no further decisions before work starts. Changes to this
process, this file and tasks/scripts/, are committed directly, outside
any workplan.

`BREAKDOWN.md` lists the steps that make the change, in order. A task
that changes what an operator or a client sees ends with a step that
updates the documents affected.

`NOTES.md` holds the review questions about a task and their answers,
beside the task they shaped.

`output.patch` is the change, as plain `git diff` output, built against
the pushed head of the workplan branch and applied with `git apply`. A
patch that fails `git apply --check` is regenerated against the current
head, not merged by hand. New documents, such as task files, are
delivered as files, not patches.

output.patch, COMMIT_MSG and SQUASH_COMMIT_MSG are working files.
.gitignore ignores them, and git history records what they held.

`COMMIT_MSG` is the task's commit message: one line, the task id and
then what the change does.

    2026-11-23/0004 Include the loader's exception in ModelNotFoundError's message

A change that needs a second line to describe is two tasks.

`SQUASH_COMMIT_MSG` is the workplan's squash-merge message, written
after OUTCOME.md, as Merging describes.

`OUTCOME.md` is written once every task has been applied and run. It
records each finding and what now addresses it, how the work was
checked, where a task departed from its breakdown, and anything left
for a later workplan.

## Steps

1. Agree the workplan, and commit it on a new workplan branch.
2. Write the task files. Commit each task when it is agreed, and refine
   the others, in discussion or in their NOTES.md, until they are.
3. For each task in order: confirm the tasks it depends on have landed
   and the code is in the state the task expects; run the patch loop
   below until the diff is right; run it; accept it with
   `tasks/scripts/task.sh accept <nnnn>`; push.
4. Run the integration cycle, then write OUTCOME.md and commit it.
5. Review the workplan as a whole, and write SQUASH_COMMIT_MSG.
6. Squash-merge to master with `tasks/scripts/task.sh merge <date>`.

The maintainer authors every commit.

## The patch loop

Once a task and its breakdown are agreed, generating its patch is the
engineering loop:

1. Generate output.patch and COMMIT_MSG from TASK.md and BREAKDOWN.md,
   against the pushed head.
2. `task.sh apply <nnnn>` stages the patch, and `task.sh diff <nnnn>`
   shows it; `task.sh view <nnnn>` prints COMMIT_MSG.
3. If the diff is wrong, `task.sh reject <nnnn>` takes it out of the
   tree; adjust TASK.md or BREAKDOWN.md, and generate again.
4. When the diff is right, `task.sh accept <nnnn>` commits it with
   COMMIT_MSG.

task.sh takes `<date>/<nnnn>`, or `<nnnn>` in the newest workplan.

A change the patch would need outside its task, such as an
architectural change, a refactoring or an unrelated fix, is raised for
a later workplan, not put into the patch.

## Branches

| Branch | Holds | Created from | Merged into |
|---|---|---|---|
| `master` | integrated, tested code; one commit per workplan | -- | -- |
| `<date>-workplan` | one workplan: its files and one commit per task | master | master, squashed |
| `<date>-<nnnn>` | one task, worked apart from its workplan branch | `<date>-workplan` | `<date>-workplan` |

Task branches are needed only when several people work on one workplan
at once; a single developer commits tasks directly to the workplan
branch.

A branch whose name matches no directory in tasks/ has no recorded
intent. Merged branches are deleted, locally and on origin.

## Merging

A workplan is squash-merged into master once its tasks and OUTCOME.md
are committed and the integration cycle has passed on its branch.
SQUASH_COMMIT_MSG holds the message: the workplan's goal in one line, a
paragraph summarising what changed, the task commit subjects in order,
and a trailer naming the workplan:

    2026-11-23 Settings as arguments, declared code layers

    Model settings reach each loader and handler as a ModelSettings
    argument, and no setting passes through the process environment.
    ...

    2026-11-23/0002 Describe [environment] as compose variables
    2026-11-23/0003 Reject [environment] keys the platform sets
    ...

    Workplan: tasks/2026-11-23/WORKPLAN.md

The task lines come from the branch:

    git log --reverse --format=%s master..<date>-workplan | grep '^<date>/'

`task.sh merge <date>` squashes `<date>-workplan` into master with
SQUASH_COMMIT_MSG; TASK_MAIN_BRANCH names another main branch.

The tasks/<date>/ directory stays in master as the record of the work.
`git log --format='%h %s %(trailers:key=Workplan,valueonly)'` lists the
workplan behind each commit on master.

## Working together

- Fetch before starting work: `git fetch --prune`.
- Each workplan has one owner. When master moves while a workplan is
  open, the owner rebases its branch onto `origin/master` and pushes;
  task branches rebase onto the workplan branch the same way.
- Tasks whose files do not overlap can run in parallel on task
  branches; tasks that share files run in order.
- Pushing a task branch claims the task. When two people claim the
  same task, the first push stands.
- Suggested settings: `git config pull.rebase true`,
  `git config rebase.autoStash true`, `git config fetch.prune true`.

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
