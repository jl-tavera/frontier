#!/usr/bin/env python3
"""Run /build <n> auto for each ticket, each in its own git worktree, up to four at a time.

    python autopilot.py              every open `ready-for-agent` ticket
    python autopilot.py 51-55 58     a range and/or single numbers
    python autopilot.py --max 3 ...  at most three tickets
    python autopilot.py --serial ... one ticket at a time

Run it from the project's root. Each ticket gets a worktree at <root>-worktrees/<n>, cut from the
freshly fetched remote default branch, and a fresh `claude -p` session there with CLAUDE_AUTOPILOT=1
in its env -- the only thing that lets tap-approval.py start /ship without a tap, and something the
model inside cannot set for itself. The session loads user and local settings only, so only the
user-level hooks guard it (see run()). Prints one line per milestone, flushed, so whoever runs it (a
person or the /autopilot chat) can follow along.

Another session starts only while the subscription's 5-hour and 7-day windows are under CEILING. The
reading comes from the sessions themselves: `--output-format stream-json` sends a `rate_limit_event`
within its first few lines and on every 1% change (seen in every logged run; not in the docs). No
reading yet counts as headroom, and one session always runs.

A merged ticket's worktree and branch are removed; a stopped ticket's stay for a person to look at.
The root checkout is only ever fetched, so `main` there falls behind as tickets merge: `git pull`.
Logs and the STOP file live in the temp dir, never in the repo: an untracked file there would make
/ship's "tree is not what you expected" check stop every run.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

LABEL = "ready-for-agent"
STUCK = "needs-human"
MAX_JOBS = 4  # lazy: a constant; make it a flag when a project wants more at once
CEILING = 0.80  # lazy: one ceiling for both windows; split them if the weekly one bites first
INSTALL = {"pnpm-lock.yaml": ["pnpm", "install", "--frozen-lockfile", "--prefer-offline"],
           "package-lock.json": ["npm", "ci"]}

# Latest utilization per window, 0..1, written by whichever session reported last.
usage: dict[str, float | None] = {"five_hour": None, "seven_day": None}
reported: set[int] = set()  # tickets whose session has sent at least one rate_limit_event


def say(line: str) -> None:
    print(line, flush=True)


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8").stdout.strip()


def git(cwd: str, *args: str, check: bool = False) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=check)
    return done.stdout.strip()


def parse(argv: list[str]) -> tuple[list[int], int | None, bool]:
    # The /autopilot chat passes the user's words as typed: `52 and 53`, `52, 53`.
    numbers, limit, serial, rest = [], None, False, iter(" ".join(argv).replace(",", " ").split())
    for arg in rest:
        if arg.lower() == "and":
            continue
        if arg == "--max":
            limit = int(next(rest))
        elif arg == "--serial":
            serial = True
        elif "-" in arg:
            low, high = map(int, arg.lstrip("#").split("-"))
            numbers += range(low, high + 1)
        else:
            numbers.append(int(arg.lstrip("#")))
    return sorted(set(numbers)), limit, serial


def ticket(n: int) -> dict:
    out = gh("issue", "view", str(n), "--json", "state,labels,title")
    if not out:
        return {"state": "MISSING", "labels": [], "title": ""}
    data = json.loads(out)
    data["labels"] = [label["name"] for label in data["labels"]]
    return data


def blocked(repo: str, n: int) -> bool:
    # Native dependency links, as /issues creates them. No API (or an error) reads as unblocked.
    out = gh("api", f"repos/{repo}/issues/{n}/dependencies/blocked_by",
             "--jq", '[.[] | select(.state == "open")] | length')
    return out.isdigit() and int(out) > 0


def runnable(repo: str, pending: list[int]) -> list[tuple[int, str]]:
    """The open, unlabelled, unblocked tickets in `pending`, lowest first; drops the closed and stuck ones from it."""
    found = []
    for n in list(pending):
        info = ticket(n)
        if info["state"] != "OPEN":
            say(f"#{n} skipped ({info['state'].lower()})")
            pending.remove(n)
        elif STUCK in info["labels"]:
            say(f"#{n} skipped (labelled {STUCK})")
            pending.remove(n)
        elif not blocked(repo, n):
            found.append((n, info["title"]))
    return found


def headroom(usage: dict, last_started: int | None, reported: set, running: dict) -> bool:
    """Whether one more session may start.

    Nothing running always may: the queue then moves one ticket at a time, as it did before. Otherwise
    wait for the newest session's first reading (seconds after it starts), then ask for both windows
    under CEILING. No reading at all counts as headroom.
    """
    if not running:
        return True
    if last_started in running and last_started not in reported:
        return False
    return all(value is None or value < CEILING for value in usage.values())


def gauge() -> str:
    """`5h 23% · 7d 41%`, or whatever is known so far."""
    parts = [f"{label} {value * 100:.0f}%" for label, value in zip(("5h", "7d"), usage.values()) if value is not None]
    return " · ".join(parts) or "usage unknown"


def milestone(event: dict) -> str | None:
    """A one-line summary of a stream-json event worth showing, or None."""
    if event.get("type") != "assistant":
        return None
    for block in event.get("message", {}).get("content", []):
        if block.get("type") != "tool_use":
            continue
        tool, args = block.get("name"), block.get("input", {})
        if tool == "Skill":
            return f"/{args.get('skill')}"
        command = args.get("command", "") if tool == "Bash" else ""
        for needle, text in ((STUCK, "flagged needs-human"), ("gh issue comment", "commented on the ticket"),
                             ("gh pr create", "opening PR"), ("gh pr merge", "merging"),
                             ("git switch -c", "branched"), ("git push", "pushing")):
            if needle in command:
                return text
    return None


def worktree(root: str, n: int, base: str) -> str:
    """A worktree for ticket n at <root>-worktrees/<n>, cut from the fetched `origin/<base>`; reused if it is there."""
    path = os.path.join(f"{root}-worktrees", str(n))
    if os.path.isdir(path):
        say(f"#{n} reusing worktree {path}")
        return path
    git(root, "fetch", "--quiet", "origin", check=True)
    git(root, "worktree", "add", "--quiet", "--detach", path, f"origin/{base}", check=True)
    for lock, command in INSTALL.items():
        if os.path.exists(os.path.join(path, lock)):
            exe = shutil.which(command[0])  # the .cmd shim on Windows; Popen won't find it by bare name
            if exe:
                subprocess.run([exe, *command[1:]], cwd=path, check=True, capture_output=True, text=True)
            else:
                say(f"#{n} {command[0]} is not on PATH; the session will have to install")
            break
    return path


def remove_worktree(root: str, path: str) -> None:
    """Drop a merged ticket's worktree and its branch, local and remote.

    /ship can't do this from inside: `main` is checked out in the root, so `gh pr merge --delete-branch`
    fails to switch to it and leaves the remote branch behind.
    """
    branch = git(path, "rev-parse", "--abbrev-ref", "HEAD")
    git(root, "worktree", "remove", "--force", path)
    if os.path.isdir(path):  # git refused -- a lock, or a junction inside; take the directory ourselves
        shutil.rmtree(path, ignore_errors=True)
        git(root, "worktree", "prune")
    if branch and branch != "HEAD":
        git(root, "branch", "-D", branch)
        git(root, "push", "--quiet", "origin", "--delete", branch)


def run(n: int, cwd: str, logs: str, claude: str) -> None:
    log_path = os.path.join(logs, f"{n}.log")
    env = {**os.environ, "CLAUDE_AUTOPILOT": "1"}
    # No `project` source: repos that vendored an old copy of these hooks wire it in their
    # .claude/settings.json, and that copy refuses /ship even with CLAUDE_AUTOPILOT set.
    # lazy: drops a repo's own settings.json (permissions, env) too; load `project` again once no repo vendors hooks.
    command = [claude, "-p", f"/build {n} auto", "--setting-sources", "user,local", "--permission-mode", "auto",
               "--output-format", "stream-json", "--verbose"]
    with open(log_path, "w", encoding="utf-8") as log, subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            env=env) as proc:
        for line in proc.stdout:
            log.write(line)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "rate_limit_event":
                windows = event.get("rate_limit_info", {}).get("unifiedWindows", {})
                for window in usage:
                    if window in windows:
                        usage[window] = windows[window].get("utilization")
                reported.add(n)
            elif event.get("type") == "system" and event.get("subtype") == "init":
                say(f"#{n} session {event.get('session_id')}  (claude --resume {event.get('session_id')})")
            elif event.get("type") == "result":
                cost = event.get("total_cost_usd")
                say(f"#{n} session ended{f' (${cost:.2f})' if cost else ''}: {str(event.get('result', ''))[-300:]}")
            elif text := milestone(event):
                say(f"#{n} {text}")
    say(f"#{n} log: {log_path}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows pipes default to cp1252
    try:
        numbers, limit, serial = parse(sys.argv[1:])
    except (ValueError, StopIteration):
        say(f"STOPPED: can't read {' '.join(sys.argv[1:])!r}; use numbers, ranges (51-55), --max N and --serial")
        return 1
    claude = shutil.which("claude")
    if not claude:
        say("STOPPED: `claude` is not on PATH")
        return 1
    repo = gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
    if not repo:
        say("STOPPED: not in a GitHub repo, or `gh` is not logged in")
        return 1
    root = git(os.getcwd(), "rev-parse", "--show-toplevel")
    if not root:
        say("STOPPED: not inside a git checkout")
        return 1
    base = gh("api", f"repos/{repo}", "--jq", ".default_branch") or "main"
    if not numbers:
        out = gh("issue", "list", "--label", LABEL, "--state", "open", "--limit", "200", "--json", "number")
        numbers = sorted(issue["number"] for issue in json.loads(out or "[]"))

    logs = os.path.join(tempfile.gettempdir(), "claude-autopilot", repo.replace("/", "-"))
    os.makedirs(logs, exist_ok=True)
    stop_file = os.path.join(logs, "STOP")
    if os.path.exists(stop_file):
        os.remove(stop_file)
    jobs = 1 if serial else MAX_JOBS
    say(f"autopilot {repo}: {', '.join(f'#{n}' for n in numbers) or 'nothing to do'}"
        f" -- {'one at a time' if serial else f'up to {jobs} at once'}, worktrees in {root}-worktrees")
    say(f"stop after the running ticket{'s' if jobs > 1 else ''}: create {stop_file}")

    done, pending = 0, list(numbers)
    running: dict[int, tuple[threading.Thread, str]] = {}
    queue: list[tuple[int, str]] = []
    halt = stopped = holding = False
    rescan, last_started = True, None
    while pending or running:
        for n, (thread, path) in list(running.items()):
            if thread.is_alive():
                continue
            del running[n]
            after = ticket(n)
            if after["state"] == "CLOSED":
                say(f"#{n} merged ✓")
                remove_worktree(root, path)
                done += 1
                rescan = True
            else:
                reason = "labelled needs-human, see the ticket" if STUCK in after["labels"] else "ticket still open"
                say(f"#{n} STOPPED: {reason}; worktree kept at {path}")
                stopped = halt = True
        if not halt and os.path.exists(stop_file):
            say(f"stopping on request after {', '.join(f'#{n}' for n in running) or 'nothing'}")
            halt = True
        if rescan and not halt:
            queue = runnable(repo, pending)
            rescan = False
        while queue and not halt and len(running) < jobs and (limit is None or done + len(running) < limit):
            if not headroom(usage, last_started, reported, running):
                over = any(value is not None and value >= CEILING for value in usage.values())
                if over and not holding:
                    say(f"holding at {gauge()}: nothing new starts until usage drops; "
                        f"{len(running)} running, {len(queue)} ready")
                holding = over
                break
            holding = False
            n, title = queue.pop(0)
            pending.remove(n)
            try:
                path = worktree(root, n, base)
            except subprocess.CalledProcessError as error:
                say(f"#{n} STOPPED: could not prepare its worktree: {str(error.stderr or '').strip()[-300:]}")
                stopped = halt = True
                break
            say(f"#{n} started ({gauge()}): {title}")
            thread = threading.Thread(target=run, args=(n, path, logs, claude), daemon=True)
            thread.start()
            running[n] = (thread, path)
            last_started = n
        if not running:
            left = ", ".join(f"#{n}" for n in pending)
            if stopped:
                say(f"autopilot stopped: {done} merged" + (f", left: {left}" if left else ""))
                return 1
            if halt:
                say(f"STOPPED on request: {done} merged" + (f", left: {left}" if left else ""))
                return 0
            if limit is not None and done >= limit:
                break
            if pending:
                say(f"STOPPED: every remaining ticket is blocked: {left}")
                return 1
            break
        time.sleep(5)

    say(f"autopilot done: {done} merged" + (f", left: {', '.join(f'#{n}' for n in pending)}" if pending else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
