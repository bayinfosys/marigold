#!/bin/bash
# tasks/scripts/task.sh -- work with a task's patch, or merge a workplan.
#
#   task.sh apply  [DATE/]NNNN   update the tree and the index with the patch
#   task.sh diff   [DATE/]NNNN   show the changes: staged if applied, else the patch
#   task.sh accept [DATE/]NNNN   apply if needed, then commit with COMMIT_MSG
#   task.sh reject [DATE/]NNNN   take an applied, uncommitted patch out of the tree and the index
#   task.sh view   [DATE/]NNNN   print COMMIT_MSG
#   task.sh merge  [DATE]        squash DATE-workplan into the main branch with SQUASH_COMMIT_MSG
#
# DATE defaults to the newest workplan directory under tasks/.
# TASK_MAIN_BRANCH names the main branch; it defaults to master.
set -euo pipefail

MAIN=${TASK_MAIN_BRANCH:-master}

die()   { echo "$0: $*" >&2; exit 1; }
usage() { echo "usage: $0 apply|diff|accept|reject|view [DATE/]NNNN | merge [DATE]" >&2; exit 2; }
need()  { [ -f "$1" ] || die "$1: not found"; }

newest() {
  shopt -s nullglob
  local plans=(tasks/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9])
  shopt -u nullglob
  [ ${#plans[@]} -gt 0 ] || die "no workplan directories under tasks/"
  basename "${plans[-1]}"
}

[ $# -ge 1 ] || usage
CMD=$1
ARG=${2:-}

cd "$(git rev-parse --show-toplevel)"

case $CMD in
  merge)
    [ $# -le 2 ] || usage
    DATE=${ARG:-$(newest)}
    DIR=tasks/$DATE
    [ -d "$DIR" ] || die "workplan $DATE does not exist"
    ;;
  *)
    [ $# -eq 2 ] || usage
    case $ARG in
      */*) DIR=tasks/$ARG ;;
      *)   DIR=tasks/$(newest)/$ARG ;;
    esac
    [ -d "$DIR" ] || die "task ${DIR#tasks/} does not exist"
    PATCH=$DIR/output.patch
    MSG=$DIR/COMMIT_MSG
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
  local branch=$DATE-workplan
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
  *)
    usage
    ;;
esac
