---
name: autopilot
description: "Build, ship and merge a queue of tickets unattended: one fresh headless /build <n> auto session per ticket, each in its own git worktree, up to four at once in dependency order while usage allows. The first ticket that needs a human stops new starts. This chat is the control room."
disable-model-invocation: true
argument-hint: "[51-55 | 51 53 54 | empty = every ready-for-agent ticket] [--max N] [--serial]"
---

# Autopilot

Start the queue and report on it. You don't build anything here: every ticket runs in its own fresh `claude -p "/build <n> auto"` session in its own worktree (`<repo>-worktrees/<n>`), started by the script next to this file. Up to four run at once; another starts only while the 5-hour and weekly usage windows are under 80%. `--serial` runs one at a time.

1. **Start it in the background**, from the project root, with the user's arguments as given:
   `python ~/.claude/skills/autopilot/autopilot.py $ARGUMENTS` with `run_in_background: true`. Then watch its output with Monitor so each line reaches the chat as it's printed.
2. **Relay milestones** as they come: one short line each (`#51 merged ✓`, `#52 started: <title>`). Don't add commentary to routine lines. A `holding at …` line means usage is high and nothing new starts until it drops; say so once.
3. **On a `STOPPED` line**, read the ticket (`gh issue view <n> --comments`) and say in two or three lines what it needs from the user and how to resume: answer or fix on the ticket (its worktree path is in the output), remove the `needs-human` label, run `/autopilot` again. Tickets already running finish first; keep relaying them.
4. **While it runs**, the user may ask:
   - "how's it going?": summarise the output so far: running, merged, waiting.
   - "stop after this one": create the STOP file whose path the script printed. The tickets already running finish and nothing new starts.
   - "stop now": stop the background task. Each running ticket's branch stays in its worktree, so name every ticket that was mid-flight and its worktree path.
   - the details of a ticket: point to `claude --resume <session id>` from the output, or to the log path.
5. **When it ends**, remind the user that the script never touches their checkout: `git pull` brings `main` up to date.
