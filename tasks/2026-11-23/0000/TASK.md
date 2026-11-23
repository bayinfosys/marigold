# The process in tasks/README.md

tasks/README.md describes the whole process in one place: the workplan
and task files, how a patch is written and committed, how branches are
named, how a workplan is merged, and how several developers share the
work.

- Patches: output.patch is plain `git diff` output, built against the
  pushed head of the workplan branch and applied with `git apply`.
  A patch that fails `git apply --check` is regenerated, not merged by
  hand. New documents, such as task files, are delivered as files, not
  patches.
- Commits: COMMIT_MSG holds one line, the task id then what the change
  does (`2026-11-23/0004 Include the loader's exception in ...`). The
  maintainer commits it with `git commit -F`. A change that needs a
  second line is two tasks.
- Review: NOTES.md beside a task holds review questions and answers.
  A task is committed when it is agreed, and refined until then.
- The patch loop: once a task is agreed, its patch is generated,
  applied and read as a diff; a wrong diff is reverted with
  `git apply -R`, the task or breakdown adjusted, and the patch
  generated again. Changes outside the task go into the backlog in
  TODO.md.
- Branches: a workplan branch is `<date>-workplan`; a task worked on its
  own branch is `<date>-<nnnn>`. A branch that names no directory in
  tasks/ has no recorded intent. Merged branches are deleted.
- Merging: a workplan is squash-merged into master once its tasks and
  OUTCOME.md are committed and the integration cycle has passed. The
  message keeps the task commit subjects and ends with a
  `Workplan: tasks/<date>/WORKPLAN.md` trailer. The tasks/<date>/
  directory stays in master as the record of the work.
- Keeping current: fetch before starting; when master moves, the
  workplan's owner rebases its branch onto it.
- Several developers: each workplan has one owner; tasks whose files do
  not overlap run in parallel on task branches; pushing a task branch
  claims the task, and the first push stands.

Effects:

- a developer or an agent joining the work reads one file
- the repository records the intent of each branch and commit, as well
  as the change
