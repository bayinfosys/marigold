"""tasks/scripts/task.py -- the commands of the task process.

    task.py status [ID | ID/NNNN | NNNN]   where a workplan or a task stands
    task.py apply  [ID/]NNNN   stage the patch in the tree and the index
    task.py diff   [ID/]NNNN   the staged change if applied, else the patch
    task.py accept [ID/]NNNN   apply if needed, then commit with COMMIT_MSG
    task.py reject [ID/]NNNN   take an applied, uncommitted patch back out
    task.py view   [ID/]NNNN   print COMMIT_MSG
    task.py merge  [ID]        squash workplan/ID/root into the main branch
    task.py route  [REV]       the next step after a commit (default HEAD)
    task.py install            run tasks/scripts/hooks in this clone

A workplan's id is its directory under tasks/, and a task's id is its
path below tasks/: tasks/2026-11-24/0001 is task 2026-11-24/0001 of
workplan 2026-11-24. Branches follow the same tree, workplan/<id>/root
and workplan/<id>/task/<nnnn>, and a task's commit subject starts with
its id. With no workplan given, the workplan is the current branch's,
else the newest dated directory under tasks/.

Environment:

    TASK_MAIN_BRANCH          the main branch (default master)
    TASK_CLASSIFIER           rules (default) or marigold, for route
    TASK_CLASSIFIER_MODEL     the model route asks, with marigold
    TASK_CLASSIFIER_TIMEOUT   seconds (default 120)
    MARIGOLD_API_BASE         default http://localhost:8000

Standard library only.
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import urllib.request
from pathlib import Path

MAIN = os.environ.get("TASK_MAIN_BRANCH", "master")
TASKS = Path("tasks")

DATED = re.compile(r"\d{4}-\d{2}-\d{2}")
NNNN = re.compile(r"\d{4}")
LISTED = re.compile(r"^(\d{4})  ", re.M)          # a task line in WORKPLAN.md
DEPENDS = re.compile(r"^Depends on (.+)$", re.M)   # a dependency line in TASK.md
BRANCH = re.compile(r"workplan/([^/\s']+)/")


class Fail(Exception):
    """A command that cannot go on; main() prints it and exits 1."""


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------

def git(*args: str, input: str | None = None, show: bool = False) -> str:
    """Run git; return its output, or raise Fail with its error.

    With show, git writes to the terminal (its pager included) and
    nothing is returned.
    """
    result = subprocess.run(
        ["git", *args],
        text=True,
        input=input,
        capture_output=not show,
    )
    if result.returncode != 0:
        detail = "" if show else (result.stderr.strip() or result.stdout.strip())
        raise Fail(f"git {' '.join(args)} failed" + (f": {detail}" if detail else ""))
    return "" if show else result.stdout.strip()


def succeeds(*args: str) -> bool:
    """True when the git command exits 0."""
    return subprocess.run(["git", *args], capture_output=True).returncode == 0


def main_ref() -> str:
    """The main branch, locally if it exists there, else on origin."""
    for ref in (MAIN, f"origin/{MAIN}"):
        if succeeds("rev-parse", "--verify", "-q", ref):
            return ref
    raise Fail(f"no branch {MAIN}, locally or on origin")


def clean() -> bool:
    return succeeds("diff", "--quiet") and succeeds("diff", "--cached", "--quiet")


# ---------------------------------------------------------------------------
# workplans and tasks
# ---------------------------------------------------------------------------

def current_workplan() -> str:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if m := BRANCH.match(branch + "/"):
        return m[1]
    dated = sorted(p.name for p in TASKS.iterdir() if p.is_dir() and DATED.fullmatch(p.name))
    if not dated:
        raise Fail(f"no workplan for branch {branch}, and no dated workplan under tasks/")
    return dated[-1]


def workplan_id(arg: str | None) -> str:
    wid = arg or current_workplan()
    if not (TASKS / wid).is_dir():
        raise Fail(f"workplan {wid} does not exist")
    return wid


def task_id(arg: str) -> str:
    """ID/NNNN as given, or NNNN in the current workplan."""
    tid = arg if "/" in arg else f"{current_workplan()}/{arg}"
    if not NNNN.fullmatch(tid.split("/")[-1]) or tid.count("/") != 1:
        raise Fail(f"{arg}: a task id is <workplan>/<nnnn>, or <nnnn>")
    return tid


def listed(wid: str) -> set[str]:
    """The task numbers WORKPLAN.md lists."""
    plan = TASKS / wid / "WORKPLAN.md"
    return set(LISTED.findall(plan.read_text())) if plan.is_file() else set()


def workplan_tasks(wid: str) -> list[str]:
    """Every task WORKPLAN.md lists or tasks/<wid>/ holds."""
    dirs = {p.name for p in (TASKS / wid).iterdir() if p.is_dir() and NNNN.fullmatch(p.name)}
    return [f"{wid}/{n}" for n in sorted(listed(wid) | dirs)]


def commit_for(tid: str, ref: str) -> str:
    """The latest commit in ref's history whose message has a line
    starting with the task id: the task's commit, or the squash that
    lists it. Empty when there is none."""
    pattern = "^(\\+ )?" + tid.replace(".", "\\.") + " "
    return git("log", ref, "-E", f"--grep={pattern}", "--format=%h %s", "-n", "1")


def depends_on(tid: str) -> list[str]:
    """The tasks TASK.md names on its 'Depends on' line, in the same workplan."""
    task = TASKS / tid / "TASK.md"
    wid = tid.split("/")[0]
    if not task.is_file():
        return []
    return [
        f"{wid}/{n}"
        for line in DEPENDS.findall(task.read_text())
        for n in NNNN.findall(line)
    ]


def patch_applied(patch: Path) -> bool:
    """True when the index or the tree already holds the patch."""
    return succeeds("apply", "--cached", "-R", "--check", str(patch)) or succeeds(
        "apply", "-R", "--check", str(patch)
    )


def state(tid: str, seen: frozenset = frozenset()) -> tuple[str, str]:
    """A task's state and its detail: the commit, or the tasks waited on.

    merged       a commit on the main branch lists the task
    complete     a commit on the current branch is the task's
    testing      output.patch is in the index or the tree, uncommitted
    development  output.patch exists and would apply
    waiting      output.patch does not apply, and a task it depends on
                 is not committed
    stale        output.patch does not apply, and every task it depends
                 on is committed: regenerate it
    refinement   TASK.md exists, with no patch
    unspecified  WORKPLAN.md lists the task, with no directory
    unknown      neither the workplan nor tasks/ knows the task
    """
    for ref, name in ((main_ref(), "merged"), ("HEAD", "complete")):
        if commit := commit_for(tid, ref):
            return name, commit

    directory = TASKS / tid
    patch = directory / "output.patch"

    if patch.is_file():
        if patch_applied(patch):
            return "testing", ""
        if succeeds("apply", "--check", str(patch)):
            return "development", ""
        pending = [
            dep for dep in depends_on(tid)
            if dep not in seen and state(dep, seen | {tid})[0] not in ("merged", "complete")
        ]
        if pending:
            return "waiting", "on " + ", ".join(pending)
        return "stale", ""

    if (directory / "TASK.md").is_file():
        return "refinement", ""

    wid, nnnn = tid.split("/")
    if nnnn in listed(wid):
        return "unspecified", ""

    return "unknown", ""


def need(path: Path) -> Path:
    if not path.is_file():
        raise Fail(f"{path}: not found")
    return path


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_status(arg: str | None) -> None:
    if arg and ("/" in arg or NNNN.fullmatch(arg)):
        tids = [task_id(arg)]
    else:
        tids = workplan_tasks(workplan_id(arg))

    for tid in tids:
        name, commit = state(tid)
        print(f"{tid:<24} {name:<12} {commit}".rstrip())


def apply_patch(patch: Path) -> None:
    if patch_applied(patch):
        print(f"{patch}: already applied", file=sys.stderr)
        return
    git("apply", "--index", str(patch))
    git("diff", "--cached", "--stat", show=True)


def cmd_apply(arg: str) -> None:
    apply_patch(need(TASKS / task_id(arg) / "output.patch"))


def cmd_diff(arg: str) -> None:
    patch = need(TASKS / task_id(arg) / "output.patch")
    if patch_applied(patch):
        git("diff", "--cached", show=True)
    else:
        git("apply", "--stat", str(patch), show=True)
        subprocess.run([os.environ.get("PAGER", "less"), str(patch)])


def cmd_accept(arg: str) -> None:
    tid = task_id(arg)
    patch = need(TASKS / tid / "output.patch")
    msg = need(TASKS / tid / "COMMIT_MSG")

    lines = msg.read_text().strip().splitlines()
    if len(lines) != 1 or not lines[0].startswith(f"{tid} "):
        raise Fail(f"{msg}: one line, starting '{tid} '")

    name, commit = state(tid)
    if name in ("merged", "complete"):
        raise Fail(f"{tid} is {name}: {commit}")

    apply_patch(patch)
    git("commit", "-F", str(msg), show=True)


def cmd_reject(arg: str) -> None:
    patch = need(TASKS / task_id(arg) / "output.patch")
    if not patch_applied(patch):
        raise Fail(f"{patch}: not applied")
    if not succeeds("apply", "--index", "-R", "--check", str(patch)):
        git("diff", "--stat", show=True)
        raise Fail(f"{patch}: the tree has edits to the patch's files; restore them first")
    git("apply", "--index", "-R", str(patch))
    print(f"{patch}: rejected")


def cmd_view(arg: str) -> None:
    print(need(TASKS / task_id(arg) / "COMMIT_MSG").read_text(), end="")


def cmd_merge(arg: str | None) -> None:
    """Squash workplan/<id>/root into the main branch.

    Every task must be committed and OUTCOME.md committed on the branch.
    SQUASH_COMMIT_MSG holds the goal line and the summary; the task
    subjects and the Workplan trailer are added here, from the branch.
    """
    wid = workplan_id(arg)
    branch = f"workplan/{wid}/root"
    main = main_ref()

    if not succeeds("rev-parse", "--verify", "-q", f"refs/heads/{branch}"):
        raise Fail(f"branch {branch} does not exist")
    if not clean():
        raise Fail("the tree has uncommitted changes")

    open_tasks = [
        tid for tid in workplan_tasks(wid)
        if not (commit_for(tid, branch) or commit_for(tid, main))
    ]
    if open_tasks:
        raise Fail("not committed on " + branch + ": " + ", ".join(open_tasks))

    if not succeeds("cat-file", "-e", f"{branch}:tasks/{wid}/OUTCOME.md"):
        raise Fail(f"tasks/{wid}/OUTCOME.md is not committed on {branch}")

    head = need(TASKS / wid / "SQUASH_COMMIT_MSG").read_text().rstrip()
    if re.search(rf"^(\+ )?{re.escape(wid)}/\d{{4}} |^Workplan:", head, re.M):
        raise Fail("SQUASH_COMMIT_MSG holds the goal line and the summary only; "
                   "merge adds the task subjects and the Workplan trailer")

    subjects = [
        s for s in git("log", "--reverse", "--format=%s", f"{main}..{branch}").splitlines()
        if re.match(rf"{re.escape(wid)}/\d{{4}} ", s)
    ]
    if not subjects:
        raise Fail(f"no task commits on {branch} beyond {main}")

    message = f"{head}\n\n" + "\n".join(subjects) + f"\n\nWorkplan: tasks/{wid}/WORKPLAN.md\n"
    print(message)

    git("switch", MAIN, show=True)
    git("merge", "--squash", branch, show=True)
    git("commit", "-F", "-", input=message)
    print(git("log", "-1", "--format=%h %s"))


def cmd_install() -> None:
    previous = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"], capture_output=True, text=True
    ).stdout.strip()
    git("config", "core.hooksPath", "tasks/scripts/hooks")
    print(f"core.hooksPath: {previous or '(unset)'} -> tasks/scripts/hooks")


# ---------------------------------------------------------------------------
# route
# ---------------------------------------------------------------------------

ACTIONS = ("complete", "plan-tasks", "make-patch", "review", "none")

PLAN_PATH = re.compile(r"^tasks/([^/]+)/WORKPLAN\.md$")
TASK_PATH = re.compile(r"^tasks/([^/]+)/(\d{4})/(?:TASK|BREAKDOWN)\.md$")
TASK_SUBJECT = re.compile(r"^([^/\s]+)/(\d{4}) ")


def facts(rev: str) -> dict:
    """What a commit is: the branch, its parents, subject, trailer and paths."""
    parents = git("rev-list", "--parents", "-n", "1", rev).split()[1:]
    if len(parents) > 1:
        paths = git("diff", "--name-only", parents[0], rev).split()
    else:
        paths = git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", rev).split()

    return {
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "parents": len(parents),
        "subject": git("log", "-1", "--format=%s", rev),
        "workplan": git("log", "-1", "--format=%(trailers:key=Workplan,valueonly)", rev),
        "paths": paths,
    }


def candidates(f: dict) -> dict[str, list[str]]:
    """Each action the commit could lead to, with its targets."""
    found: dict[str, list[str]] = {}

    if f["branch"] == MAIN:
        if m := PLAN_PATH.match(f["workplan"]) or BRANCH.search(f["subject"]):
            found["complete"] = [m[1]]

    if plans := sorted({m[1] for p in f["paths"] if (m := PLAN_PATH.match(p))}):
        found["plan-tasks"] = plans

    if tasks := sorted({f"{m[1]}/{m[2]}" for p in f["paths"] if (m := TASK_PATH.match(p))}):
        found["make-patch"] = tasks

    m = TASK_SUBJECT.match(f["subject"])
    if m and any(not p.startswith("tasks/") for p in f["paths"]):
        found["review"] = [f"{m[1]}/{m[2]}"]

    return found


def classify(f: dict) -> str | None:
    """The action a model served by marigold picks, or None."""
    model = os.environ.get("TASK_CLASSIFIER_MODEL")
    if not model:
        print("route: TASK_CLASSIFIER_MODEL is not set", file=sys.stderr)
        return None

    base = os.environ.get("MARIGOLD_API_BASE", "http://localhost:8000").rstrip("/")
    timeout = float(os.environ.get("TASK_CLASSIFIER_TIMEOUT", "120"))
    paths = "\n".join(f["paths"][:50])

    prompt = (
        "A commit was made in a repository that plans work in tasks/.\n"
        "tasks/<id>/WORKPLAN.md is a workplan; tasks/<id>/<nnnn>/TASK.md and\n"
        "BREAKDOWN.md define a task; a commit whose subject starts <id>/<nnnn>\n"
        "is that task's change to the code; a commit on the main branch with a\n"
        "Workplan trailer completes a workplan.\n\n"
        "Actions:\n"
        "complete: a workplan reached the main branch\n"
        "plan-tasks: the workplan changed, so its tasks need refreshing\n"
        "make-patch: a task definition changed, so its patch needs generating\n"
        "review: code changed under a task, so it needs checking against the task\n"
        "none: nothing to do\n\n"
        f"Branch: {f['branch']}\n"
        f"Parents: {f['parents']}\n"
        f"Subject: {f['subject']}\n"
        f"Workplan trailer: {f['workplan'] or '(none)'}\n"
        f"Changed paths:\n{paths}\n\n"
        "Answer with the action's name only."
    )

    request = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 8,
        }).encode(),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = json.load(response)["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001 -- any failure falls back to the rules
        print(f"route: classifier failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None

    words = answer.strip().lower().split()
    choice = words[0].strip(".:`'\"") if words else ""
    if choice not in ACTIONS:
        print(f"route: classifier answered {answer!r}", file=sys.stderr)
        return None
    return choice


def cmd_route(rev: str | None) -> None:
    """Print the action and its targets. The targets come from the
    commit; the action from the rules, the first of ACTIONS that has
    targets, or from the classifier when TASK_CLASSIFIER=marigold."""
    f = facts(rev or "HEAD")
    found = candidates(f)
    rule = next((a for a in ACTIONS if a in found), "none")
    action, source = rule, "rules"

    if os.environ.get("TASK_CLASSIFIER", "rules") == "marigold":
        choice = classify(f)
        if choice == "none" or choice in found:
            action, source = choice, "marigold"
        elif choice:
            print(f"route: the classifier chose {choice}, which has no targets", file=sys.stderr)

    print(f"route: {source} chose {action}; the rules chose {rule}", file=sys.stderr)
    print(" ".join([action, *found.get(action, [])]))


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="task.py",
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    sub.add_parser("status", help="where a workplan or a task stands").add_argument("id", nargs="?")
    for name, text in (
        ("apply", "stage the patch in the tree and the index"),
        ("diff", "the staged change if applied, else the patch"),
        ("accept", "apply if needed, then commit with COMMIT_MSG"),
        ("reject", "take an applied, uncommitted patch back out"),
        ("view", "print COMMIT_MSG"),
    ):
        sub.add_parser(name, help=text).add_argument("task", metavar="[ID/]NNNN")
    sub.add_parser("merge", help="squash workplan/ID/root into the main branch").add_argument("id", nargs="?")
    sub.add_parser("route", help="the next step after a commit").add_argument("rev", nargs="?")
    sub.add_parser("install", help="run tasks/scripts/hooks in this clone")

    args = parser.parse_args()
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # quiet when piped to head

    try:
        os.chdir(git("rev-parse", "--show-toplevel"))
        match args.command:
            case "status":
                cmd_status(args.id)
            case "apply":
                cmd_apply(args.task)
            case "diff":
                cmd_diff(args.task)
            case "accept":
                cmd_accept(args.task)
            case "reject":
                cmd_reject(args.task)
            case "view":
                cmd_view(args.task)
            case "merge":
                cmd_merge(args.id)
            case "route":
                cmd_route(args.rev)
            case "install":
                cmd_install()
    except Fail as e:
        print(f"task: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
