---
name: ship
description: "Take finished work from a feature branch to merged: shape it into layered commits that each pass the checks, push, open a PR, ask before merging, then land it and report what comes next. Started only by the user — typing /ship, or tapping \"Ship it — run /ship\" in /build's closing question, or /build auto inside an /autopilot run; tap-approval.py refuses any other call."
approval: tap
---

# Ship

The endgame, once the work is done and `/review` has been through it: commits worth reading, a PR that explains itself, and a merge that keeps both.

This skill names the commands rather than describing them. The flags carry the decisions — `--rebase` rather than `--squash` is the difference between seven commits on `main` and one — so leaving them to be re-derived each time is how a decision quietly reverses.

This skill never merges without being told to. Every stop — merge, or a situation it doesn't expect — is a question asked with the AskUserQuestion tool, never one written in the reply: a pending question notifies the user in the Remote Control app, a reply that just ends does not.

## Auto mode

The arguments contain `auto` (`/build … auto` passes it on under `/autopilot`, and nobody is watching). Same process, with these changes:

- **Merge without asking**, but only when step 2's per-commit loop passed on every commit and step 4 found nothing red. Otherwise don't merge.
- **Every place that would ask the user stops instead.** That covers the merge when the checks aren't green, pushed commits on the default branch, and the cases under "When the tree is not what you expected". Comment on the ticket with what you found, run `gh issue edit <n> --add-label needs-human --remove-label ready-for-agent`, and end the session. Never call AskUserQuestion.
- **Step 7's report goes on the ticket** as a `gh issue comment`. Nobody is reading this terminal.

## Process

### 1. Preflight

Five checks, all cheap, each catching a different way this goes wrong:

```bash
git rev-parse --abbrev-ref HEAD          # which branch
git status --short                        # is the tree clean
git log --oneline origin/main..HEAD       # what is unpushed
gh auth status                            # can we open a PR at all
gh api repos/{owner}/{repo} --jq '{default_branch,allow_rebase_merge,allow_auto_merge,delete_branch_on_merge}'
```

Read the base branch from `gh api`, **not** from `refs/remotes/origin/HEAD` — that ref is unset in this clone and `git symbolic-ref` on it simply fails.

**If HEAD is the default branch**, stop and rescue rather than pushing. The work is not lost and does not need redoing — provided nothing has been pushed yet:

```bash
git switch -c <type>/<issue>-<slug>   # the branch now points at the work
git branch -f main origin/main         # main goes back to where the remote has it
```

Confirm `git log --oneline origin/main..HEAD` still lists the work before going on. If the commits were already pushed to the default branch, say so and ask with AskUserQuestion how to proceed — rewriting published history is the user's call, not yours.

### 2. Shape the commits

The step that needs judgement, and the reason this is a skill and not a script.

If the work is one undifferentiated commit, or several commits that only make sense together, rebuild it. `git reset --soft <base>` puts every change back in the index without touching a file, and the pieces can then be committed in order.

What makes the layering right:

- **Dependency order, bottom up.** A module before the thing that imports it; the schema before the code that writes to it; test infrastructure before the tests that use it.
- **Each commit is one reason.** A commit that changes a module *and* renames something unrelated is two commits.
- **Each commit stands alone.** It passes the checks with nothing after it applied. Do not assert this — check it, with the checks for the areas touched (`CLAUDE.md § Agent skills`):

  ```bash
  for sha in $(git rev-list --reverse <base>..HEAD); do
    git -c advice.detachedHead=false checkout -q "$sha"
    <the area's checks>
  done
  git checkout -q <branch>
  ```

- **The tree is unchanged by the restructuring.** `git diff <original-sha> HEAD` must be empty. If it is not, the split dropped something.

Messages follow the repo's own voice — read `git log` before writing one. Here: a sentence-case subject that says what the change is *for* rather than what it touches, and a body that argues the reasoning rather than restating the diff. End with the attribution trailer the harness gives for this session, naming the model actually running (`Co-Authored-By: Claude <model> <noreply@anthropic.com>`).

### 3. Push and open the PR

First land on the latest base: other branches may have merged while this one was built (`/autopilot` runs several at once).

```bash
git fetch origin
git rebase origin/<default-branch>
```

A conflict where both sides add something (an import, a list entry, a function) is resolved by keeping both. Anything else stops here with AskUserQuestion (auto mode: comment, `needs-human`, end). After resolving, `git diff origin/<default-branch>` must show only this ticket's additions: nothing that was on the base may disappear. Then run step 2's per-commit loop again. If the merge in step 6 is later refused for conflicts, do this once more and push with `--force-with-lease`; a second refusal stops.

```bash
git push -u origin <branch>
gh pr create --base <default-branch> --head <branch> --title "<subject>" --body-file -
```

The body is drawn from the ticket, not invented: what it does, the decisions worth not re-deriving, anything the review changed, how to verify it, and anything deliberately left undone. Include `Closes #N` so the ticket closes itself on merge. Name the commits and what each one is, since the whole point of shaping them is that somebody can read them. End with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

### 4. Checks

**This repo has no CI.** `gh pr checks <n>` will report nothing — say so plainly rather than reading it as green. The gate is step 2's per-commit loop, which already ran the checks on every commit; if it didn't, run them on HEAD now and report the result.

If workflows appear later, the three outcomes are genuinely different: **green** → step 5; **red** → stop, report which check failed and what it said, do not merge and do not ask to; **no checks reported** → say so plainly; it is the user's call whether that is expected.

### 5. Ask before merging

Report the PR link, the check state, and the commits as they will land. Then ask with AskUserQuestion: **"Merge PR #N — rebase, delete branch"** (Recommended) / **"Not yet"**.

Wait for the tap. A green PR is not permission.

### 6. Land it

In a linked worktree (`git rev-parse --git-dir` names a `worktrees/` path, which is how `/autopilot` runs), merge without `--delete-branch` and skip the local sync below: `main` is checked out elsewhere, so `git checkout` would fail, and the autopilot runner deletes the branch and removes the worktree once the ticket closes.

```bash
gh pr merge <n> --rebase --delete-branch
```

`--rebase` because the layering from step 2 is the deliverable; a squash discards it and puts one commit on the default branch. `--delete-branch` unless preflight showed `delete_branch_on_merge` already on. `--auto` only when `allow_auto_merge` is true *and* the user asked to queue behind checks.

Then bring the local default branch back in line. A rebase merge rewrites the SHAs, so a pull would try to reconcile two versions of the same commits:

```bash
git checkout <default-branch>
git fetch --prune origin
git reset --hard origin/<default-branch>
```

Confirm afterwards: the commits are on the default branch, the tree is clean, and the checks pass there.

### 7. Report what comes next

Not a summary of what just happened — the user watched that. What to do next:

- **What this ticket left unfinished.** Verification steps its own ticket listed that have not been run yet, especially anything needing credentials or a live service.
- **What it unblocks.** Read it from the tracker (`gh issue list --label ready-for-agent`), do not guess. Say which tickets are ready now and why.
- **Debts left in the code.** Every `# lazy:` marker this branch added, with its ceiling and trigger (`/debt` lists them all), and anything else deliberately deferred and where it is written down.
- **Judgement calls worth revisiting**, if the review raised something you decided against.

## When the tree is not what you expected

Stop and ask with AskUserQuestion rather than working around it. Uncommitted changes you did not make, a branch that has diverged from its remote, a merge conflict against the base — each of these means the situation is not the one this process assumes, and a guess here costs more than a question.
