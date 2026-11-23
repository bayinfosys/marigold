#!/bin/bash
# tasks/scripts/task.sh -- work with a task's patch, merge a workplan, route a commit.
#
#   task.sh apply  [ID/]NNNN   update the tree and the index with the patch
#   task.sh diff   [ID/]NNNN   show the changes: staged if applied, else the patch
#   task.sh accept [ID/]NNNN   apply if needed, then commit with COMMIT_MSG
#   task.sh reject [ID/]NNNN   take an applied, uncommitted patch out of the tree and the index
#   task.sh view   [ID/]NNNN   print COMMIT_MSG
#   task.sh merge  [ID]        squash workplan/ID/root into the main branch with SQUASH_COMMIT_MSG
#   task.sh route  [REV]       print the next step for a commit (default HEAD)
#   task.sh install            run tasks/scripts/hooks in this clone
#
# ID is a workplan's directory under tasks/. It defaults to the workplan
# of the current branch (workplan/ID/root or workplan/ID/task/NNNN), then
# to the newest dated workplan.
# TASK_MAIN_BRANCH names the main branch; it defaults to master.
set -euo pipefail

MAIN=${TASK_MAIN_BRANCH:-master}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

die()   { echo "$0: $*" >&2; exit 1; }
usage() { echo "usage: $0 apply|diff|accept|reject|view [ID/]NNNN | merge [ID] | route [REV] | install" >&2; exit 2; }
need()  { [ -f "$1" ] || die "$1: not found"; }

# The workplan of the current branch, else the newest dated workplan.
current() {
  local branch
  branch=$(git rev-parse --abbrev-ref HEAD)
  if [[ $branch =~ ^workplan/([^/]+)/ ]]; then
    echo "${BASH_REMATCH[1]}"
    return
  fi
  shopt -s nullglob
  local plans=(tasks/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9])
  shopt -u nullglob
  [ ${#plans[@]} -gt 0 ] || die "no workplan for branch $branch, and no dated workplan under tasks/"
  basename "${plans[-1]}"
}

[ $# -ge 1 ] || usage
CMD=$1
ARG=${2:-}

cd "$(git rev-parse --show-toplevel)"

case $CMD in
  route)
    [ $# -le 2 ] || usage
    exec python3 "$HERE/route.py" "${ARG:-HEAD}"
    ;;
  install)
    [ $# -eq 1 ] || usage
    previous=$(git config --get core.hooksPath || true)
    git config core.hooksPath tasks/scripts/hooks
    echo "core.hooksPath: ${previous:-(unset)} -> tasks/scripts/hooks"
    exit 0
    ;;
  merge)
    [ $# -le 2 ] || usage
    ID=${ARG:-$(current)}
    DIR=tasks/$ID
    [ -d "$DIR" ] || die "workplan $ID does not exist"
    ;;
  apply|diff|accept|reject|view)
    [ $# -eq 2 ] || usage
    case $ARG in
      */*) DIR=tasks/$ARG ;;
      *)   DIR=tasks/$(current)/$ARG ;;
    esac
    [ -d "$DIR" ] || die "task ${DIR#tasks/} does not exist"
    PATCH=$DIR/output.patch
    MSG=$DIR/COMMIT_MSG
    ;;
  *)
    usage
    ;;
esac

# True when the index holds the whole patch.
applied() { git apply --cached -R --check "$PATCH" 2>/dev/null; }

apply_patch() {
  if applied; then
    echo "$PATCH: already applied" >&2
    return 0
  fi
  git apply --index "$PATCH"
  git diff --cached --stat
}

reject_patch() {
  applied || die "$PATCH: not applied"
  git apply --index -R --check "$PATCH" 2>/dev/null || {
    echo "$PATCH: the tree has edits to the patch's files; restore them first:" >&2
    git diff --stat >&2
    exit 1
  }
  git apply --index -R "$PATCH"
  echo "$PATCH: rejected"
}

merge_workplan() {
  local branch=workplan/$ID/root
  local msg=$DIR/SQUASH_COMMIT_MSG
  need "$msg"
  git rev-parse --verify -q "refs/heads/$branch" >/dev/null || die "branch $branch does not exist"
  git diff --quiet && git diff --cached --quiet || die "the tree has uncommitted changes"
  git switch "$MAIN"
  git merge --squash "$branch"
  git commit -F "$msg"
}

case $CMD in
  apply)
    need "$PATCH"
    apply_patch
    ;;
  diff)
    need "$PATCH"
    if applied; then
      git diff --cached
    else
      git apply --stat "$PATCH"
      ${PAGER:-less} "$PATCH"
    fi
    ;;
  accept)
    need "$PATCH"
    need "$MSG"
    apply_patch
    git commit -F "$MSG"
    ;;
  reject)
    need "$PATCH"
    reject_patch
    ;;
  view)
    need "$MSG"
    cat "$MSG"
    ;;
  merge)
    merge_workplan
    ;;
esac
