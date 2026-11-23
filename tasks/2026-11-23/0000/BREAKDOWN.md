# Breakdown

1. Add COMMIT_MSG and NOTES.md to the layout and to Files, and describe
   output.patch as plain `git diff` output applied with `git apply`.
2. Rewrite Steps: agree the workplan; write and refine the task files,
   committing each when agreed; for each task, write the patch against
   the pushed head, review, apply, run, and commit with `git commit -F`;
   write OUTCOME.md; review; squash-merge.
3. Add a Branches section: the branch names, and deleting merged
   branches.
4. Add a Merging section: the squash commit's message and trailer, and
   the task directory staying in master.
5. Add a Working together section: fetching, rebasing onto master, one
   owner per workplan, parallel tasks and claiming them.
6. Add a Patch loop section: generate, apply, read the diff, revert and
   adjust the task, generate again; changes outside the task go into
   the backlog in TODO.md.
